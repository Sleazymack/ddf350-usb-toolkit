"""Bounded original startup player and data wrapper. No hardware access."""
import hashlib
import json
import struct
import os
from pathlib import Path
import stat
import startup_player_blob as player
import startup_player_v1 as player_v1
import startup_player_loop as player_loop

BASE=0x08005000
PLAYER_BASE=0x080a8000
PLAYER_OFFSET=PLAYER_BASE-BASE
MAX_IMAGE_SIZE=0x080f5000-BASE
MAX_ASSET_SIZE=310000
TRAILER_MAGIC=b'DDF350-STARTUP-ANIMATION-v1!'
PLAYERS={1:player_v1,2:player,3:player_loop}
LOOP_MAGIC=b'DDFLOOP1'
# This format stores one 500-ms cycle of ten frames.
LOOP_FRAMES,LOOP_PERIOD_MS,LOOP_PLAYS=10,50,8
CURRENT_PLAYER=2
MAX_ENCODED_SIZE=PLAYER_OFFSET+max(len(p.CODE) for p in PLAYERS.values())+MAX_ASSET_SIZE+1024+4+len(TRAILER_MAGIC)
ORIGINAL_SITES={0x10afe:bytes.fromhex('4af0e7fb'),0x10c8a:bytes.fromhex('fff7ebfb')}
HEADER=struct.Struct('<8sHHHHI')

def require(ok,message):
    if not ok:raise ValueError(message)

def decode_asset(blob):
    require(isinstance(blob,bytes) and 52<=len(blob)<=MAX_ASSET_SIZE,'Unsupported startup animation size.')
    magic,w,h,count,colors,size=HEADER.unpack_from(blob)
    require(magic in (b'DDFANM1\0',LOOP_MAGIC) and 16<=w<=128 and w%2==0 and 16<=h<=160 and 1<=count<=40 and colors==16 and size==w*h//2 and size<=10240,'Unsupported startup animation header.')
    is_loop=magic==LOOP_MAGIC
    if is_loop:require(count==LOOP_FRAMES,'A simple loop requires ten frames.')
    cursor=52;current=bytearray(size);frames=[];durations=[]
    for _ in range(count):
        require(cursor+6<=len(blob),'Truncated startup frame.')
        duration,length=struct.unpack_from('<HI',blob,cursor);cursor+=6
        require(10<=duration<=1000 and cursor+length<=len(blob),'Invalid startup frame length.')
        if is_loop:require(duration==LOOP_PERIOD_MS,'A simple loop requires 50 ms per frame.')
        end=cursor+length;position=0
        while True:
            require(cursor+4<=end,'Truncated startup delta.')
            skip,n=struct.unpack_from('<HH',blob,cursor);cursor+=4
            if skip==65535 and n==0:
                require(cursor==end,'Trailing startup delta bytes.');break
            position+=skip
            require(n>0 and position+n<=size and cursor+n<=end,'Startup delta is outside its frame.')
            current[position:position+n]=blob[cursor:cursor+n];position+=n;cursor+=n
        frames.append(bytes(current));durations.append(duration)
    require(cursor==len(blob) and sum(durations)<=4000,'Unsupported startup animation duration or trailing data.')
    return {'width':w,'height':h,'frames':frames,'durations':durations,'palette':blob[20:52],'repeat_count':LOOP_PLAYS if is_loop else 1}

def description(blob):
    data=decode_asset(blob)
    plays=data['repeat_count']
    return {'width':data['width'],'height':data['height'],'frames':len(data['frames']),
            'display_frames':len(data['frames'])*plays,'repeat_count':plays,
            'cycle_duration_ms':sum(data['durations']),
            'duration_ms':sum(data['durations'])*plays,'display_width':240,'display_height':275,
            'asset_sha256':hashlib.sha256(blob).hexdigest(),'hardware_tested':False}

def read_asset_file(path):
    # Reuse the local-path restrictions without an import cycle at module load.
    import patch_firmware as p
    source=p.validate_local_path(path);p._check_local_volume(source,'Animation')
    require(stat.S_ISREG(source.lstat().st_mode),'Animation must be a regular file.')
    fd=os.open(source,os.O_RDONLY|getattr(os,'O_BINARY',0)|getattr(os,'O_NOFOLLOW',0))
    with os.fdopen(fd,'rb') as stream:
        info=os.fstat(stream.fileno())
        require(stat.S_ISREG(info.st_mode) and 52<=info.st_size<=MAX_ASSET_SIZE,'Invalid animation file size.')
        blob=stream.read(MAX_ASSET_SIZE+1)
    require(len(blob)==info.st_size,'Animation changed while reading.')
    decode_asset(blob);return blob

def _branch(address,target):
    delta=(target&~1)-address-4
    require(address%2==0 and -(1<<24)<=delta<(1<<24),'Startup branch outside range.')
    sign=(delta>>24)&1;j1=1^((delta>>23)&1)^sign;j2=1^((delta>>22)&1)^sign
    return struct.pack('<HH',0xf000|(sign<<10)|((delta>>12)&1023),0xd000|(j1<<13)|(j2<<11)|((delta>>1)&2047))

def version_for(asset):
    return 3 if asset[:8]==LOOP_MAGIC else CURRENT_PLAYER

def attach(base_image,asset,*,player_version=None):
    decode_asset(asset)
    if player_version is None:player_version=version_for(asset)
    require((player_version==3)==(asset[:8]==LOOP_MAGIC),'Startup format and player differ.')
    require(type(player_version) is int and player_version in PLAYERS,'Unknown startup player version.')
    selected=PLAYERS[player_version]
    extended=len(base_image)>=PLAYER_OFFSET
    if extended:
        import dashboard_custom as custom
        layout,_=custom.read_trailer(base_image)
        require(layout['schema']==12 and layout['wallpaper'] is not None and
                len(selected.CODE)<=custom.wallpaper.DATA_OFFSET-PLAYER_OFFSET and
                base_image[PLAYER_OFFSET:custom.wallpaper.DATA_OFFSET]==b'\xff'*(custom.wallpaper.DATA_OFFSET-PLAYER_OFFSET),
                'Dashboard overlaps the startup player area.')
    for site,signature in ORIGINAL_SITES.items():
        require(base_image[site:site+4]==signature,'Startup hook signature differs.')
    code=bytearray(selected.CODE)
    require(selected.DATA['base']==PLAYER_BASE and hashlib.sha256(code).hexdigest()==selected.DATA['sha256'],'Startup player code differs.')
    require(struct.unpack_from('<I',code)[0]==0x53475031,'Startup player configuration differs.')
    asset_offset=len(base_image) if extended else PLAYER_OFFSET+len(code)
    struct.pack_into('<II',code,4,BASE+asset_offset,len(asset))
    result=bytearray(base_image)
    for site,name in ((0x10afe,'boot_start'),(0x10c8a,'boot_cleanup_hook')):
        if player_version>=2 and site==0x10c8a:continue
        result[site:site+4]=_branch(BASE+site,selected.DATA['symbols'][name]['address'])
    if extended:
        result[PLAYER_OFFSET:PLAYER_OFFSET+len(code)]=code
        result+=asset
    else:result+=b'\xff'*(PLAYER_OFFSET-len(result))+code+asset
    metadata={'schema':1,'base_size':len(base_image),'asset_size':len(asset),'asset_sha256':hashlib.sha256(asset).hexdigest()}
    if player_version>=2:metadata.update(schema=4 if player_version==3 else 2,player=player_version)
    if extended:metadata.update(schema=3,player=player_version)
    encoded=json.dumps(metadata,sort_keys=True,separators=(',',':')).encode('ascii')
    encoded+=b' '*(-(len(result)+len(encoded)+4+len(TRAILER_MAGIC))%4)
    result+=encoded+struct.pack('<I',len(encoded))+TRAILER_MAGIC
    require(len(result)<=MAX_IMAGE_SIZE,'Photo et démarrage trop volumineux ensemble : réduis le nombre d’images du GIF ou garde le démarrage d’origine.' if extended else 'Startup animation exceeds the application partition.')
    return bytes(result)

def unpack(image,*,with_version=False):
    require(PLAYER_OFFSET+min(len(p.CODE) for p in PLAYERS.values())+52<len(image)<=MAX_IMAGE_SIZE and image.endswith(TRAILER_MAGIC),'Not a startup animation wrapper.')
    end=len(image)-len(TRAILER_MAGIC)-4;length=struct.unpack_from('<I',image,end)[0]
    require(0<length<=1024 and end-length>=PLAYER_OFFSET,'Invalid startup trailer size.')
    meta=json.loads(image[end-length:end])
    require(type(meta) is dict,'Invalid startup trailer.')
    version=1 if meta.get('schema')==1 else meta.get('player')
    require(type(version) is int and version in PLAYERS,'Invalid startup player version.')
    extended=meta.get('schema')==3
    keys={'schema','base_size','asset_size','asset_sha256'} | ({'player'} if extended or version>=2 else set())
    require(set(meta)==keys and type(meta['schema']) is int and (extended or meta['schema']=={1:1,2:2,3:4}[version]),'Invalid startup trailer.')
    size=meta['base_size']
    from dashboard_wallpaper import END
    require(type(size) is int and ((END<size<=END+4120) if extended else (626956<=size<PLAYER_OFFSET)) and
            type(meta['asset_size']) is int and 52<=meta['asset_size']<=MAX_ASSET_SIZE,'Invalid startup boundaries.')
    start=size if extended else PLAYER_OFFSET+len(PLAYERS[version].CODE)
    require(start+meta['asset_size']==end-length,'Startup asset boundary differs.')
    asset=image[start:start+meta['asset_size']]
    require(hashlib.sha256(asset).hexdigest()==meta['asset_sha256'],'Startup asset hash differs.')
    decode_asset(asset)
    require((version==3)==(asset[:8]==LOOP_MAGIC),'Startup format and player differ.')
    base=bytearray(image[:meta['base_size']])
    if extended:base[PLAYER_OFFSET:PLAYER_OFFSET+len(PLAYERS[version].CODE)]=b'\xff'*len(PLAYERS[version].CODE)
    for site,signature in ORIGINAL_SITES.items():base[site:site+4]=signature
    return (bytes(base),asset,version) if with_version else (bytes(base),asset)

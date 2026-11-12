"""Convert a user GIF to a bounded indexed delta asset; never patch a radio.

This is an intermediate animation format, NOT an installable firmware file.
Pillow is used only for deterministic media conversion, preserving frame order.
"""
import argparse
import hashlib
import io
import json
from pathlib import Path
import struct
import sys

MAGIC=b'DDFANM1\0'
HEADER=struct.Struct('<8sHHHHI')

def encode_delta(before,after):
    if len(before)!=len(after) or len(after)>65534:raise ValueError('Invalid frame length')
    result=bytearray();position=0;cursor=0
    while position<len(after):
        while position<len(after) and before[position]==after[position]:position+=1
        if position==len(after):break
        start=position;last=position+1;position+=1
        while position<len(after):
            if before[position]!=after[position]:last=position+1
            if position-last>=4:break
            position+=1
        result+=struct.pack('<HH',start-cursor,last-start)+after[start:last]
        cursor=last;position=last
    result+=struct.pack('<HH',65535,0)
    return bytes(result)

def decode_delta(before,payload):
    result=bytearray(before);position=0;offset=0
    while True:
        if offset+4>len(payload):raise ValueError('Truncated delta')
        skip,count=struct.unpack_from('<HH',payload,offset);offset+=4
        if skip==65535 and count==0:
            if offset!=len(payload):raise ValueError('Trailing delta bytes')
            return bytes(result)
        position+=skip
        if not count or position+count>len(result) or offset+count>len(payload):raise ValueError('Invalid delta bounds')
        result[position:position+count]=payload[offset:offset+count]
        position+=count;offset+=count

def decode_asset(blob):
    if len(blob)<HEADER.size+32:raise ValueError('Truncated animation header')
    magic,width,height,count,colors,frame_bytes=HEADER.unpack_from(blob)
    if magic!=MAGIC or not (16<=width<=240 and width%2==0 and 16<=height<=320 and 1<=count<=120 and colors==16 and frame_bytes==width*height//2 and frame_bytes<=65534):
        raise ValueError('Invalid animation header')
    offset=HEADER.size+32;current=bytes(frame_bytes);frames=[];durations=[]
    for _ in range(count):
        if offset+6>len(blob):raise ValueError('Truncated frame header')
        duration,length=struct.unpack_from('<HI',blob,offset);offset+=6
        if not (10<=duration<=1000) or offset+length>len(blob):raise ValueError('Invalid frame payload')
        current=decode_delta(current,blob[offset:offset+length]);offset+=length
        frames.append(current);durations.append(duration)
    if offset!=len(blob):raise ValueError('Trailing animation bytes')
    return width,height,frames,durations

def build(source,width,output):
    from PIL import Image,ImageSequence
    source=Path(source);output=Path(output)
    if output.exists():raise ValueError('Use a new output directory')
    with Image.open(source) as gif:
        if gif.format!='GIF' or not 1<=gif.n_frames<=40:raise ValueError('Unsupported GIF: at most 40 frames')
        height=round(width*gif.height/gif.width)
        if width%2 or not (16<=width<=128 and 16<=height<=160):raise ValueError('Invalid target dimensions')
        frames=[];durations=[]
        for frame in ImageSequence.Iterator(gif):
            durations.append(max(10,min(1000,frame.info.get('duration',100))))
            frames.append(frame.convert('RGB').resize((width,height),Image.Resampling.LANCZOS))
    if sum(durations)>4000:raise ValueError('Animation exceeds four seconds')
    # A shared palette keeps stationary background pixels stable between frames.
    contact=Image.new('RGB',(width,height*len(frames)))
    for index,frame in enumerate(frames):contact.paste(frame,(0,index*height))
    palette_image=contact.quantize(colors=16,method=Image.Quantize.MEDIANCUT)
    palette=palette_image.getpalette()[:48]
    palette_rgb565=bytearray()
    for i in range(0,48,3):
        r,g,b=palette[i:i+3];palette_rgb565+=struct.pack('<H',((r>>3)<<11)|((g>>2)<<5)|(b>>3))
    indexed=[];packed=[]
    for frame in frames:
        indexed_frame=frame.quantize(palette=palette_image,dither=Image.Dither.NONE)
        values=indexed_frame.tobytes()
        if max(values)>15:raise ValueError('Palette index outside four-bit range')
        packed.append(bytes((values[i]<<4)|values[i+1] for i in range(0,len(values),2)))
        indexed.append(indexed_frame)
    blob=bytearray(HEADER.pack(MAGIC,width,height,len(frames),16,width*height//2)+palette_rgb565)
    current=bytes(width*height//2)
    for frame,duration in zip(packed,durations):
        delta=encode_delta(current,frame)
        if decode_delta(current,delta)!=frame:raise RuntimeError('Frame round-trip mismatch')
        blob+=struct.pack('<HI',duration,len(delta))+delta;current=frame
    decoded=decode_asset(blob)
    if decoded!=(width,height,packed,durations):raise RuntimeError('Animation round-trip mismatch')
    for malformed in (b'',blob[:HEADER.size-1],blob[:-1],blob+b'junk'):
        try:decode_asset(malformed)
        except ValueError:pass
        else:raise RuntimeError('Corrupt animation accepted')
    sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
    import startup_animation
    startup_animation.decode_asset(bytes(blob))
    output.mkdir(parents=True)
    (output/'animation.ddfa').write_bytes(blob)
    indexed[0].save(output/'apercu.gif',save_all=True,append_images=indexed[1:],duration=durations,loop=0,optimize=False,disposal=2)
    with Image.open(output/'apercu.gif') as check:
        if check.n_frames!=len(frames):raise RuntimeError('Preview frame count differs')
    report={'status':'intermediate-asset-only-not-installable','source_sha256':hashlib.sha256(source.read_bytes()).hexdigest(),
        'width':width,'height':height,'frames':len(frames),'duration_ms':sum(durations),'colors':16,
        'encoded_bytes':len(blob),'mutable_index_buffer_bytes':width*height//2,'palette_bytes':32,
        'all_frames_packed_without_deltas':sum(map(len,packed)),
        'roundtrip_all_frames':'PASS','corruption_refusal':'PASS',
        'asset_sha256':hashlib.sha256(blob).hexdigest(),
        'native_player_implemented':True,'firmware_modified':False,
        'format':'DDFANM1; little-endian RGB565 palette; high nibble first; per-frame skip/copy runs',
        'remaining':['Measure heap budget, LCD rendering and frame timing on hardware']}
    (output/'rapport.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    return report

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source',type=Path);parser.add_argument('output',type=Path);parser.add_argument('--width',type=int,default=128)
    args=parser.parse_args()
    print(json.dumps(build(args.source,args.width,args.output),indent=2))

"""Bounded local startup media conversion and faithful asset previews; no USB."""
from dataclasses import dataclass
import io
import os
import stat
import struct
import warnings

import startup_animation as animation
import startup_photo as photo
from startup.convert_gif import HEADER, MAGIC, encode_delta, decode_delta

MAX_SOURCE_BYTES=25*1024*1024
MAX_SOURCE_EDGE=4096
MAX_SOURCE_PIXELS=8*1024*1024
# Decimal kB: 280,000 bytes is already over the limit.
GIF_BYTES=280_000
GIF_MAX_FRAMES=20
GIF_MIN_MS=200
GIF_MAX_MS=1000
GIF_MAX_DURATION=4000
GIF_HELP='GIF : moins de 280 Ko, 5 images/s maximum, 4 s maximum (2 à 20 images).'
GIF_TIMING='Chaque image du GIF doit durer entre 200 et 1 000 ms (5 images/s maximum).'
GIF_SIZE='Le GIF doit faire moins de 280 Ko (280 000 octets), avant et après conversion.'
GIF_COUNT='Le GIF doit contenir 2 à 20 images et durer 4 secondes maximum.'
FORMATS={'GIF','PNG','JPEG','BMP'}


@dataclass(frozen=True)
class Media:
    asset: bytes
    name: str
    kind: str

    @property
    def info(self):
        if self.kind=='photo':
            return {'width':photo.WIDTH,'height':photo.HEIGHT,'frames':1}
        return animation.description(self.asset)


def read_source(path):
    import patch_firmware as p
    source=p.validate_local_path(path);p._check_local_volume(source,'Startup media')
    if not stat.S_ISREG(source.lstat().st_mode):raise ValueError('Le média doit être un fichier local ordinaire.')
    fd=os.open(source,os.O_RDONLY|getattr(os,'O_BINARY',0)|getattr(os,'O_NOFOLLOW',0))
    with os.fdopen(fd,'rb') as stream:
        info=os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or not 1<=info.st_size<=MAX_SOURCE_BYTES:
            raise ValueError('Le média dépasse la limite de 25 Mo ou est vide.')
        blob=stream.read(MAX_SOURCE_BYTES+1)
    if len(blob)!=info.st_size:raise ValueError('Le média a changé pendant sa lecture.')
    return source.name,blob


def from_file(path):
    name,blob=read_source(path)
    return from_bytes(blob,name=name)


def fitted(image):
    from PIL import Image, ImageOps
    frame=ImageOps.exif_transpose(image).convert('RGBA')
    frame=ImageOps.contain(frame,(photo.WIDTH,photo.HEIGHT),Image.Resampling.LANCZOS)
    box=Image.new('RGB',(photo.WIDTH,photo.HEIGHT))
    box.paste(frame,((photo.WIDTH-frame.width)//2,(photo.HEIGHT-frame.height)//2),frame.getchannel('A'))
    return box


def validate_new_animation(asset):
    if len(asset)>=GIF_BYTES:raise ValueError(GIF_SIZE)
    data=animation.decode_asset(asset)
    if data['repeat_count']!=1 or not 2<=len(data['frames'])<=GIF_MAX_FRAMES or sum(data['durations'])>GIF_MAX_DURATION:
        raise ValueError(GIF_COUNT)
    if min(data['durations'])<GIF_MIN_MS or max(data['durations'])>GIF_MAX_MS:raise ValueError(GIF_TIMING)


def from_bytes(blob,*,name='media'):
    from PIL import Image,UnidentifiedImageError
    if not isinstance(blob,bytes) or not 1<=len(blob)<=MAX_SOURCE_BYTES:
        raise ValueError('Le média dépasse la limite de 25 Mo ou est vide.')
    if blob.startswith((b'GIF87a',b'GIF89a')) and len(blob)>=GIF_BYTES:raise ValueError(GIF_SIZE)
    try:
        with warnings.catch_warnings():
            warnings.simplefilter('error',Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(blob)) as image:
                if image.format not in FORMATS:raise ValueError('Formats acceptés : PNG, JPEG, BMP ou GIF.')
                def check_size():
                    w,h=image.size
                    if not (1<=w<=MAX_SOURCE_EDGE and 1<=h<=MAX_SOURCE_EDGE and w*h<=MAX_SOURCE_PIXELS):
                        raise ValueError('Image trop grande : 4096 pixels par côté et 8 mégapixels maximum.')
                check_size()
                if image.format!='GIF':
                    if getattr(image,'n_frames',1)!=1:raise ValueError('Pour une animation, utilise un GIF ; les PNG animés ne sont pas acceptés.')
                    # The LCD stores the high RGB565 byte first.
                    rgb=fitted(image).tobytes()
                    pixels=b''.join(struct.pack('>H',(r>>3)<<11 | (g>>2)<<5 | b>>3) for r,g,b in zip(rgb[0::3],rgb[1::3],rgb[2::3]))
                    return Media(pixels,str(name),'photo')
                if len(blob)>=GIF_BYTES:raise ValueError(GIF_SIZE)
                frames=[];durations=[];total_pixels=0
                for index in range(GIF_MAX_FRAMES+1):
                    try:image.seek(index)
                    except EOFError:break
                    check_size()
                    if index==GIF_MAX_FRAMES:raise ValueError(GIF_COUNT)
                    total_pixels+=image.width*image.height
                    if total_pixels>64*1024*1024:raise ValueError('Le GIF décompressé dépasse 64 mégapixels.')
                    dt=image.info.get('duration')
                    if type(dt) is not int or not GIF_MIN_MS<=dt<=GIF_MAX_MS:raise ValueError(GIF_TIMING)
                    durations.append(dt)
                    if sum(durations)>GIF_MAX_DURATION:raise ValueError(GIF_COUNT)
                    area=Image.new('RGB',(240,275))
                    area.paste(fitted(image),(24,32-22))
                    frames.append(area.resize((96,110),Image.Resampling.LANCZOS))
                if len(frames)<2:raise ValueError(GIF_COUNT)
    except (UnidentifiedImageError,Image.DecompressionBombError,Image.DecompressionBombWarning,OSError,EOFError) as error:
        raise ValueError('Le fichier image est illisible, incomplet ou trop grand.') from error
    w,h=frames[0].size
    sheet=Image.new('RGB',(w,h*len(frames)))
    for idx,frame in enumerate(frames):sheet.paste(frame,(0,h*idx))
    palette=sheet.quantize(colors=16,method=Image.Quantize.MEDIANCUT)
    values=bytes(palette.getpalette()[:48]).ljust(48,b'\0')
    colors=b''.join(struct.pack('<H',(r>>3)<<11 | (g>>2)<<5 | b>>3) for r,g,b in zip(values[::3],values[1::3],values[2::3]))
    result=bytearray(HEADER.pack(MAGIC,w,h,len(frames),16,w*h//2)+colors)
    prior=bytes(w*h//2)
    for frame,dt in zip(frames,durations):
        indexed=frame.quantize(palette=palette,dither=Image.Dither.NONE).tobytes()
        if max(indexed)>15:raise ValueError('Palette invalide.')
        packed=bytes((hi<<4)|lo for hi,lo in zip(indexed[::2],indexed[1::2]))
        delta=encode_delta(prior,packed)
        if decode_delta(prior,delta)!=packed:raise ValueError('Échec de vérification du média converti.')
        result+=struct.pack('<HI',dt,len(delta))+delta;prior=packed
    asset=bytes(result);validate_new_animation(asset)
    return Media(asset,str(name),'gif')


def preview_media(media):
    if media.kind!='photo':return preview_cycle(media.asset)
    from PIL import Image
    rgb=bytearray()
    for (c,) in struct.iter_unpack('>H',media.asset):
        r,g,b=c>>11,(c>>5)&63,c&31
        rgb.extend(((r<<3)|(r>>2),(g<<2)|(g>>4),(b<<3)|(b>>2)))
    screen=Image.new('RGB',(240,320))
    screen.paste(Image.frombytes('RGB',(photo.WIDTH,photo.HEIGHT),bytes(rgb)),(24,32))
    return [screen],[]


def preview_cycle(asset):
    """Return the RGB565-decoded frames, with the player's integer scaling."""
    from PIL import Image
    data=animation.decode_asset(asset);w,h=data['width'],data['height']
    palette=[]
    for value, in struct.iter_unpack('<H',data['palette']):
        r=(value>>11)&31;g=(value>>5)&63;b=value&31
        palette.append(((r<<3)|(r>>2),(g<<2)|(g>>4),(b<<3)|(b>>2)))
    result=[]
    for packed in data['frames']:
        colors=[palette[n] for value in packed for n in (value>>4,value&15)]
        screen=Image.new('RGB',(240,320),'black')
        area=Image.new('RGB',(240,275))
        area.putdata([colors[(y*h//275)*w+x*w//240] for y in range(275) for x in range(240)])
        screen.paste(area,(0,22));result.append(screen)
    return result,list(data['durations'])


def self_test():
    from PIL import Image
    for fmt in ('PNG','JPEG','BMP'):
        stream=io.BytesIO();Image.new('RGB',(24,32),'cyan').save(stream,format=fmt)
        media=from_bytes(stream.getvalue())
        if media.kind!='photo' or preview_media(media)[0][0].getbbox()!=(24,32,216,288):
            raise RuntimeError('Startup photo self-test failed')
    def gif(ms):
        stream=io.BytesIO()
        Image.new('RGB',(24,32),'red').save(stream,format='GIF',save_all=True,append_images=[Image.new('RGB',(24,32),'blue')],duration=ms)
        return stream.getvalue()
    if from_bytes(gif(200)).info['duration_ms']!=400:raise RuntimeError('GIF self-test failed')
    try:from_bytes(gif(100))
    except ValueError:pass
    else:raise RuntimeError('Fast GIF accepted')
    return True

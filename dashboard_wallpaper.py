"""Single fixed-format opaque LVGL wallpaper; no original photo metadata or paths."""
import base64
import hashlib
import io
import struct

WIDTH,HEIGHT=240,320
PALETTE_BYTES=256*4
DATA_BYTES=PALETTE_BYTES+WIDTH*HEIGHT
TEXT_BYTES=4*((DATA_BYTES+2)//3)
JSON_LIMIT=TEXT_BYTES+4096
# Leave both unmodified native startup player binaries their fixed code slot.
PLAYER_OFFSET=0xa3000
DATA_OFFSET=PLAYER_OFFSET+2048
END=DATA_OFFSET+DATA_BYTES
BASE=0x08005000

def raw(text):
    if type(text) is not str or len(text)!=TEXT_BYTES:raise ValueError('Invalid wallpaper size.')
    try:blob=base64.b64decode(text,validate=True)
    except (ValueError,UnicodeError) as exc:raise ValueError('Invalid wallpaper encoding.') from exc
    if (len(blob)!=DATA_BYTES or blob[3:PALETTE_BYTES:4]!=bytes([255])*256
            or base64.b64encode(blob).decode('ascii')!=text):raise ValueError('Invalid wallpaper palette or pixels.')
    return blob

def convert(data):
    from PIL import Image,ImageOps
    if not 0<len(data)<=25*1024*1024:raise ValueError('Photo : 25 Mio maximum.')
    try:opened=Image.open(io.BytesIO(data))
    except Image.DecompressionBombError as error:raise ValueError('Photo trop grande.') from error
    with opened as image:
        if image.format not in ('PNG','JPEG','BMP','WEBP') or max(image.size)>4096 or image.width*image.height>8*1024*1024 or getattr(image,'is_animated',False):
            raise ValueError('Choisis une photo fixe PNG, JPEG, BMP ou WebP (4096 px maximum).')
        image=ImageOps.fit(ImageOps.exif_transpose(image).convert('RGBA'),(WIDTH,HEIGHT),Image.Resampling.LANCZOS)
        rgb=Image.new('RGB',image.size);rgb.paste(image,mask=image.getchannel('A'))
        q=rgb.quantize(colors=256,method=Image.Quantize.MEDIANCUT)
        palette=bytes(q.getpalette()[:768]).ljust(768,b'\0')
        blob=b''.join(bytes((b,g,r,255)) for r,g,b in zip(palette[::3],palette[1::3],palette[2::3]))+q.tobytes()
    return base64.b64encode(blob).decode('ascii')

def photo(text):
    from PIL import Image
    blob=raw(text);pal=blob[:PALETTE_BYTES]
    img=Image.frombytes('P',(WIDTH,HEIGHT),blob[PALETTE_BYTES:])
    img.putpalette(bytes(n for b,g,r in zip(pal[::4],pal[1::4],pal[2::4]) for n in (r,g,b)))
    return img.convert('RGB')

def descriptor(height=HEIGHT):
    if not 1<=height<=HEIGHT:raise ValueError('Invalid wallpaper viewport.')
    return struct.pack('<III',10|(WIDTH<<10)|(height<<21),PALETTE_BYTES+WIDTH*height,BASE+DATA_OFFSET)

def stored(spec):
    text=spec.get('wallpaper')
    if spec['schema']==12 and text is not None:return {**spec,'wallpaper':hashlib.sha256(raw(text)).hexdigest()}
    return spec

def restore(spec,image,metadata_offset):
    if isinstance(spec,dict) and spec.get('schema')==12 and spec.get('wallpaper') is not None:
        if not END<=metadata_offset<=END+3:raise ValueError('Invalid embedded wallpaper boundary.')
        blob=image[DATA_OFFSET:END]
        if hashlib.sha256(blob).hexdigest()!=spec['wallpaper']:raise ValueError('Wallpaper verification failed.')
        return {**spec,'wallpaper':base64.b64encode(blob).decode('ascii')}
    return spec

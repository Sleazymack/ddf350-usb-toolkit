"""Build the three 240 x 320 presets as indexed pixels on the native LCD grid.

Run under Windows with Pillow and the system Arial/Consolas bold fonts.
No reference bitmaps, intermediate scaling or partial-coverage pixels are used.
"""
import base64
import json
import math
import zlib
from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

WIDTH, HEIGHT = 240, 320
BLACK, PANEL, RECESS, FRAME, SILVER, WHITE, LIME, OLIVE = range(8)
CYAN, TEAL, AMBER, BRONZE, VIOLET, PLUM, BLUE, PINK = range(8, 16)
COLOR = (
    '000000', '111922', '202c37', '465766', 'a7bac8', 'f2f7fa', 'b6fa24', '405d17',
    '1ee0eb', '12515e', 'ffad38', '684321', 'cd5aff', '562575', '397dff', 'efabff',
)
RGB = [bytes.fromhex(hex_color) for hex_color in COLOR]
CHARACTERS = '0123456789- %+'

def canvas(size):
    return Image.new('P', size, BLACK)

@lru_cache(maxsize=64)
def font(size, italic=False, numeric=False):
    name = 'consolab.ttf' if numeric else 'arialbi.ttf' if italic else 'arialbd.ttf'
    return ImageFont.truetype(name, size)

def label(draw, xy, text, size, color, anchor='lm', italic=False):
    draw.fontmode = '1'
    draw.text(xy, text, font=font(size, italic), fill=color, anchor=anchor)

def indexed(image):
    """Zero is a transparent pixel. All visible palette entries are fully opaque."""
    colors = sorted(set(image.tobytes()) - {BLACK})
    bits = next(n for n in (1, 2, 4) if len(colors) < 1 << n)
    lookup = [0] * 256
    palette = bytearray(4 << bits)
    for index, color in enumerate(colors, 1):
        r, g, b = RGB[color]
        lookup[color] = index
        palette[4*index:4*index+4] = bytes((b, g, r, 255))
    pixels = image.tobytes()
    per_byte = 8 // bits
    for y in range(image.height):
        row = pixels[y*image.width:(y+1)*image.width]
        for x in range(0, image.width, per_byte):
            byte = 0
            for j, color in enumerate(row[x:x+per_byte]):
                byte |= lookup[color] << (8 - bits * (j+1))
            palette.append(byte)
    return [*image.size, bits, base64.b85encode(zlib.compress(palette, 9)).decode('ascii')]

def point(cx, cy, radius, degrees):
    angle = math.radians(degrees)
    return round(cx+radius*math.cos(angle)), round(cy+radius*math.sin(angle))

def outline(draw, points, color, width=1):
    draw.line([*points, points[0]], fill=color, width=width)

def cell(face, channel, number, points, on):
    """Store the on-state at exactly the coordinates of the unlit polygon."""
    name = f's{channel}_{number}'
    xs, ys = zip(*points)
    x, y = min(xs), min(ys)
    sprite = canvas((max(xs)-x+1, max(ys)-y+1))
    local=[(px-x,py-y) for px,py in points]
    draw=ImageDraw.Draw(sprite)
    draw.polygon(local,fill=on)
    # A single cut chrome edge uses solid pixels, including on angled cells.
    draw.line(local[:2],fill=WHITE if on in (LIME,CYAN) else SILVER)
    face['sprites'][name] = indexed(sprite)
    face['lamps'].append(dict(sprite=name, x=x, y=y, channel=channel,
                              threshold=math.ceil((number+1)*100/16)))

def header(draw, face, accent):
    draw.polygon([(4,10),(12,2),(235,2),(235,36),(229,42),(4,42)], fill=PANEL)
    draw.line([(4,22),(4,10),(12,2),(42,2)], fill=accent, width=2)
    draw.line([(5,42),(228,42),(235,35)], fill=FRAME)
    for ch, x in ((1,14),(2,92)):
        label(draw, (x,12), f'CH{ch}', 12, SILVER)
        face['digits'][str(ch)] = [x,21,9,16,4]
    for x in (79,156):
        draw.line([(x,9),(x,35)], fill=RECESS)
    draw.rectangle((171,8,202,18), outline=SILVER)
    draw.rectangle((203,11,205,15), fill=SILVER)
    face['battery'] = [174,11,26,5]
    face['digits']['0'] = [169,21,9,16,3]

def strip(draw, face):
    for ch, y, accent, dark in ((3,56,LIME,OLIVE),(4,187,CYAN,TEAL)):
        border = [(4,y+21),(22,y),(82,y),(91,y+7),(221,y+7),(235,y+21),
                  (235,y+95),(220,y+110),(16,y+110),(4,y+98)]
        draw.polygon(border, fill=PANEL)
        outline(draw, border, FRAME)
        draw.line([(5,y+36),(5,y+21),(22,y+1),(82,y+1),(91,y+8),(127,y+8)], fill=accent, width=2)
        draw.line([(12,y+101),(18,y+107),(217,y+107),(232,y+92)], fill=dark, width=2)
        label(draw, (18,y+23), f'CH{ch}', 23, accent, italic=True)
        for x in range(84,127,5):
            draw.line([(x,y+27),(x+10,y+17)],fill=RECESS,width=2)
        draw.line([(10,y+45),(17,y+38),(67,y+38),(78,y+27),(116,y+27),(132,y+11),(219,y+11)],
                  fill=SILVER,width=2)
        draw.line([(19,y+40),(68,y+40),(79,y+29),(117,y+29)],fill=FRAME)
        face['digits'][str(ch)] = [134,y+13,17,27,4]
        bezel = [(10,y+74),(19,y+48),(229,y+48),(220,y+74)]
        draw.polygon(bezel, fill=BLACK)
        outline(draw, bezel, SILVER)
        for i in range(16):
            x=21+13*i
            poly=[(x,y+51),(x+10,y+51),(x+3,y+71),(x-7,y+71)]
            cell(face,ch,i,poly,AMBER if i>=14 else accent)
            draw.polygon(poly,fill=BRONZE if i>=14 else dark)
        for i in range(9):
            x = 17+25*i
            draw.line([(x,y+78),(x,y+83 if i%2==0 else y+81)], fill=SILVER)
        for x, txt, anchor in ((12,'-100','lm'),(68,'-50','mm'),(117,'0','mm'),(167,'+50','mm'),(225,'+100','rm')):
            label(draw,(x,y+93),txt,12,SILVER,anchor)

def led(draw, face):
    for ch, cy, accent, dark, stop in ((3,118,LIME,OLIVE,AMBER),(4,254,CYAN,TEAL,BLUE)):
        cx, radius = 120,56
        for i in range(16):
            start=135+i*270/16+1.6
            end=135+(i+1)*270/16-1.6
            poly=[point(cx,cy,r,start+(end-start)*j/4)
                  for r,indices in ((radius,range(5)),(radius-11,reversed(range(5)))) for j in indices]
            cell(face,ch,i,poly,stop if i>=14 else accent)
            draw.polygon(poly,fill=BRONZE if i>=14 and ch==3 else dark)
        for i in range(5):
            angle=135+i*67.5
            draw.line([point(cx,cy,radius+3,angle),point(cx,cy,radius+7,angle)],fill=SILVER)
        label(draw,(cx,cy-radius-8),'0',11,SILVER,'mb')
        for x,y,txt,anchor in ((55,cy-24,'-50','rm'),(185,cy-24,'+50','lm'),
                               (73,cy+47,'-100','rm'),(167,cy+47,'+100','lm')):
            label(draw,(x,y),txt,13,SILVER,anchor)
        label(draw,(cx,cy-12),f'CH{ch}',20,WHITE,'mm',True)
        draw.line([(cx-24,cy+1),(cx+21,cy+1),(cx+25,cy-2)],fill=accent)
        face['digits'][str(ch)]=[cx-37,cy+6,15,24,4]

def circle(draw, cx, cy, radius, **kwargs):
    draw.ellipse((cx-radius,cy-radius,cx+radius,cy+radius), **kwargs)

def purple(draw, face):
    # A single bank of opaque silver needle silhouettes serves both dials.
    # Cropped masks travel around each pivot without scaling or rotation on the LCD.
    frames = []
    for i in range(101):
        angle = 140+260*i/100
        origin = 42
        mask = canvas((2*origin+1,2*origin+1))
        tip = point(origin,origin,40,angle)
        base1=point(origin,origin,2,angle+90)
        base2=point(origin,origin,2,angle-90)
        ImageDraw.Draw(mask).polygon([base1,tip,base2],fill=WHITE)
        x,y,r,b=mask.getbbox()
        name=f'needle{i}'
        face['sprites'][name]=indexed(mask.crop((x,y,r,b)))
        frames.append([name,x-origin,y-origin])
    draw.line([(12,166),(41,195),(87,195),(102,210)],fill=PLUM,width=3)
    draw.line([(149,146),(160,157),(191,157),(216,182)],fill=PLUM,width=2)
    for ch,cx,cy,radius,accent,dark in ((3,80,124,72,VIOLET,PLUM),(4,165,242,66,LIME,OLIVE)):
        circle(draw,cx,cy,radius+2,outline=FRAME)
        circle(draw,cx,cy,radius,outline=dark,width=3)
        box=(cx-radius+5,cy-radius+5,cx+radius-5,cy+radius-5)
        draw.arc(box,140,400,fill=accent,width=3)
        draw.arc(box,200,267,fill=PINK if ch==3 else WHITE,width=1)
        for i in range(21):
            angle=140+260*i/20
            draw.line([point(cx,cy,radius-10,angle),point(cx,cy,radius-(18 if i%5==0 else 14),angle)],
                      fill=WHITE if i%5==0 else accent,width=2 if i%5==0 else 1)
        label(draw,(cx,cy-radius+25),'0',11,SILVER,'mm')
        for angle,txt in ((205,'-50'),(335,'+50')):
            label(draw,point(cx,cy,radius-21,angle),txt,10,SILVER,'mm')
        for angle,txt in ((140,'-100'),(400,'+100')):
            x,y=point(cx,cy,radius-25,angle)
            label(draw,(x,y+3),txt,10,SILVER,'mm')
        # These panels sit outside the pointer's sweep.
        x, y = (162,109) if ch==3 else (10,225)
        label(draw,(x,y-11),f'CH{ch}',20,accent,italic=True)
        draw.line([(x,y+4),(x+56,y+4),(x+63,y-3)],fill=dark,width=2)
        face['digits'][str(ch)]=[x,y+13,14,23,4]
        hub=canvas((9,9));hd=ImageDraw.Draw(hub)
        hd.ellipse((0,0,8,8),fill=dark,outline=accent);hd.rectangle((3,3,5,5),fill=WHITE)
        face['sprites'][f'hub{ch}']=indexed(hub)
        face['hands'].append(dict(channel=ch,cx=cx,cy=cy,frames=frames,hub=f'hub{ch}'))

def glyphs(face,key):
    for ch in range(5):
        _,_,width,height,_=face['digits'][str(ch)]
        color=WHITE if ch<3 or key=='strip_drift' else VIOLET if key=='purple_drift' and ch==3 else LIME if ch==3 or key=='purple_drift' else CYAN
        size=max(10,round(height*1.03))
        # Choose a real hinted size that fits even the widest glyph. Align all
        # signs and numbers on one baseline to avoid jitter between readings.
        alphabet=CHARACTERS if ch else CHARACTERS[:-1]
        while max(font(size,numeric=True).getbbox(s,anchor='ls')[2] for s in alphabet)>width:
            size-=1
        typeface=font(size,numeric=True)
        top=min(typeface.getbbox(s,anchor='ls')[1] for s in alphabet)
        bottom=max(typeface.getbbox(s,anchor='ls')[3] for s in alphabet)
        baseline=(height-(bottom-top))//2-top
        for i,s in enumerate(alphabet):
            img=canvas((width,height));d=ImageDraw.Draw(img);d.fontmode='1'
            d.text((width//2,baseline),s,font=typeface,anchor='ms',fill=color)
            face['sprites'][f'd{ch}_{i}']=indexed(img)

def band_parts(panel,key):
    """Split sparse analog dial artwork where it saves flash within the widget limit."""
    def bounds(box):
        x,y,_,_=box
        b=panel.crop(box).getbbox()
        if b:return (x+b[0],y+b[1],x+b[2],y+b[3])

    @lru_cache(maxsize=None)
    def cost(box):
        part=panel.crop(box)
        colors=sum(index!=BLACK for _,index in part.getcolors())
        bits=next(n for n in (1,2,4) if colors < 1<<n)
        return (part.width*bits+7)//8*part.height + (4<<bits) + 40

    @lru_cache(maxsize=None)
    def best(box):
        x,y,r,b=box
        options=[((x,y,p,b),(p,y,r,b)) for p in range(x+4,r-3,4)]
        options += [((x,y,r,p),(x,p,r,b)) for p in range(y+4,b-3,4)]
        gain,chosen=0,None
        for pair in options:
            pieces=tuple(piece for entry in pair if (piece:=bounds(entry)))
            saved=cost(box)-sum(cost(piece) for piece in pieces)
            if saved>gain:gain,chosen=saved,pieces
        return gain,chosen

    parts=[box for y in range(0,HEIGHT,24) if (box:=bounds((0,y,WIDTH,min(y+24,HEIGHT))))]
    if key=='purple_drift':
        while len(parts)<40:
            box=max(parts,key=lambda b:best(b)[0])
            gain,pieces=best(box)
            if gain<100:break
            parts.remove(box);parts.extend(pieces)
    return sorted(parts,key=lambda b:(b[1],b[0]))

def compile_theme(key):
    panel=canvas((WIDTH,HEIGHT));draw=ImageDraw.Draw(panel)
    face=dict(sprites={},bands=[],lamps=[],digits={},needles=[],hands=[])
    header(draw,face,VIOLET if key=='purple_drift' else LIME)
    {'strip_drift':strip,'led_segments':led,'purple_drift':purple}[key](draw,face)
    for i,box in enumerate(band_parts(panel,key)):
        name=f'band{i}';face['sprites'][name]=indexed(panel.crop(box))
        face['bands'].append(dict(sprite=name,x=box[0],y=box[1]))
    badge=canvas((24,12))
    label(ImageDraw.Draw(badge),(0,6),'USB',10,CYAN)
    face['sprites']['usb']=indexed(badge)
    glyphs(face,key)
    return face

if __name__=='__main__':
    faces={key:compile_theme(key) for key in ('strip_drift','led_segments','purple_drift')}
    payload=zlib.compress(json.dumps(faces,separators=(',',':')).encode('ascii'),9)
    data=base64.b85encode(payload).decode('ascii')
    output=Path(__file__).resolve().parents[1]/'dashboard_native_assets.py'
    output.write_text('# Generated by artwork/compile_native_faces.py\nimport base64, json, zlib\n'
                      'FACES = json.loads(zlib.decompress(base64.b85decode(\n'
                      +''.join(repr(data[i:i+100])+'\n' for i in range(0,len(data),100))+')))\n','ascii')

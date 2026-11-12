"""Reference-art faces for the native 215 x 270 home panel (layout schema 4).

Each image, glyph and overlay is stored in flash. Preview and firmware consume the
same indexed rows. Schema 3 stays separate for exact recognition of older radios.
"""
import base64
import math
import struct
import zlib
from functools import lru_cache

import dashboard_custom as c
import dashboard_six as six
import dashboard_themes as t
from dashboard_face_assets import FACES
from startup_animation import PLAYER_OFFSET

THEMES=t.THEMES
SAMPLE={0:75,1:0,2:-15,3:35,4:65}
CHARS='0123456789- %'
SIGNED_CHARS=CHARS+'+'

def face_bank(full,signed,native=False):
    if native:
        from dashboard_native_assets import FACES as faces
    elif signed:
        from dashboard_signed_assets import FACES as faces
    elif full:
        from dashboard_lcd_assets import FACES as faces
    else:faces=FACES
    return faces

def numeral(value,show_plus=False):
    return f'{value:+d}' if show_plus and value>0 else str(value)

def validate(spec):
    c._keys(spec,('schema','theme'),'artwork preset')
    c._integer(spec['schema'],4,4,'schema')
    c._require(type(spec['theme']) is str and spec['theme'] in THEMES,'Unknown artwork preset.')
    return {'schema':4,'theme':spec['theme']}

def layout(key):return validate({'schema':4,'theme':key})

@lru_cache(maxsize=512)
def asset(key,name,full=False,signed=False,native=False):
    faces=face_bank(full,signed,native)
    w,h,bits,packed=faces[key]['sprites'][name]
    blob=zlib.decompress(base64.b85decode(packed))
    c._require(bits in (1,2,4) and len(blob)==4*(1<<bits)+((w*bits+7)//8)*h,'Invalid indexed sprite.')
    return w,h,bits,blob

def center_edge(value):
    """Boundary between segments, 0..16. Either side starts at boundary 8."""
    count=(abs(value)*8+99)//100
    return 8-count if value<0 else 8+count

def needle_frame(value,centered):
    # The 101 frames have two percentage points of travel per step.
    return (value+100+int(centered and value>0))//2

def scene(key,full=False,signed=False,native=False,centered=False):
    faces=face_bank(full,signed,native)
    W,H=(240,320) if full else (215,270)
    face=faces[key];leaves=[]
    def img(name,x,y,**kwargs):
        w,h,_,_=asset(key,name,full,signed,native)
        leaves.append(dict(kind='img',sprite=name,box=(x,y,w,h),color='#ffffff',**kwargs))
    for part in face['bands']:img(part['sprite'],part['x'],part['y'])
    for index,part in enumerate(face['lamps']):
        if centered:
            img(part['sprite'],part['x'],part['y'],channel=part['channel'],role='segment',slot=index%16,hidden=True)
            continue
        threshold=-100+math.ceil((index%16+1)*200/16) if signed else part['threshold']
        img(part['sprite'],part['x'],part['y'],channel=part['channel'],role='segment',threshold=threshold,hidden=threshold>0)
    for ch in range(5):
        leaves.append(dict(kind='bar',box=tuple(face['battery']) if ch==0 else (0,0,1,1),channel=ch,
                           role='cache',color='#9bea28',hidden=bool(ch)))
    if native:
        leaves.append(dict(kind='bar',box=(0,0,1,1),channel=-1,role='usb_frames',color='#000000',hidden=True))
        img('usb',209,8,role='usb_source',hidden=True)
        for hand in face['hands']:
            name,dx,dy=hand['frames'][50]
            img(name,hand['cx']+dx,hand['cy']+dy,role='bitmap_needle',channel=hand['channel'],hand=hand)
            img(hand['hub'],hand['cx']-4,hand['cy']-4)
    for ch,geom in enumerate(face['needles'],3):
        leaves.append(dict(kind='line',box=(0,0,W,H),channel=ch,role='needle',geom=geom,
                           width=2,color='#fa69ff' if ch==3 else '#c1ff37',initial_index=50 if signed else 0))
        cx,cy,_,_=geom
        leaves.append(dict(kind='obj',box=(cx-2,cy-2,5,5),color='#824195' if ch==3 else '#738c26',radius=3))
    for ch in range(5):
        x,y,w,h,slots=face['digits'][str(ch)]
        for i,s in enumerate(str(0).rjust(slots)+'%'):
            img('d%d_%d'%(ch,CHARS.index(s)),x+i*w,y,channel=ch,role='digit' if i<slots else 'percent',col=i+4-slots)
    c._require(len(leaves)<=t.MAX_LEAVES and all(0<=x<x+w<=W and 0<=y<y+h<=H for x,y,w,h in (v['box'] for v in leaves)),'Artwork outside home panel.')
    return leaves

def points(geom,value):
    cx,cy,rx,ry=geom;angle=math.radians(140+260*value/100)
    return (cx,cy,round(cx+rx*math.cos(angle)),round(cy+ry*math.sin(angle)))

def checked_tree(a,leaves,failure,table):
    # Match *every* owner, class and count before using the child array. A single
    # loop keeps the asset budget for artwork. Preserve r5=panel, r6=root, r7=array.
    a.load_global(5,six.PANEL);c._not_null(a,5,failure)
    c._array(a,4,5,1,failure);a.ldr(6,4);c._typed(a,6,5,six.PANEL,failure)
    c._array(a,7,6,len(leaves),failure)
    a.imm(2,table);a.imm(3,len(leaves)*4);a.imm(4,0);a.mark('edges')
    a.emit(0x5938);c._not_null(a,0,failure)  # ldr r0,[r7,r4]
    a.ldr(1,0,4);a.cmp_reg(1,6);a.jump(failure,1)
    a.ldr(0,0);a.emit(0x5911);a.cmp_reg(0,1);a.jump(failure,1)  # ldr r1,[r2,r4]
    a.emit(0x3404);a.cmp_reg(4,3);a.jump('edges',1)

def update(addr,leaves,converter,tables,full=False,signed=False):
    a=t.Code(addr);a.emit(0xb5f8);six._home_guard(a,'return')
    if full:
        from dashboard_fullscreen import check_overlay
        check_overlay(a,leaves,'return',tables['classes'])
    else:checked_tree(a,leaves,'return',tables['classes'])
    for ch in range(5):
        group=[(n,v) for n,v in enumerate(leaves) if v.get('channel')==ch]
        cache=next(n for n,v in group if v['role']=='cache')
        t.leaf(a,4,cache);a.mov(0,4);a.call('bar_get_value');a.mov(6,0)
        if not ch:
            if 'usb_status' in tables:
                a.call(tables['usb_status']);a.cmp(0,0);a.jump('native_battery',0)
                a.imm(0,100);a.jump('power_read');a.mark('native_battery')
            a.load_global(0,0x200005cc);c._not_null(a,0,'return');a.call('arc_get_value')
            if 'usb_status' in tables:a.mark('power_read')
            # Keep subsequent digit indexing bounded even if the model returns a sentinel.
            a.cmp(0,100);a.jump('return',8)
        else:
            a.load_global(0,0x20000200+ch*4);a.call(tables['aux_convert'] if signed and ch>=3 else converter)
            if not signed and ch>=3:a.emit(0x3064,0x0840)  # Legacy unsigned scale.
        a.mov(5,0);a.cmp_reg(5,6);a.jump('next%d'%ch,0)
        a.mov(0,4);a.mov(1,5);a.imm(2,0);a.call('bar_value')
        for n,v in group:
            if v['role']=='digit':
                a.mov(0,5)
                if not (signed and ch==0):a.emit(0x3064)
                a.emit(0x0080)
                lookup=tables['battery_digits'] if signed and ch==0 else tables['numbers']
                a.imm(1,lookup+v['col']);a.emit(0x1808,0x7800,0x0080)
                a.imm(1,tables['font%d'%ch]);a.emit(0x1808);a.ldr(1,0)
                t.leaf(a,0,n);a.call(t.IMG_SRC)
            elif v['role']=='segment' and full:
                if n==next(i for i,item in group if item['role']=='segment'):
                    a.mov(0,7);a.emit(0x3000+n*4);a.mov(1,6);a.mov(2,5)
                    if signed:a.emit(0x3164,0x3264)  # Both lookup indices are now 0..200.
                    a.call(tables['lamps_fn'])
            elif v['role']=='segment':
                # Touch only LEDs whose threshold was crossed in this sample.
                end='done%d'%n;up='light%d'%n
                a.cmp(5,v['threshold']);a.jump(up,2)
                a.cmp(6,v['threshold']);a.jump(end,3)
                t.leaf(a,4,n);a.method('add_flag',1);a.jump(end)
                a.mark(up);a.cmp(6,v['threshold']);a.jump(end,2)
                t.leaf(a,4,n);a.method('clear_flag',1);a.mark(end)
            elif v['role']=='bitmap_needle':
                t.leaf(a,0,n);a.mov(1,5)
                a.emit(0x3164)
                if 'needle_frames' in tables:
                    a.imm(2,tables['needle_frames']);a.emit(0x5c51)  # ldrb r1,[r2,r1]
                else:a.emit(0x0849)
                a.emit(0x0109)  # 16 bytes per frame record
                a.imm(2,tables[n]);a.emit(0x1889);a.call(tables['set_needle'])
            elif v['role']=='needle':
                a.mov(0,5)
                if signed:a.emit(0x3064,0x0840)
                a.emit(0x00c1);a.imm(0,tables[n]);a.emit(0x1809)
                t.leaf(a,0,n);a.imm(2,2);a.call(t.LINE_POINTS)
        a.mark('next%d'%ch)
    a.mark('return');a.emit(0xbdf8);return a.finish()

def build_appendix(original,offset,spec,*,full=False):
    centered=spec.get('schema')==9
    native=spec.get('schema') in (8,9)
    signed=spec.get('schema') in (7,8,9)
    if full:
        import dashboard_fullscreen as lcd
        faces=face_bank(full,signed,native)
        key=lcd.validate(spec)['theme']
    else:key=validate(spec)['theme'];faces=FACES
    leaves=scene(key,full,signed,native,centered);code=bytearray();tables={};fn={}
    c._require(offset>=len(original) and offset%4==0,'Invalid artwork offset.')
    for site,signature in {**six.ORIGINAL_SITES,0x47900:bytes.fromhex('70b5044600bf00bf2146'),
            0x4881c:bytes.fromhex('2de9f04f85b005460f46'),0x4a778:bytes.fromhex('70b5044600bf00bf2146'),
            0x4a96c:bytes.fromhex('2de9f04104460e46')}.items():
        c._require(original[site:site+len(signature)]==signature,'Native UI signature differs.')
    def data(blob):
        code.extend(bytes(-len(code)%4));address=six.BASE+offset+len(code);code.extend(blob);return address
    images={}
    for name in faces[key]['sprites']:
        w,h,bits,blob=asset(key,name,full,signed,native)
        signature=(w,h,bits,blob)
        if signature not in images:
            ptr=data(blob);header={1:7,2:8,4:9}[bits]|(w<<10)|(h<<21)
            images[signature]=data(struct.pack('<III',header,len(blob),ptr))
        tables[name]=images[signature]
    for ch in range(5):
        count=14 if signed and ch else 13
        tables['font%d'%ch]=data(struct.pack('<%dI'%count,*(tables['d%d_%d'%(ch,i)] for i in range(count))))
    tables['numbers']=data(bytes(SIGNED_CHARS.index(s) for v in range(-100,101) for s in numeral(v,signed).rjust(4)))
    if signed:tables['battery_digits']=data(bytes(CHARS.index(s) for v in range(101) for s in str(v).rjust(4)))
    tables['classes']=data(struct.pack('<%dI'%len(leaves),*(t.CLASS[v['kind']] for v in leaves)))
    for n,v in enumerate(leaves):
        if v.get('role')=='bitmap_needle':
            hand=v['hand'];records=[]
            for name,dx,dy in hand['frames']:
                w,h=faces[key]['sprites'][name][:2]
                x,y=hand['cx']+dx,hand['cy']+dy
                c._require(0<=x<x+w<=240 and 0<=y<y+h<=320,'Needle outside LCD.')
                records.append(struct.pack('<I4H4x',tables[name],x,y,w,h))
            tables[n]=data(b''.join(records))
        if v.get('role')=='needle':tables[n]=data(b''.join(struct.pack('<4h',*points(v['geom'],i)) for i in range(101)))
    def append(name,builder,*args,**kwargs):
        address=data(b'');fn[name]=address;code.extend(builder(address,*args,**kwargs))
    if full:
        tables['records']=lcd.records(data,leaves,tables)
        if faces[key]['lamps']:
            if centered:
                levels=data(bytes(center_edge(v) for v in range(-100,101)))
                append('lamps',lcd.centered_lamps,levels)
            else:
                travel=200 if signed else 100
                levels=data(bytes(i*16//travel for i in range(travel+1)))
                append('lamps',lcd.lamps,levels)
            tables['lamps_fn']=fn['lamps']
        append('images',lcd.images)
    if native:
        cache=next(i for i,v in enumerate(leaves) if v.get('role')=='usb_frames')
        badge=next(i for i,v in enumerate(leaves) if v.get('role')=='usb_source')
        append('usb_status',lcd.usb_power_status,cache,badge);tables['usb_status']=fn['usb_status']
        if faces[key]['hands']:
            if centered:tables['needle_frames']=data(bytes(needle_frame(v,True) for v in range(-100,101)))
            append('set_needle',lcd.set_needle);tables['set_needle']=fn['set_needle']
    if signed:
        append('convert',lcd.channel_percent,*lcd.PRIMARY_STOPS)
        append('aux_convert',lcd.channel_percent,*lcd.AUX_STOPS);tables['aux_convert']=fn['aux_convert']
    else:append('convert',t.convert)
    append('update',update,leaves,fn['convert'],tables,full,signed)
    if full:append('layout',lcd.construct,leaves,tables,fn['update'],fn['images'])
    else:
        append('cleanup',six._cleanup)
        append('layout',t.construct,leaves,{},tables,fn['update'],fn['cleanup'],
               check_tree=lambda a,l,f:checked_tree(a,l,f,tables['classes']),background='#000000')
    append('constructor',six._constructor,fn['layout']);append('timer',six._timer,fn['update'])
    end=offset+len(code)+len(c.make_trailer(spec,True))
    c._require(end<PLAYER_OFFSET,f'Artwork overlaps startup media: {end} >= {PLAYER_OFFSET}.')
    repl={six.HOOK_CONSTRUCTOR:six._branch(six.BASE+six.HOOK_CONSTRUCTOR,fn['constructor'],True),
          six.HOOK_TIMER:struct.pack('<I',fn['timer']|1)}
    return bytes(code),repl,{'layout':spec,'code_bytes':len(code),'new_owned_widgets':1+len(leaves)}

@lru_cache(maxsize=512)
def bitmap(key,name,full=False,signed=False,native=False):
    from PIL import Image
    w,h,bits,blob=asset(key,name,full,signed,native);n=1<<bits;stride=(w*bits+7)//8
    pal=[(r,g,b,a) for b,g,r,a in struct.iter_unpack('4B',blob[:4*n])]
    raw=blob[4*n:];out=Image.new('RGBA',(w,h))
    out.putdata([pal[(raw[y*stride+x*bits//8]>>(8-bits-x*bits%8))&(n-1)] for y in range(h) for x in range(w)])
    return out

def render(key,values=None,full=False,signed=False,native=False,usb_active=False,centered=False):
    """Draw the same indexed sprites, in the same positions, as the radio."""
    from PIL import Image,ImageDraw
    val={**SAMPLE,**(values or {})};im=Image.new('RGBA',(240,320) if full else (215,270),'black');draw=ImageDraw.Draw(im)
    if native and usb_active:val[0]=100
    for item in scene(key,full,signed,native,centered):
        x,y,w,h=item['box'];role=item.get('role');ch=item.get('channel')
        if item['kind']=='img':
            name=item['sprite']
            if role=='usb_source' and not usb_active:continue
            if role=='bitmap_needle':
                hand=item['hand'];name,dx,dy=hand['frames'][needle_frame(val[ch],centered)]
                x,y=hand['cx']+dx,hand['cy']+dy
            if role=='segment':
                if centered:
                    edge=center_edge(val[ch])
                    if not min(8,edge)<=item['slot']<max(8,edge):continue
                elif val[ch]<item['threshold']:continue
            if role=='digit':
                s=numeral(val[ch],signed and ch!=0).rjust(4)[item['col']];name='d%d_%d'%(ch,SIGNED_CHARS.index(s))
            im.alpha_composite(bitmap(key,name,full,signed,native),(x,y))
        elif role=='cache' and ch==0:
            draw.rectangle((x,y,x+w-1,y+h-1),fill=t.TRACK)
            fill=w*val[ch]//100
            if fill:draw.rectangle((x,y,x+fill-1,y+h-1),fill=item['color'])
        elif role=='needle':draw.line(points(item['geom'],(val[ch]+100)//2 if signed else val[ch]),fill=item['color'],width=item['width'])
        elif item['kind']=='obj':draw.rounded_rectangle((x,y,x+w-1,y+h-1),radius=item['radius'],fill=item['color'])
    return im.convert('RGB')

def paint(canvas,key,values=None,full=False,signed=False,native=False,usb_active=False,centered=False):
    from PIL import Image,ImageTk
    w,h=max(1,canvas.winfo_width()),max(1,canvas.winfo_height());W,H=(240,320) if full else (215,270);scale=min(w/W,h/H)
    size=(max(1,round(W*scale)),max(1,round(H*scale)))
    img=render(key,values,full,signed,native,usb_active,centered).resize(size,Image.Resampling.NEAREST if native or scale>=1 else Image.Resampling.LANCZOS)
    canvas._face_photo=ImageTk.PhotoImage(img,master=canvas)
    canvas.delete('all');canvas.create_image(w/2,h/2,image=canvas._face_photo)


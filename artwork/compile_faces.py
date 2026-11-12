"""Compile user-supplied reference artwork into bounded native indexed sprites.
Usage: python artwork/compile_faces.py Strip.png LED.png Purple.png output.py
The source photographs, fonts and vendor firmware are not packaged by this script.
"""
import base64, hashlib, io, json, math, struct, sys, zlib
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont, ImageFilter, ImageChops
W,H=215,270
S=(1086,1448)
K=('strip_drift','led_segments','purple_drift')
FONT='arialbi.ttf'

def tx(x):return round(x*W/S[0])
def ty(y):return round(y*H/S[1])
def crop_bands(face):
    """Split sparse bands only where black LCD pixels can replace stored black.
    Preserve every visible pixel and its existing palette, including soft edges.
    """
    def read(name):
        w,h,bits,blob=face['sprites'][name];data=zlib.decompress(base64.b85decode(blob))
        pal=data[:64];pixels=data[64:];im=Image.new('L',(w,h))
        im.putdata([(pixels[y*((w+1)//2)+x//2]>>(4 if x%2==0 else 0))&15 for y in range(h) for x in range(w)])
        lut=[255 if max(pal[i:i+3]) and pal[i+3] else 0 for i in range(0,64,4)]+[0]*240
        return im,im.point(lut),pal
    def cost(rect):
        x,y,r,b=rect;return 100+(r-x+1)//2*(b-y)
    def best(node):
        im,mask,pal=read(node['sprite']);w,h=im.size;best_gain=0;best_boxes=None
        for axis,length in enumerate((w,h)):
            for n in range(2,length-1,2):
                halves=((0,0,n,h),(n,0,w,h)) if not axis else ((0,0,w,n),(0,n,w,h))
                boxes=[]
                for x,y,r,b in halves:
                    bb=mask.crop((x,y,r,b)).getbbox()
                    if bb:boxes.append((x+bb[0],y+bb[1],x+bb[2],y+bb[3]))
                gain=cost((0,0,w,h))-sum(map(cost,boxes))
                if gain>best_gain:best_boxes=boxes;best_gain=gain
        return best_gain,best_boxes
    candidates={node['sprite']:best(node) for node in face['bands']}
    max_bands=len(face['bands'])+6
    while candidates and len(face['bands'])<max_bands:
        name=max(candidates,key=lambda k:candidates[k][0])
        gain,boxes=candidates.pop(name)
        if gain<16:break
        node=next(n for n in face['bands'] if n['sprite']==name)
        im,mask,pal=read(name);face['bands'].remove(node);del face['sprites'][name]
        for i,(x,y,r,b) in enumerate(boxes):
            part=im.crop((x,y,r,b));w,h=part.size;uniq=name+'_'+str(i);raw=bytearray(pal)
            for yy in range(h):
                for xx in range(0,w,2):raw.append(part.getpixel((xx,yy))*16+(part.getpixel((xx+1,yy)) if xx+1<w else 0))
            face['sprites'][uniq]=[w,h,4,base64.b85encode(zlib.compress(raw,9)).decode()]
            d=dict(sprite=uniq,x=node['x']+x,y=node['y']+y);face['bands'].append(d);candidates[uniq]=best(d)
    return face
def erase(im,box):
    x,y,x2,y2=box
    left=im.crop((x-2,y,x,y2)).resize((x2-x,y2-y))
    right=im.crop((x2,y,x2+2,y2)).resize(left.size)
    mask=Image.linear_gradient('L').rotate(90).resize(left.size)
    im.paste(Image.composite(right,left,mask),(x,y))

def quant(im,bits,ink=None):
    im=im.convert('RGBA');colors=2**bits
    rgb=im.convert('RGB')
    # The dark background occupies most pixels. Give thin chrome, white text
    # and saturated neon their own palette entries instead of 12 near-blacks.
    hist={}
    for r,g,b in rgb.getdata():
        k=(r>>4,g>>4,b>>4)
        hist[k]=hist.get(k,0)+1
    samples=[tuple(min(255,16*v+(0 if k==(0,0,0) else 7)) for v in k) for k,n in hist.items() for _ in range(1+int(n**.45))]
    sample=Image.new('RGB',(len(samples),1));sample.putdata(samples)
    p=sample.quantize(colors=colors-1,kmeans=2);pal=p.getpalette()[:3*(colors-1)]
    pal+=([0]*(3*(colors-1)-len(pal)))
    if not ink:
        darkest=min(range(colors-1),key=lambda i:sum(pal[3*i:3*i+3]))
        pal[darkest*3:darkest*3+3]=[0,0,0]
    # Duplicate a real color in the padding so Pillow cannot pick an invalid index.
    p.putpalette(pal+pal[:3]*(256-(colors-1)))
    q=rgb.quantize(palette=p,dither=Image.Dither.NONE)
    palette=bytes(4)+b''.join(bytes((b,g,r,255)) for r,g,b in zip(pal[::3],pal[1::3],pal[2::3]))
    w,h=q.size;raw=bytearray()
    idx=q.tobytes();alpha=im.getchannel('A').tobytes()
    if ink:
        r,g,b=ink;palette=b''.join(bytes((b,g,r,a)) for a in (0,85,170,255))
    for y in range(h):
        acc=n=0
        for x in range(w):
            i=y*w+x;v=(idx[i]+1 if idx[i]<colors-1 else 1) if alpha[i]>=128 else 0
            if ink:v=(alpha[i]+42)//85
            acc=(acc<<bits)|v;n+=bits
            if n==8:raw.append(acc);acc=n=0
        if n:raw.append(acc<<(8-n))
    return [w,h,bits,base64.b85encode(zlib.compress(palette+raw,9)).decode('ascii')]

def lamp_sprite(mask,glow):
    # Four native RGBA palette entries: clear, luminous halo, face and bevel.
    edge=mask.resize((W,H),Image.Resampling.LANCZOS)
    soft=edge.filter(ImageFilter.GaussianBlur(1.15))
    bbox=soft.point(lambda p:255 if p>12 else 0).getbbox()
    core=edge.crop(bbox);halo=soft.crop(bbox);w,h=core.size
    palette=bytearray(4)
    for rgb,a in ((glow,60),(glow,255),(tuple(round(v*.59+104) for v in glow),255)):
        r,g,b=rgb;palette.extend((b,g,r,a))
    for y in range(h):
        row=0
        for x in range(w):
            edge=core.getpixel((x,y));blur=halo.getpixel((x,y))
            v=3 if edge>168 and ((y<h*.30 and blur<225) or x==1) else 2 if edge>=115 else 1 if blur>16 else 0
            row=(row<<2)|v
            if x%4==3:palette.append(row);row=0
        if w%4:palette.append(row<<(8-2*(w%4)))
    return bbox,[w,h,2,base64.b85encode(zlib.compress(bytes(palette),9)).decode()]

def signed_graduations(im,key):
    """Replace the unsigned legends baked into the source design, before rasterization.
    Locations are in the 430x540 reference proof. Preserve the dial face around the ink.
    """
    sx,sy=S[0]/430,S[1]/540
    if key==K[0]:
        scales=[[(x,y) for x in (32,66,102,138,175,211,246,280,315,349,381)] for y in (278,425)]
    elif key==K[1]:
        scales=[[(116,244+d),(89,120+d),(215,52+d),(342,120+d),(315,244+d)] for d in (0,214)]
    else:
        scales=[[(69,266),(57,226),(59,186),(77,149),(110,124),(157,110),(203,126),(231,156),(244,191),(243,230),(229,266)],
                [(228,436),(228,401),(231,369),(246,340),(271,320),(313,307),(351,320),(373,346),(382,373),(381,405),(373,434)]]
    for scale in scales:
        for i,(cx,cy) in enumerate(scale):
            rx,ry=(15,5.8) if key==K[0] else (20,7) if key==K[1] else (17,6.6)
            x,y,r,b=round((cx-rx)*sx),round((cy-ry)*sy),round((cx+rx)*sx),round((cy+ry)*sy)
            old=im.crop((x,y,r,b));w,h=old.size
            ink=Image.new('L',(w,h));ink.putdata([255 if min(rgb)>50 and max(rgb)-min(rgb)<90 else 0 for rgb in old.getdata()])
            ink=ink.filter(ImageFilter.MaxFilter(5))
            above=im.crop((x,y-2,r,y-1)).resize((w,h));below=im.crop((x,b+1,r,b+2)).resize((w,h))
            im.paste(Image.composite(below,above,Image.linear_gradient('L').resize((w,h))),(x,y),ink)
            val=-100+200*i//(len(scale)-1)
            # Use the original tick marks. Leave alternate minor ticks unlabelled on compact scales.
            if len(scale)==11 and i not in (0,2,5,8,10):continue
            label='0' if val==0 else f'{val:+d}'
            font=ImageFont.truetype(FONT,27 if key==K[2] else 31)
            ImageDraw.Draw(im).text((round(cx*sx),round(cy*sy)),label,anchor='mm',font=font,fill='#eaf1ef')

def compile_one(key,path,signed=False):
    im=Image.open(path).convert('RGB')
    if im.size!=S:raise ValueError('Expected the full 1086 × 1448 reference')
    original=im.copy();sprites={};nodes=[];lamps=[]
    purple=key==K[2];strip=key==K[0]
    # Static pieces of the photo are preserved; all example telemetry is removed.
    if strip:
        fields=[(0,(849,137,1016,186)),(1,(349,297,468,352)),(2,(800,298,960,352)),
                (3,(803,525,1019,609)),(4,(803,915,1019,999))]
        model=(521,140,781,184)
    elif not purple:
        fields=[(0,(877,46,1017,86)),(1,(153,137,244,178)),(2,(138,205,245,246)),
                (3,(361,410,724,536)),(4,(361,979,725,1111))]
        model=(521,35,788,83)
    else:
        fields=[(0,(911,78,1042,135)),(1,(917,246,1043,310)),(2,(882,343,1045,410)),
                (3,(222,646,532,748)),(4,(612,1103,908,1190))]
        model=(467,83,677,127)
        # Repair the two narrow needle paths from the same dial face on either
        # side; preserve the original scale and metallic rim outside the path.
        for cx,cy,x1,y1,hub in ((371,567,183,297,25),(767,1045,894,855,21)):
            px=original.load();out=im.load();dx=x1-cx;dy=y1-cy;l=math.hypot(dx,dy);nx=-dy/l;ny=dx/l
            for y in range(int(min(cy,y1)-25),int(max(cy,y1)+25)):
                for x in range(int(min(cx,x1)-25),int(max(cx,x1)+25)):
                    q=(x-cx)*dx/l+(y-cy)*dy/l;d=(x-cx)*nx+(y-cy)*ny
                    if hub-5<q<l+8 and abs(d)<20:
                        a=px[round(x+(21-d)*nx),round(y+(21-d)*ny)];b=px[round(x-(21+d)*nx),round(y-(21+d)*ny)]
                        out[x,y]=tuple(round((aa*(d+21)+bb*(21-d))/42) for aa,bb in zip(a,b))
    for ch,box in fields:
        if ch>=3 and not strip:
            x,y,xx,yy=box
            upper=im.crop((x,y-2,xx,y-1)).resize((xx-x,yy-y))
            lower=im.crop((x,yy+1,xx,yy+2)).resize(upper.size)
            im.paste(Image.composite(lower,upper,Image.linear_gradient('L').resize(upper.size)),(x,y))
        else:erase(im,box)
    erase(im,model)
    ImageDraw.Draw(im).text((model[0],model[1]),{'strip_drift':'STRIP / 09','led_segments':'LED / 08','purple_drift':'PURPLE / 04'}[key],
        font=ImageFont.truetype(FONT,34),fill='#d9e2e5',anchor='lt',stroke_width=0)
    # Native model name lives in the existing header above the artwork.
    if purple:
        ImageDraw.Draw(im).rectangle((788,92,875,121),fill='#141b0e')
    else:
        x,y,xx,yy=fields[0][1];ImageDraw.Draw(im).rectangle((x,y,xx-1,yy-1),fill='#141b0e')
    if not purple:
        for ch in (3,4):
            lime=ch==3;cy=449 if lime else 1023;cx=533
            base=(178,255,0) if lime else (0,235,255)
            if strip:
                y=634 if lime else 1027
                ImageDraw.Draw(im).polygon([(68,y+57),(98,y),(997,y),(970,y+57)],fill='#080b0d')
            else:
                pix=im.load()
                for yy in range(cy-295,cy+215):
                    for xx in range(cx-295,cx+296):
                        r=math.hypot(xx-cx,yy-cy)
                        if 180<r<300:
                            rgb=pix[xx,yy]
                            if max(rgb)-min(rgb)>10:pix[xx,yy]=tuple(v//12 for v in rgb)
            for n in range(16):
                if strip:
                    x=100+56*n
                    poly=[(x,y+2),(x+51,y+2),(x+25,y+55),(x-26,y+55)]
                else:
                    start=135+n*270/16+1.1;end=135+(n+1)*270/16-1.1
                    def pt(r,a):return (cx+r*math.cos(math.radians(a)),cy+r*math.sin(math.radians(a)))
                    poly=[pt(r,start+(end-start)*j/8) for r,indices in ((262,range(9)),(208,reversed(range(9)))) for j in indices]
                glow=(255,155,1) if n>=14 and (strip or lime) else (38,105,255) if n>=14 and not lime else base
                tint=.57 if n>=14 else .18
                d=ImageDraw.Draw(im);d.polygon(poly,fill=tuple(round(v*tint)+5 for v in glow),outline=tuple(round(v*(tint+.12))+11 for v in glow),width=3)
                mask=Image.new('L',S);ImageDraw.Draw(mask).polygon(poly,fill=255)
                name=f's{ch}_{n}';bbox,sprites[name]=lamp_sprite(mask,glow)
                lamps.append(dict(sprite=name,x=bbox[0],y=bbox[1],channel=ch,threshold=math.ceil((n+1)*100/16)))
    if signed:signed_graduations(im,key)
    panel=im.resize((W,H),Image.Resampling.LANCZOS)
    # Separate palettes by horizontal band: more shades on the LCD without
    # allocating a full-screen framebuffer. 2 bits suffice for quiet bands.
    for n,y in enumerate(range(0,H,24)):
        band=panel.crop((0,y,W,min(y+24,H)))
        bbox=band.convert('L').point(lambda p:255 if p>=12 else 0).getbbox()
        if not bbox:continue
        band=band.crop(bbox);name='b'+str(n)
        sprites[name]=quant(band,4)
        nodes.append(dict(sprite=name,x=bbox[0],y=y+bbox[1]))
    digits={}
    for ch,(x,y,xx,yy) in fields:
        x0,x2,y0,y2=tx(x),tx(xx),ty(y),ty(yy)
        # Signed CH1/2 need enough space for -100%. The photograph's tiny
        # numbers are widened into adjoining blank area at native resolution.
        slots=4 if ch in (1,2) or (signed and ch) else 3
        size= max(8,y2-y0) if ch<3 else min(21,y2-y0+1)
        cw=max(4,min((x2-x0)//(slots+1),round(size*.66)))
        if ch in (1,2):cw=max(cw,5)
        if ch>=3:cw=max(cw,round((x2-x0)/3.35))
        if signed and ch>=3:cw=max(5,(x2-x0)//5)
        color=(255,255,255) if strip or (purple and ch in (0,1,2)) else (204,255,6) if ch!=4 else (0,240,255)
        if purple and ch>=3:color=(247,232,255) if ch==3 else (233,255,196)
        if ch==0:color=(235,255,206)
        for i,s in enumerate('0123456789- %'+('+' if signed and ch else '')):
            glyph=Image.new('RGBA',(cw*4,size*4))
            if s!=' ':
                font=ImageFont.truetype(FONT,size*5)
                bb=font.getbbox(s);gh=Image.new('L',(bb[2]-bb[0]+2,bb[3]-bb[1]+2))
                ImageDraw.Draw(gh).text((1-bb[0],1-bb[1]),s,font=font,fill=255)
                h=round(size*4*(.17 if s=='-' else .53 if s=='+' else .93));w=max(2,cw*4-2)
                gh=gh.resize((w,h),Image.Resampling.LANCZOS)
                fg=Image.new('RGBA',(w,h));fd=ImageDraw.Draw(fg)
                for row in range(h):
                    strength=1-.23*row/max(h-1,1)
                    fd.line((0,row,w,row),fill=tuple(round(v*strength) for v in color)+(255,))
                fg.putalpha(gh);glyph.alpha_composite(fg,(1,(size*4-h)//2))
            sprites[f'd{ch}_{i}']=quant(glyph.resize((cw,size),Image.Resampling.LANCZOS),2,ink=color)
        digits[str(ch)]=[max(0,min(W-(slots+1)*cw,x2-(slots+1)*cw)),y0,cw,size,slots]
    return dict(sprites=sprites,bands=nodes,lamps=lamps,digits=digits,
        battery=([tx(789),ty(93),tx(86),ty(29)] if purple else [tx(fields[0][1][0]),ty(fields[0][1][3])+1,tx(135),2]),
        needles=([[tx(371),ty(567),tx(320),ty(320)],[tx(767),ty(1045),tx(225),ty(225)]] if purple else []))

if __name__=='__main__':
    signed='--signed' in sys.argv
    if signed:sys.argv.remove('--signed')
    if '--fullscreen' in sys.argv:
        sys.argv.remove('--fullscreen')
        W,H=240,320
    if len(sys.argv)!=5:raise SystemExit(__doc__)
    if signed and (W,H)!=(240,320):raise ValueError('Signed artwork requires --fullscreen.')
    data={k:compile_one(k,p,signed) for k,p in zip(K,sys.argv[1:4])}
    if (W,H)==(240,320):
        crop_bands(data['purple_drift'])
    raw=json.dumps(data,separators=(',',':')).encode()
    packed=base64.b85encode(zlib.compress(raw,9)).decode()
    Path(sys.argv[4]).write_text('# Generated indexed artwork; no input image files needed at runtime.\nimport json,base64,zlib\nFACES=json.loads(zlib.decompress(base64.b85decode(\n'+''.join(repr(packed[i:i+100])+'\n' for i in range(0,len(packed),100))+')))\n',encoding='ascii')


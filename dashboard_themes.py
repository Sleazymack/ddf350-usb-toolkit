"""Three bounded native drift themes and their shared desktop preview geometry.

Only our home constructor/timer hooks are used. No bitmap covers live values.
Native menus and model access remain alive. Original images are references only.
"""
import math
import struct

import dashboard_custom as c
import dashboard_six as six
from dashboard_zones import UPPER_NATIVE

THEMES=('strip_drift','led_segments','purple_drift')
NAMES={'strip_drift':'Strip Drift','led_segments':'LED Segments','purple_drift':'Purple Drift'}
BACKGROUND='#030609'
WHITE='#e8f1f5'
TRACK='#20282b'
CLASS={'obj':six.BASE+0x96558,'bar':six.BASE+0x96d68,'arc':six.BASE+0x96d4c,
       'label':six.BASE+0x96e48,'line':six.BASE+0x96e64}
LINE_CREATE=six.BASE+0x4a778
LINE_POINTS=six.BASE+0x4a96c
MAX_LEAVES=80
IMG_CREATE=six.BASE+0x47900
IMG_SRC=six.BASE+0x4881c
CLASS['img']=six.BASE+0x96e2c


def validate(layout):
    c._keys(layout,('schema','theme'),'drift theme')
    c._integer(layout['schema'],3,3,'schema')
    c._require(type(layout['theme']) is str and layout['theme'] in THEMES,'Unknown drift theme.')
    return {'schema':3,'theme':layout['theme']}


def layout(key):return validate({'schema':3,'theme':key})


def point(cx,cy,r,angle):
    angle=math.radians(angle)
    return round(cx+r*math.cos(angle)),round(cy+r*math.sin(angle))


def scene(key):
    """Flat, bounded native leaves; every coordinate is panel-local (215x270)."""
    c._require(key in THEMES,'Unknown drift theme.')
    leaves=[]
    accent='#bdff10' if key!='purple_drift' else '#bc30f4'
    def add(kind,box,color=WHITE,**other):
        item=dict(kind=kind,box=box,color=color,**other);leaves.append(item);return len(leaves)-1
    def text(value,box,color=WHITE,**other):return add('label',box,color,text=value,**other)
    text('DRIFT',(4,0,90,18),accent)
    add('bar',(138,3,26,12),'#8bec24',channel=0,role='cache')
    text('0%',(168,0,45,16),WHITE,channel=0,role='value')
    add('obj',(4,19,205,1),accent)
    for channel,x in ((1,4),(2,113)):
        text(f'CH{channel}',(x,25,34,16))
        text('0%',(x+34,25,60,16),accent,channel=channel,role='value')
        add('bar',(0,0,1,1),accent,channel=channel,role='cache',hidden=True)
    for channel,color in ((3,'#bc30f4' if key=='purple_drift' else '#bdff10'),
                          (4,'#8bec24' if key=='purple_drift' else '#00dcea')):
        add('bar',(0,0,1,1),color,channel=channel,role='cache',hidden=True)
        if key=='strip_drift':
            y=65 if channel==3 else 161
            add('obj',(3,y,209,70),BACKGROUND,border=color)
            text(f'CH{channel}',(10,y+5,55,16),color)
            text('0%',(150,y+5,54,16),WHITE,channel=channel,role='value')
            for n in range(12):
                add('obj',(10+n*16,y+30,13,18),color if n<10 else '#ff9d00',
                    channel=channel,role='segment',threshold=-100+math.ceil((n+1)*200/12))
            text('-100',(10,y+51,45,16))
            text('0',(99,y+51,30,16))
            text('+100',(160,y+51,47,16))
        elif key=='led_segments':
            x,y,size=59,(48 if channel==3 else 159),104
            for n in range(12):
                add('arc',(x,y,size,size),color if n<10 or channel==4 else '#ff9d00',
                    angles=((135+round(n*270/12))%360,(135+round((n+1)*270/12)-4)%360),
                    width=10,channel=channel,role='segment',threshold=-100+math.ceil((n+1)*200/12))
            text(f'CH{channel}',(83,y+31,56,16),WHITE)
            text('0%',(81,y+52,62,16),color,channel=channel,role='value')
        else:
            cx,cy,r=(77,110,68) if channel==3 else (148,208,57)
            add('arc',(cx-r,cy-r,r*2,r*2),color,angles=(135,45),width=4)
            for n in range(11):
                angle=135+n*27
                a=point(cx,cy,r-7,angle);b=point(cx,cy,r-12,angle)
                add('line',(0,0,215,270),color,points=(*a,*b),width=1)
            add('line',(0,0,215,270),color,channel=channel,role='needle',
                center=(cx,cy),radius=r-16,width=2)
            add('obj',(cx-3,cy-3,7,7),color,radius=4)
            text(f'CH{channel}',(cx-27,cy-25,56,16),WHITE)
            text('0%',(cx-29,cy+17,62,16),color,channel=channel,role='value')
    c._require(len(leaves)<=MAX_LEAVES,'Theme object limit exceeded.')
    for item in leaves:
        x,y,w,h=item['box']
        c._require(min(x,y)>=0 and w>0 and h>0 and x+w<=215 and y+h<=270,'Theme exceeds home panel.')
    return leaves


class Code(c._Code):
    pass


def leaf(a,dest,index):
    c._require(0<=index<MAX_LEAVES,'Theme leaf outside bound.')
    a.emit(0xf8d7,(dest<<12)|(index*4)) # LDR.W from the validated child array.


def tree(a,leaves,failure):
    a.load_global(5,six.PANEL);c._not_null(a,5,failure)
    c._array(a,4,5,1,failure);a.ldr(6,4)
    c._typed(a,6,5,six.PANEL,failure)
    c._array(a,7,6,len(leaves),failure)
    for index,item in enumerate(leaves):
        leaf(a,0,index);c._not_null(a,0,failure)
        a.ldr(1,0,4);a.cmp_reg(1,6);a.jump(failure,1)
        a.ldr(1,0);a.imm(2,CLASS[item['kind']]);a.cmp_reg(1,2);a.jump(failure,1)


def convert(address):
    # Same saturation and symmetric rounding as the existing helper, on +/-100.
    code=bytearray(six._convert(address))
    # Instructions have MULS between the immediate multiplier and rounding.
    before=bytes.fromhex('0321484319303221')
    after=bytes.fromhex('012148430a301421')
    c._require(code.count(before)==1,'Unexpected signed percentage helper.')
    return bytes(code.replace(before,after))


def update(address,leaves,converter,strings,tables):
    a=Code(address);a.emit(0xb5f8)
    six._home_guard(a,'return');tree(a,leaves,'return')
    for channel in range(5):
        cache=next(n for n,v in enumerate(leaves) if v.get('channel')==channel and v.get('role')=='cache')
        value=next(n for n,v in enumerate(leaves) if v.get('channel')==channel and v.get('role')=='value')
        leaf(a,4,cache);a.mov(0,4);a.call('bar_get_value');a.mov(6,0)
        if channel==0:
            a.load_global(0,0x200005cc);c._not_null(a,0,'return');a.call('arc_get_value')
        else:a.load_global(0,0x20000200+channel*4);a.call(converter)
        a.mov(5,0);a.cmp_reg(5,6);a.jump(f'next{channel}',0)
        a.mov(0,4);a.mov(1,5);a.imm(2,0);a.call('bar_value')
        leaf(a,0,value);a.imm(1,strings['percent']);a.mov(2,5);a.call('label_fmt')
        for n,item in enumerate(leaves):
            if item.get('channel')!=channel:continue
            if item.get('role')=='segment':
                a.imm(6,c.native_color(TRACK));a.imm(0,item['threshold']);a.cmp_reg(5,0)
                a.jump(f'inactive{n}',11) # signed < threshold
                a.imm(6,c.native_color(item['color']));a.mark(f'inactive{n}')
                leaf(a,4,n)
                if item['kind']=='arc':
                    a.mov(0,4);a.imm(1,0x52);a.mov(2,6);a.imm(3,0);a.call('style')
                else:a.mov(0,4);a.mov(1,6);a.imm(2,0);a.call('bg_color')
            elif item.get('role')=='needle':
                leaf(a,4,n);a.mov(0,5);a.emit(0x3064,0x00c1) # +100; LSL r1,r0,3.
                a.imm(0,tables[n]);a.emit(0x1809) # ADD r1,r1,r0.
                a.mov(0,4);a.imm(2,2);a.call(LINE_POINTS)
        a.mark(f'next{channel}')
    a.mark('return');a.emit(0xbdf8);return a.finish()


def construct(address,leaves,strings,tables,updater,cleanup,*,check_tree=tree,background=BACKGROUND):
    a=Code(address);a.emit(0xb5f8);six._home_guard(a,'return')
    a.load_global(5,six.PANEL);c._not_null(a,5,'return')
    a.ldr(0,5,8);a.cmp(0,0);a.jump('create',0)
    a.ldr(0,0,4);a.cmp(0,0);a.jump('return',1)
    a.mark('create');a.mov(0,5);a.call('obj_create');a.mov(4,0);c._not_null(a,4,'failed')
    a.method('add_flag',1);a.method('remove_style_all');a.method('clear_flag',c.NONINTERACTIVE_CLIPPED)
    a.box(0,0,215,270);a.mov(6,4)
    for n,item in enumerate(leaves):
        a.mov(0,6);a.call({'line':LINE_CREATE,'img':IMG_CREATE}.get(item['kind'],item['kind']+'_create'))
        a.mov(4,0);c._not_null(a,4,'failed')
        a.method('clear_flag',c.NONINTERACTIVE_CLIPPED)
        a.method('remove_style_all');a.box(*item['box'])
        color=c.native_color(item['color'])
        if item['kind']=='img':
            a.method(IMG_SRC,tables[item['sprite']])
        elif item['kind']=='label':
            a.method('font',six.FONT,0);a.method('text_color',color,0)
            a.method('text_align',0,0);a.method('label',strings['text'+str(n)])
        elif item['kind']=='line':
            a.method('style',0x849,item['width'],0)
            a.method('style',0x4d,color,0);a.method('style',0x4e,255,0)
            a.method('style',0x4c,1,0)
            a.method(LINE_POINTS,tables[n]+(item.get('initial_index',100)*8 if item.get('role')=='needle' else 0),2)
        elif item['kind']=='arc':
            a.method('remove_style',0,0x30000)
            active=item.get('threshold',-101)<=0
            for prop,value in ((0x850,item['width']),(0x51,0),(0x52,color if active else c.native_color(TRACK)),(0x53,255)):
                a.method('style',prop,value,0)
            a.method('style',0x53,0,0x20000) # Only the fixed segment/background arc is drawn.
            a.method('arc_bg_angles',*item['angles']);a.method('arc_range',-100,100);a.method('arc_value',0)
        elif item['kind']=='bar':
            for part,foreground in ((0,c.native_color(TRACK)),(0x20000,color)):
                a.method('bg_color',foreground,part);a.method('style',0x21,255,part)
            a.method('bar_mode',0);a.method('bar_range',0 if item['channel']==0 else -100,100)
            a.method('bar_value',0,0)
        else:
            active=item.get('threshold',-101)<=0
            a.method('bg_color',color if active else c.native_color(TRACK),0);a.method('style',0x21,255,0)
            if 'border' in item:
                for prop,value in ((0x1032,1),(0x30,c.native_color(item['border'])),(0x31,255)):
                    a.method('style',prop,value,0)
            a.method('radius',item.get('radius',0),0)
        if item.get('hidden'):a.method('add_flag',1)
    check_tree(a,leaves,'failed')
    for pointer in (*c.NATIVE_ROWS,*UPPER_NATIVE):
        a.load_global(0,pointer);c._not_null(a,0,'failed')
    a.mov(4,5);a.box(20,30,215,270);a.method('bg_color',c.native_color(background),0)
    a.method('style',0x21,255,0);a.method('clear_flag',c.NONINTERACTIVE_CLIPPED)
    for prop in (0x1010,0x1011,0x1012,0x1013):a.method('style',prop,0,0)
    for pointer in (*c.NATIVE_ROWS,*UPPER_NATIVE):
        a.load_global(4,pointer);a.method('add_flag',1)
    a.mov(4,6);a.method('clear_flag',1);a.call(updater);a.jump('return')
    a.mark('failed');a.mov(0,5);a.call(cleanup)
    a.mark('return');a.emit(0xbdf8);return a.finish()


def build_appendix(original,offset,spec):
    spec=validate(spec);leaves=scene(spec['theme'])
    c._require(offset>=len(original) and offset%4==0,'Invalid theme appendix offset.')
    for site,signature in six.ORIGINAL_SITES.items():c._require(original[site:site+len(signature)]==signature,'Theme home hook differs.')
    # Additional native line ABI is used only by Purple Drift and pinned to the
    # exact stock input. No copied native implementation is added to our output.
    for site,signature in ((0x4a778,bytes.fromhex('70b5044600bf00bf2146')),
                           (0x4a96c,bytes.fromhex('2de9f04104460e46'))):
        c._require(original[site:site+len(signature)]==signature,'Native line ABI signature differs.')
    code=bytearray();strings={};tables={};functions={}
    def data(blob):
        address=six.BASE+offset+len(code);code.extend(blob);return address
    strings['percent']=data(b'%d%%\0')
    for n,item in enumerate(leaves):
        if item['kind']=='label':strings['text'+str(n)]=data(item['text'].encode('ascii')+b'\0')
    while len(code)%4:code.append(0)
    for n,item in enumerate(leaves):
        if item['kind']!='line':continue
        if item.get('role')=='needle':
            cx,cy=item['center'];r=item['radius']
            points=[(cx,cy,*point(cx,cy,r,135+(value+100)*270/200)) for value in range(-100,101)]
        else:points=[item['points']]
        tables[n]=data(b''.join(struct.pack('<4h',*p) for p in points))
    def append(name,builder,*args):
        functions[name]=six.BASE+offset+len(code);code.extend(builder(functions[name],*args))
    append('convert',convert)
    append('update',update,leaves,functions['convert'],strings,tables)
    append('cleanup',six._cleanup)
    append('layout',construct,leaves,strings,tables,functions['update'],functions['cleanup'])
    append('constructor',six._constructor,functions['layout']);append('timer',six._timer,functions['update'])
    c._require(len(code)<=c.MAX_APPENDIX_BYTES-c.LAYOUT_MAX_BYTES-23,'Theme code exceeds bounded appendix.')
    c._require(six.BASE+offset+len(code)<0x080f5000,'Theme reaches settings area.')
    replacements={six.HOOK_CONSTRUCTOR:six._branch(six.BASE+six.HOOK_CONSTRUCTOR,functions['constructor'],True),
                  six.HOOK_TIMER:struct.pack('<I',functions['timer']|1)}
    return bytes(code),replacements,{'appendix_offset':offset,'code_bytes':len(code),'functions':{k:v-six.BASE for k,v in functions.items()},
        'new_owned_widgets':1+len(leaves),'new_timers':0,'new_global_ram_bytes':0,'layout':spec,
        'normalized_channel_range':[-100,100],'native_panel':[20,30,215,270]}


def paint(canvas,key,values=None):
    """Tk preview from the native scene; illustrative inputs, no USB writes."""
    values={0:75,1:0,2:-15,3:35,4:65,**(values or {})}
    canvas.delete('all');width=max(1,canvas.winfo_width());height=max(1,canvas.winfo_height())
    scale=min(width/215,height/270);ox=(width-215*scale)/2;oy=(height-270*scale)/2
    canvas.create_rectangle(ox,oy,ox+215*scale,oy+270*scale,fill=BACKGROUND,outline='')
    def coords(box):x,y,w,h=box;return ox+x*scale,oy+y*scale,ox+(x+w)*scale,oy+(y+h)*scale
    for item in scene(key):
        if item.get('hidden'):continue
        box=item['box'];channel=item.get('channel');value=values.get(channel,0)
        color=item['color']
        if item.get('role')=='segment' and value<item['threshold']:color=TRACK
        if item['kind']=='label':
            text=f'{value}%' if item.get('role')=='value' else item['text']
            x,y,_,_=coords(box)
            canvas.create_text(x,y,anchor='nw',text=text,fill=color,font=('Segoe UI',-max(5,round(14*scale)),'bold'))
        elif item['kind']=='arc':
            start,end=item['angles'];extent=(end-start)%360
            canvas.create_arc(*coords(box),start=-start,extent=-extent,style='arc',outline=color,width=max(1,item['width']*scale))
        elif item['kind']=='line':
            if item.get('role')=='needle':
                cx,cy=item['center'];points=(cx,cy,*point(cx,cy,item['radius'],135+(value+100)*270/200))
            else:points=item['points']
            canvas.create_line(*[ox+p*scale if n%2==0 else oy+p*scale for n,p in enumerate(points)],fill=color,width=max(1,item['width']*scale))
        elif item['kind']=='bar':
            x,y,x2,y2=coords(box);canvas.create_rectangle(x,y,x2,y2,fill=TRACK,outline=color)
            canvas.create_rectangle(x,y,x+(x2-x)*max(0,min(100,value))/100,y2,fill=color,outline='')
        else:canvas.create_rectangle(*coords(box),fill=color,outline=item.get('border',''))

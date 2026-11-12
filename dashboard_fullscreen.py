"""240 x 320 artwork on a noninteractive, topmost child of the original home.

The stock home and every control remain intact underneath. The stock constructor
creates the menu entry last; it is our identity anchor, not a fixed child index.
Failure can delete only the hidden overlay created by this invocation.
"""
import struct
import dashboard_custom as c
import dashboard_six as six
import dashboard_themes as t
import dashboard_faces as f

THEMES=f.THEMES
MENU=0x200005d8
def validate(spec):
    c._keys(spec,('schema','theme'),'full-screen theme')
    c._require(type(spec['schema']) is int and spec['schema'] in (5,7,8,9),'Unknown full-screen schema.')
    c._require(type(spec['theme']) is str and spec['theme'] in THEMES,'Unknown full-screen theme.')
    return {'schema':spec['schema'],'theme':spec['theme']}
def layout(key):return validate({'schema':9,'theme':key})
def scene(key):return f.scene(key,True,True,native=True,centered=True)
def render(key,values=None,*,usb_active=False):return f.render(key,values,True,True,native=True,usb_active=usb_active,centered=True)
def paint(canvas,key,values=None):
    sample={3:-50,4:50} if values is None else values
    return f.paint(canvas,key,sample,True,True,native=True,usb_active=True,centered=True)

# Magnitudes at the inner edge of the *reported old display bins*. These are
# display endpoints, not ADC measurements or changes to model servo travel.
# 0.6.5: round_half_away(raw/20) = ±83; AUX: floor((rounded+100)/2) = 9 or 91.
PRIMARY_STOPS=(1650,1650)
AUX_STOPS=(1610,1630)

def channel_percent(addr,negative,positive):
    # Symmetric rounding around the exact neutral, separate endpoint magnitudes.
    # Clamp before negating or multiplying so even INT32_MIN/MAX are bounded.
    a=t.Code(addr);a.imm(1,-negative);a.cmp_reg(0,1);a.jump('minimum',13)
    a.imm(1,positive);a.cmp_reg(0,1);a.jump('maximum',10)
    a.imm(2,positive);a.imm(3,0);a.cmp(0,0);a.jump('scale',10)
    a.emit(0x4240);a.imm(2,negative);a.imm(3,1)
    a.mark('scale');a.imm(1,100);a.emit(0x4348,0x0851,0x1840) # abs*100 + span/2
    a.emit(0xfb90,0xf0f2);a.cmp(3,0);a.jump('done',0);a.emit(0x4240)
    a.mark('done');a.emit(0x4770)
    a.mark('minimum');a.imm(0,-100);a.emit(0x4770)
    a.mark('maximum');a.imm(0,100);a.emit(0x4770)
    return a.finish()

def home_tail(a,failure):
    # r5 = original 240x320 home; r0 = address of its final child slot.
    a.load_global(5,six.ROOT);c._not_null(a,5,failure)
    a.load_global(4,MENU);c._not_null(a,4,failure);a.ldr(0,4,4)
    a.cmp_reg(0,5);a.jump(failure,1)
    a.ldr(1,5,8);c._not_null(a,1,failure)
    a.ldr(0,1);c._not_null(a,0,failure);a.ldr(2,1,4)
    a.cmp(2,2);a.jump(failure,3);a.cmp(2,128);a.jump(failure,8)
    a.emit(0x3a01,0x0092,0x1880) # --count; count*=4; r0+=count

def owned_leaves(a,leaves,failure,table):
    c._array(a,7,6,len(leaves),failure)
    a.imm(2,table);a.imm(3,len(leaves)*4);a.imm(4,0);a.mark('edges')
    a.emit(0x5938);c._not_null(a,0,failure)
    a.ldr(1,0,4);a.cmp_reg(1,6);a.jump(failure,1)
    a.ldr(0,0);a.emit(0x5911);a.cmp_reg(0,1);a.jump(failure,1)
    a.emit(0x3404);a.cmp_reg(4,3);a.jump('edges',1)

def check_overlay(a,leaves,failure,table):
    home_tail(a,failure);a.ldr(6,0);a.emit(0x3804);a.ldr(1,0)
    a.cmp_reg(4,1);a.jump(failure,1)
    c._typed(a,6,5,six.PANEL,failure)
    owned_leaves(a,leaves,failure,table)

def records(data,leaves,tables):
    records={};group=[];start=0
    for i,v in enumerate([*leaves,{'kind':None}]):
        if v['kind']=='img':
            if not group:start=i
            group.append(struct.pack('<IHHHHI',tables[v['sprite']],*v['box'],int(bool(v.get('hidden')))))
        elif group:
            records[start]=(data(b''.join(group)),len(group));group=[]
    return records

def images(addr):
    # parent, [start,end) immutable 16-byte records. Preserve our caller's root.
    a=t.Code(addr);a.emit(0xb5f8);a.mov(7,0);a.mov(5,1);a.mov(6,2)
    a.mark('loop');a.mov(0,7);a.call(t.IMG_CREATE);a.mov(4,0);c._not_null(a,4,'failed')
    a.method('remove_style_all');a.method('clear_flag',c.NONINTERACTIVE_CLIPPED)
    a.mov(0,4);a.emit(0x8929,0x896a);a.call('size') # ldrh r1,[r5,#8]; ldrh r2,[r5,#10]
    a.mov(0,4);a.imm(1,1);a.emit(0x88aa,0x88eb);a.call('align')
    a.mov(0,4);a.ldr(1,5);a.call(t.IMG_SRC)
    a.ldr(0,5,12);a.cmp(0,0);a.jump('shown',0);a.method('add_flag',1)
    a.mark('shown');a.emit(0x3510);a.cmp_reg(5,6);a.jump('loop',3)
    a.imm(0,1);a.emit(0xbdf8);a.mark('failed');a.imm(0,0);a.emit(0xbdf8);return a.finish()

def lamps(addr,levels):
    a=t.Code(addr);a.emit(0xb5f8);a.mov(5,0);a.imm(3,levels)
    a.emit(0x5c5e,0x5c9f) # ldrb r6,[r3,r1]; ldrb r7,[r3,r2]
    a.mark('step');a.cmp_reg(6,7);a.jump('done',0);a.jump('down',8)
    a.emit(0x00b0,0x5828);a.imm(1,1);a.call('clear_flag');a.emit(0x3601);a.jump('step')
    a.mark('down');a.emit(0x3e01,0x00b0,0x5828);a.imm(1,1);a.call('add_flag');a.jump('step')
    a.mark('done');a.emit(0xbdf8);return a.finish()

def centered_lamps(addr,levels):
    """Walk the changed boundaries. At neutral all sixteen lamps are dark."""
    a=t.Code(addr);a.emit(0xb5f8);a.mov(5,0);a.imm(3,levels)
    a.emit(0x5c5e,0x5c9f)  # old and new boundaries, each in 0..16
    a.mark('step');a.cmp_reg(6,7);a.jump('done',0);a.jump('left',8)
    # Moving right crosses slot old. Hide the slot on the negative side.
    a.emit(0x00b0,0x5828,0x3601);a.imm(1,1);a.cmp(6,8);a.jump('hide',9)
    a.jump('show')
    # Moving left crosses slot old-1. Hide the slot on the positive side.
    a.mark('left');a.emit(0x3e01,0x00b0,0x5828);a.imm(1,1);a.cmp(6,8);a.jump('hide',2)
    a.mark('show');a.call('clear_flag');a.jump('step')
    a.mark('hide');a.call('add_flag');a.jump('step')
    a.mark('done');a.emit(0xbdf8);return a.finish()


def set_needle(addr):
    """Apply a pre-rasterized needle record (descriptor, x, y, w, h)."""
    a=t.Code(addr);a.emit(0xb570);a.mov(4,0);a.mov(5,1)
    a.mov(0,4);a.emit(0x8929,0x896a);a.call('size')
    a.mov(0,4);a.imm(1,1);a.emit(0x88aa,0x88eb);a.call('align')
    a.mov(0,4);a.ldr(1,5);a.call(t.IMG_SRC)
    a.emit(0xbd70);return a.finish()


USB_CONFIG_STATE=0x20000f7c
USB_CLOCK_ENABLE=0x4002101c
USB_FRAME_NUMBER=0x40005c48

def usb_power_status(addr,cache,badge):
    """Report a live PC link. The battery gauge holds its own real reading.

    The official 2.0.5 HID task requires state 5. Its frame number stops on
    disconnect/suspend, even if that software state is stale. Keep the last
    11-bit frame number and a two-bit grace count in one owned hidden bar.
    The MMIO registers are read-only here. Never read USB with its clock off.
    """
    a=t.Code(addr);a.emit(0xb5f8)
    t.leaf(a,4,cache);a.mov(0,4);a.call('bar_get_value');a.mov(5,0)
    # 8192 is distinct from every valid frame/count pair, including frame zero.
    a.imm(6,8192)
    a.load_global(0,USB_CONFIG_STATE);a.cmp(0,5);a.jump('store',1)
    a.load_global(0,USB_CLOCK_ENABLE);a.emit(0x0200);a.jump('store',5)  # USBEN bit 23 -> N
    a.imm(0,USB_FRAME_NUMBER);a.emit(0x8800);a.imm(1,0x7ff);a.emit(0x4008)
    a.mov(6,0);a.emit(0x00b6,0x08a9)  # new frame << 2; old frame >> 2
    a.imm(2,8192);a.cmp_reg(5,2);a.jump('store',0)  # first sample only seeds the comparison
    a.cmp_reg(0,1);a.jump('advanced',1)
    a.mov(0,5);a.imm(1,3);a.emit(0x4008);a.cmp(0,0);a.jump('store',0)
    a.emit(0x3801,0x1836);a.jump('store')
    a.mark('advanced');a.emit(0x3603)
    a.mark('store');a.cmp_reg(5,6);a.jump('result',0)
    a.mov(0,4);a.mov(1,6);a.imm(2,0);a.call('bar_value')
    a.imm(1,3);a.mov(0,5);a.emit(0x4008);a.mov(2,6);a.emit(0x400a)
    if badge is not None:
        a.cmp(2,0);a.jump('inactive',0)
        a.cmp(0,0);a.jump('result',1)
        t.leaf(a,4,badge);a.method('clear_flag',1);a.jump('result')
        a.mark('inactive');a.cmp(0,0);a.jump('result',0)
        t.leaf(a,4,badge);a.method('add_flag',1)
    a.mark('result');a.mov(0,6);a.imm(1,3);a.emit(0x4008,0xbdf8)
    return a.finish()

def construct(addr,leaves,tables,updater,image_fn):
    a=t.Code(addr);a.emit(0xb5f8);six._home_guard(a,'return');home_tail(a,'return')
    a.ldr(1,0);a.cmp_reg(1,4);a.jump('return',1) # guarded against a second invocation
    a.mov(0,5);a.call('obj_create');a.mov(6,0);c._not_null(a,6,'return')
    a.mov(4,6);a.method('add_flag',1);a.method('remove_style_all')
    a.method('clear_flag',c.NONINTERACTIVE_CLIPPED);a.box(0,0,240,320)
    a.method('bg_color',0,0);a.method('style',0x21,255,0)
    # No border, padding, radius or inherited style can expose the old blue home.
    for n,item in enumerate(leaves):
        kind=item['kind'];color=c.native_color(item['color'])
        if kind=='img':
            if n in tables['records']:
                start,count=tables['records'][n]
                a.mov(0,6);a.imm(1,start);a.imm(2,start+count*16);a.call(image_fn)
                c._not_null(a,0,'failed')
            continue
        a.mov(0,6);a.call(t.LINE_CREATE if kind=='line' else kind+'_create')
        a.mov(4,0);c._not_null(a,4,'failed')
        a.method('remove_style_all');a.method('clear_flag',c.NONINTERACTIVE_CLIPPED)
        a.box(*item['box'])
        if kind=='line':
            for prop,value in ((0x849,item['width']),(0x4d,color),(0x4e,255),(0x4c,1)):a.method('style',prop,value,0)
            a.method(t.LINE_POINTS,tables[n]+8*item.get('initial_index',0),2)
        elif kind=='bar':
            if item['channel']==0:
                for part,col in ((0,c.native_color(t.TRACK)),(0x20000,color)):
                    a.method('bg_color',col,part);a.method('style',0x21,255,part)
            a.method('bar_mode',0)
            if item.get('role')=='usb_frames':a.method('bar_range',0,8192)
            else:a.method('bar_range',0 if item['channel']==0 else -100,100)
            a.method('bar_value',8192 if item.get('role')=='usb_frames' else 0,0)
        else:
            a.method('bg_color',color,0);a.method('style',0x21,255,0);a.method('radius',item['radius'],0)
        if item.get('hidden'):a.method('add_flag',1)
    owned_leaves(a,leaves,'failed',tables['classes'])
    a.mov(4,6);a.method('clear_flag',1);a.call(updater);a.jump('return')
    a.mark('failed');a.mov(0,6);a.call('obj_delete')
    a.mark('return');a.emit(0xbdf8);return a.finish()


"""Optional photo header for the 240 × 320 home, down to the lower grid at y=200."""
import dashboard_custom as c
import dashboard_six as six
import dashboard_fullscreen as fs

HEIGHT = 200
BODY = (6, 6, 23, 11)
TIP = (29, 9, 3, 5)
INK = '#eef5ed'
FILL = '#79e89d'
TRACK = '#18342b'


def create(addr, color, photo_descriptor):
    """Append a non-interactive cover after the stock menu; fail without covering it."""
    a=c._Code(addr);a.emit(0xb5f8)
    fs.home_tail(a,'no');a.ldr(1,0);a.cmp_reg(1,4);a.jump('no',1)
    a.mov(0,5);a.call('obj_create');a.mov(6,0);c._not_null(a,6,'no')
    a.mov(4,6);a.method('add_flag',1);a.method('remove_style_all')
    a.method('clear_flag',c.NONINTERACTIVE_CLIPPED);a.box(0,0,240,HEIGHT)
    a.method('bg_color',c.native_color(color),0);a.method('style',0x21,255,0)
    if photo_descriptor:
        # A clipped descriptor over the same palette and first 200 scanlines.
        a.method('style',0x828,photo_descriptor,0);a.method('style',0x29,255,0)
    for index,kind in enumerate(('bar','obj','bar')):
        a.mov(0,6);a.call(kind+'_create');a.mov(4,0);c._not_null(a,4,'failed')
        a.method('remove_style_all');a.method('clear_flag',c.NONINTERACTIVE_CLIPPED)
        if index==0:
            a.box(*BODY);a.method('bar_mode',0);a.method('bar_range',0,100);a.method('bar_value',0,0)
            for part,tint in ((0,TRACK),(0x20000,FILL)):
                a.method('bg_color',c.native_color(tint),part);a.method('style',0x21,255,part)
            a.method('style',0x1032,1,0);a.method('style',0x30,c.native_color(INK),0);a.method('style',0x31,255,0)
            for prop in (0x1010,0x1011,0x1012,0x1013):a.method('style',prop,2,0)
        elif index==1:
            a.box(*TIP);a.method('bg_color',c.native_color(INK),0);a.method('style',0x21,255,0)
        else:
            a.method('add_flag',1);a.method('bar_range',0,8192);a.method('bar_value',8192,0)
    a.mov(4,6);a.method('clear_flag',1);a.imm(0,1);a.emit(0xbdf8)
    a.mark('failed');a.mov(0,6);a.call('obj_delete')
    a.mark('no');a.imm(0,0);a.emit(0xbdf8);return a.finish()


def refresh(addr,usb_status):
    a=c._Code(addr);a.emit(0xb5f8)
    fs.home_tail(a,'done');a.ldr(6,0);a.emit(0x3804);a.ldr(1,0);a.cmp_reg(4,1);a.jump('done',1)
    c._typed(a,6,5,six.PANEL,'done');c._array(a,7,6,3,'done')
    for index,ref in enumerate((0x20000684,six.PANEL,0x20000684)):
        a.ldr(0,7,index*4);c._typed(a,0,6,ref,'done')
    a.call(usb_status);a.cmp(0,0);a.jump('battery',0)
    a.imm(0,100);a.jump('value')
    a.mark('battery');a.load_global(0,0x200005cc);c._not_null(a,0,'done');a.call('arc_get_value')
    a.cmp(0,100);a.jump('done',8)
    a.mark('value');a.mov(5,0);a.ldr(4,7);a.mov(0,4);a.call('bar_get_value')
    a.cmp_reg(0,5);a.jump('done',0);a.mov(0,4);a.mov(1,5);a.imm(2,0);a.call('bar_value')
    a.mark('done');a.emit(0xbdf8);return a.finish()

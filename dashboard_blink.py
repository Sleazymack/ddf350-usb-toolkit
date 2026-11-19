"""CH2 over-range flash, driven by the existing LVGL home timer only."""
import dashboard_custom as c
import dashboard_six as six
import struct

HALF_PERIOD_MS = 125
THRESHOLD = 90


def set_hidden(address):
    """r0 object, r1 boolean; change the hidden flag only when necessary."""
    a = c._Code(address)
    a.emit(0xb570)
    a.mov(4, 0)
    a.mov(5, 1)
    a.ldr(0, 4, 0x1c)
    a.imm(2, 1)
    a.emit(0x4010)
    a.cmp_reg(0, 5)
    a.jump('done', 0)
    a.mov(0, 4)
    a.imm(1, 1)
    a.cmp(5, 0)
    a.jump('show', 0)
    a.call('add_flag')
    a.jump('done')
    a.mark('show')
    a.call('clear_flag')
    a.mark('done')
    a.emit(0xbd70)
    return a.finish()


def phase(a):
    """Input r5 displayed CH2; output r6 hidden. Saved r0 is the timer pointer."""
    a.imm(6, 0)
    a.cmp(5, THRESHOLD)
    a.jump('phase_done', 13)
    a.emit(0x9800)  # LDR r0,[sp,#0], saved original callback argument.
    a.cmp(0, 0)
    a.jump('phase_done', 0)
    a.ldr(0, 0, 4)  # Native LVGL timer.last, in milliseconds.
    a.imm(1, HALF_PERIOD_MS)
    a.emit(0xfb90, 0xf0f1)  # UDIV r0,r0,r1.
    a.imm(1, 1)
    a.emit(0x4008)
    a.mov(6, 0)
    a.mark('phase_done')


def custom(address, widgets, flag_function):
    index, widget = next((index, item) for index, item in enumerate(widgets) if item['channel'] == 2)
    a = c._Code(address)
    a.emit(0xb5f1)  # r0, r4-r7, lr: timer retained across the ownership guard.
    six._home_guard(a, 'done')
    c._tree(a, widgets, 'done')
    a.ldr(0, 4, index * 4)
    a.ldr(0, 0, 8)
    a.ldr(7, 0)
    a.ldr(0, 7)
    a.call('arc_get_value' if widget['kind'] == 'semicircle' else 'bar_get_value')
    a.mov(5, 0)
    phase(a)
    # Keep the solid backing and channel name visible in both phases.
    for child in ((2,) if widget['kind'] == 'number' else (0, 2)):
        a.ldr(0, 7, child * 4)
        a.mov(1, 6)
        a.call(flag_function)
    a.mark('done')
    a.emit(0xbdf1)
    return a.finish()


def faces(address, leaves, flag_function, classes, levels):
    import dashboard_fullscreen as lcd
    import dashboard_themes as theme
    a = c._Code(address)
    a.emit(0xb5f1)
    six._home_guard(a, 'done')
    lcd.check_overlay(a, leaves, 'done', classes)
    cache = next(index for index, item in enumerate(leaves) if item.get('channel') == 2 and item.get('role') == 'cache')
    theme.leaf(a, 0, cache)
    a.call('bar_get_value')
    a.mov(5, 0)
    phase(a)
    a.mov(0, 5)
    a.emit(0x3064)
    a.imm(1, levels)
    a.emit(0x5c0d)  # LDRB r5,[r1,r0], signed-value to lit boundary.
    for index, item in enumerate(leaves):
        if item.get('channel') != 2 or item.get('role') not in ('digit', 'percent', 'segment'):
            continue
        theme.leaf(a, 0, index)
        a.mov(1, 6)
        if item['role'] == 'segment':
            a.cmp(6, 1)
            a.jump(f'apply{index}', 0)
            a.imm(1, 1)
            a.cmp(5, item['slot'])
            a.jump(f'visible{index}', 13 if item['slot'] < 8 else 12)
            a.jump(f'apply{index}')
            a.mark(f'visible{index}')
            a.imm(1, 0)
            a.mark(f'apply{index}')
        a.call(flag_function)
    a.mark('done')
    a.emit(0xbdf1)
    return a.finish()


def timer(address, update, blink):
    a = c._Code(address)
    a.emit(0xb510)
    a.mov(4, 0)
    six._home_guard(a, 'done')
    a.mov(0, 4)
    a.call(six.NATIVE_TIMER)
    if update:a.call(update)
    a.mov(0, 4)
    a.call(blink)
    a.mark('done')
    a.emit(0xbd10)
    return a.finish()


def native(address, flag_function):
    a=c._Code(address)
    a.emit(0xb5f1)
    six._home_guard(a,'done')
    a.load_global(5,six.ROOT)
    a.load_global(4,0x20000688)
    c._typed(a,4,5,0x20000684,'done')
    a.load_global(7,0x20000670)
    a.mov(0,7)
    c._typed(a,0,5,0x20000664,'done')
    a.mov(0,4)
    a.call('bar_get_value')
    a.mov(5,0)
    phase(a)
    for node in (4,7):
        a.mov(0,node)
        a.mov(1,6)
        a.call(flag_function)
    a.mark('done')
    a.emit(0xbdf1)
    return a.finish()


def build_native(original, offset, spec):
    import patch_firmware as patcher
    patcher._require_original(original)
    c._require(offset>=len(original) and offset%4==0,'Invalid native alarm appendix offset.')
    code=bytearray()
    replacements={}
    update=None
    if spec['native_dashboard']=='ch123456':
        body,replacements,report=six.build_appendix(original,offset)
        code.extend(body)
        update=six.BASE+report['functions']['update']
    elif spec['native_dashboard']=='ch1234':
        replacements={position:new for position,_,new in patcher.DASHBOARD_PATCHES}
    flags=six.BASE+offset+len(code)
    code.extend(set_hidden(flags))
    flash=six.BASE+offset+len(code)
    code.extend(native(flash,flags))
    callback=six.BASE+offset+len(code)
    code.extend(timer(callback,update,flash))
    replacements[six.HOOK_TIMER]=struct.pack('<I',callback|1)
    return bytes(code),replacements,{'layout':spec,'new_timers':0,'new_global_ram_bytes':0}

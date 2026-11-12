"""Build the optional six-row home screen, entirely offline.

The code generated here is original Thumb code. Native graphics routines and
fonts are referenced in the user's hash-verified 2.0.5 image, never bundled.
Four existing bars retain their native updates. Two new rows are children of
the existing home panel: no RAM address is appropriated and no timer is added.
This layout has not been installed or visually tested on hardware.
"""
from __future__ import annotations

import struct

BASE = 0x08005000
ROOT, PAGE, PANEL = 0x20000790, 0x200005B4, 0x200005C4
HOOK_CONSTRUCTOR, HOOK_TIMER = 0x59AE4, 0x5850C
NATIVE_TIMER = BASE + 0x59BC8
ORIGINAL_SITES = {
    HOOK_CONSTRUCTOR: bytes.fromhex("f1f7e0fd"),
    HOOK_TIMER: struct.pack("<I", NATIVE_TIMER | 1),
}
API = {name: BASE + offset for name, offset in {
    "label_create": 0x49300, "bar_create": 0x40014,
    "size": 0x50244, "align": 0x4B78A, "state": 0x4B6A8,
    "style": 0x500C4, "label": 0x4A2F4, "label_fmt": 0x4A384,
    "font": 0x50858, "text_align": 0x5081C, "add_style": 0x4B6C8,
    "bg_color": 0x50500, "bar_value": 0x4029E,
    "bar_get_value": 0x40188, "bar_range": 0x401D4,
    "bar_mode": 0x401AC, "radius": 0x5047C,
    "obj_delete": 0x4C21C,
}.items()}
FONT, LABEL_STYLE = BASE + 0x69750, 0x200007B8
ROWS = (
    (1, 0x20000664, 0x20000668, 0x20000684, 202),
    (2, 0x2000066C, 0x20000670, 0x20000688, 218),
    (5, 0x20000674, 0x20000678, 0x2000068C, 266),
    (6, 0x2000067C, 0x20000680, 0x20000690, 282),
)
NEW_ROWS = ((3, 34, 0x2000020C), (4, 50, 0x20000210))


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _words(*words):
    return struct.pack("<" + "H" * len(words), *words)


def _branch(address, target, link=False):
    delta = target - address - 4
    _require(address % 2 == target % 2 == 0 and -(1 << 24) <= delta < (1 << 24),
             "Six-row Thumb branch is out of range or unaligned.")
    sign = (delta >> 24) & 1
    j1, j2 = 1 ^ ((delta >> 23) & 1) ^ sign, 1 ^ ((delta >> 22) & 1) ^ sign
    return _words(0xF000 | (sign << 10) | ((delta >> 12) & 1023),
                  (0xD000 if link else 0x9000) | (j1 << 13) | (j2 << 11) | ((delta >> 1) & 2047))


class _Code:
    """Small deterministic assembler; only instructions used below are exposed."""

    def __init__(self, address):
        self.address, self.code, self.labels, self.fixups = address, bytearray(), {}, []

    def emit(self, *words):
        self.code += _words(*words)

    def imm(self, register, value):
        _require(0 <= register <= 7, "Unsupported immediate register.")
        value &= 0xFFFFFFFF
        if value <= 255:
            self.emit(0x2000 | (register << 8) | value)
            return
        for high, half in ((False, value & 65535), (True, value >> 16)):
            if high and not half:
                continue
            self.emit((0xF2C0 if high else 0xF240) | ((half >> 11 & 1) << 10) | (half >> 12),
                      ((half >> 8 & 7) << 12) | (register << 8) | (half & 255))

    def mov(self, dest, source):
        self.emit(0x4600 | ((dest & 8) << 4) | (source << 3) | (dest & 7))

    def ldr(self, dest, source, offset=0):
        _require(0 <= offset <= 124 and offset % 4 == 0, "Invalid word offset.")
        self.emit(0x6800 | (offset // 4 << 6) | (source << 3) | dest)

    def load_global(self, dest, address):
        self.imm(dest, address)
        self.ldr(dest, dest)

    def cmp(self, register, value):
        self.emit(0x2800 | (register << 8) | value)

    def cmp_reg(self, first, second):
        self.emit(0x4280 | (second << 3) | first)

    def mark(self, name):
        _require(name not in self.labels, "Duplicate assembly label.")
        self.labels[name] = len(self.code)

    def jump(self, name, condition=None):
        # Invert a short conditional branch over a long unconditional branch.
        # Thus all guards remain valid even when the constructor grows.
        if condition is not None:
            self.emit(0xD000 | ((condition ^ 1) << 8) | 1)
        self.fixups.append((len(self.code), name))
        self.emit(0, 0)

    def call(self, target):
        self.code += _branch(self.address + len(self.code), API.get(target, target), True)

    def method(self, name, *args):
        self.mov(0, 4)
        for register, value in enumerate(args, 1):
            self.imm(register, value)
        self.call(name)

    def box(self, x, y, width, height):
        self.method("size", width, height)
        self.method("align", 1, x, y)

    def finish(self):
        for pos, label in self.fixups:
            _require(label in self.labels, "Missing assembly target.")
            self.code[pos:pos + 4] = _branch(self.address + pos, self.address + self.labels[label])
        while len(self.code) % 4:
            self.emit(0xBF00)
        return bytes(self.code)


def _home_guard(a, failure):
    a.load_global(0, ROOT)
    a.cmp(0, 0)
    a.jump(failure, 0)
    a.imm(0, PAGE)
    a.emit(0x7800)  # LDRB r0,[r0].
    a.cmp(0, 1)
    a.jump(failure, 1)


def _children(a, failure):
    """Return panel in r5 and its complete, typed child-array in r4."""
    a.load_global(5, PANEL)
    a.cmp(5, 0)
    a.jump(failure, 0)
    a.ldr(0, 5, 8)  # Native LVGL special attributes.
    a.cmp(0, 0)
    a.jump(failure, 0)
    a.ldr(1, 0, 4)
    a.cmp(1, 6)
    a.jump(failure, 1)
    a.ldr(4, 0)
    a.cmp(4, 0)
    a.jump(failure, 0)
    for index in range(6):
        a.ldr(0, 4, index * 4)
        a.cmp(0, 0)
        a.jump(failure, 0)
        a.ldr(1, 0, 4)  # obj.parent must still be this panel.
        a.cmp_reg(1, 5)
        a.jump(failure, 1)
        a.ldr(1, 0)  # obj.class_p must match a native widget of this type.
        a.load_global(2, 0x20000684 if index % 3 == 2 else 0x20000664)
        a.cmp(2, 0)
        a.jump(failure, 0)
        a.ldr(2, 2)
        a.cmp_reg(1, 2)
        a.jump(failure, 1)


def _convert(address):
    """Signed raw -> direct native-scale percentage, no persistent cache."""
    a = _Code(address)
    a.imm(1, 2000)
    a.cmp_reg(0, 1)
    a.jump("low", 13)  # signed <=
    a.mov(0, 1)
    a.mark("low")
    a.imm(1, -2000)
    a.cmp_reg(0, 1)
    a.jump("sign", 10)  # signed >=
    a.mov(0, 1)
    a.mark("sign")
    a.imm(2, 0)
    a.cmp(0, 0)
    a.jump("scale", 10)
    a.emit(0x4240)  # RSBS r0,r0,#0.
    a.imm(2, 1)
    a.mark("scale")
    a.imm(1, 3)
    a.emit(0x4348, 0x3019)  # MULS r0,r1; ADDS r0,#25.
    a.imm(1, 50)
    a.emit(0xFB90, 0xF0F1)  # SDIV r0,r0,r1.
    a.cmp(2, 0)
    a.jump("return", 0)
    a.emit(0x4240)
    a.mark("return")
    a.emit(0x4770)
    return a.finish()


def _update(address, convert, percent_format):
    a = _Code(address)
    a.emit(0xB5F8)  # r3-r7,lr: 24 bytes, AAPCS aligned.
    _home_guard(a, "return")
    _children(a, "return")
    for index, (_channel, _y, source) in enumerate(NEW_ROWS):
        a.ldr(6, 4, (index * 3 + 2) * 4)
        a.ldr(7, 4, (index * 3 + 1) * 4)
        a.load_global(0, source)
        a.call(convert)
        a.mov(5, 0)
        a.mov(0, 6)
        a.call("bar_get_value")
        a.cmp_reg(0, 5)
        a.jump(f"next{index}", 0)
        a.mov(0, 6)
        a.mov(1, 5)
        a.imm(2, 0)
        a.call("bar_value")
        a.mov(0, 7)
        a.imm(1, percent_format)
        a.mov(2, 5)
        a.call("label_fmt")
        a.mark(f"next{index}")
    a.mark("return")
    a.emit(0xBDF8)
    return a.finish()


def _cleanup(address):
    """Delete at most six partially-created children of the empty home panel."""
    a = _Code(address)
    a.emit(0xB570)  # r4-r6,lr, 16 bytes.
    a.mov(5, 0)
    a.imm(6, 6)
    a.mark("loop")
    a.ldr(0, 5, 8)
    a.cmp(0, 0)
    a.jump("return", 0)
    a.ldr(1, 0, 4)
    a.cmp(1, 0)
    a.jump("return", 0)
    a.cmp(1, 6)
    a.jump("return", 8)  # unsigned higher: do not touch unexpected objects.
    a.ldr(0, 0)
    a.cmp(0, 0)
    a.jump("return", 0)
    a.ldr(0, 0)
    a.cmp(0, 0)
    a.jump("return", 0)
    a.ldr(1, 0, 4)
    a.cmp_reg(1, 5)
    a.jump("return", 1)
    a.call("obj_delete")
    a.emit(0x3E01)  # SUBS r6,#1; hard bound even if the native call fails.
    a.jump("loop", 1)
    a.mark("return")
    a.emit(0xBD70)
    return a.finish()


def _layout(address, strings, update, cleanup):
    a = _Code(address)
    a.emit(0xB5F8)
    _home_guard(a, "return")
    a.load_global(5, PANEL)
    a.cmp(5, 0)
    a.jump("return", 0)
    # The native panel is empty. Do not duplicate children on a repeated call.
    a.ldr(0, 5, 8)
    a.cmp(0, 0)
    a.jump("create", 0)
    a.ldr(0, 0, 4)
    a.cmp(0, 0)
    a.jump("return", 1)
    a.mark("create")
    a.mov(4, 5)
    # Explicit padding makes child coordinates relative to the native panel.
    for prop in (0x1010, 0x1011, 0x1012, 0x1013):
        a.method("style", prop, 0, 0)
    for channel, y, _source in NEW_ROWS:
        for kind in ("title", "value", "bar"):
            a.mov(0, 5)
            a.call("bar_create" if kind == "bar" else "label_create")
            a.mov(4, 0)
            a.cmp(4, 0)
            a.jump("allocation_failed", 0)
            if kind == "bar":
                a.box(35, y + 3, 120, 8)
                a.method("bg_color", 36947, 0)
                a.method("bg_color", 54566, 0x20000)
                a.method("bar_mode", 1)
                a.method("bar_range", -120, 120)
                a.method("radius", 0, 0)
                a.method("bar_value", 0, 0)
            else:
                a.method("add_style", LABEL_STYLE, 0)
                a.method("font", FONT, 0)
                a.method("text_align", 0 if kind == "title" else 3, 0)
                a.box(5 if kind == "title" else 160, y, 25 if kind == "title" else 40, 16)
                a.method("label", strings[f"ch{channel}"] if kind == "title" else strings["zero"])
    # Do not move the four existing rows unless all six children were created.
    _children(a, "return")
    for _channel, title, value, bar, y in ROWS:
        for pointer, x, width, height, dy in ((title, 25, 25, 16, 0),
                                            (value, 180, 40, 16, 0),
                                            (bar, 55, 120, 8, 3)):
            a.load_global(4, pointer)
            a.cmp(4, 0)
            a.jump("return", 0)
            a.box(x, y + dy, width, height)
    a.call(update)
    a.jump("return")
    a.mark("allocation_failed")
    a.mov(0, 5)
    a.call(cleanup)
    a.mark("return")
    a.emit(0xBDF8)
    return a.finish()


def _constructor(address, layout):
    a = _Code(address)
    a.emit(0xB510)  # preserve r4/lr and native return; 8-byte stack.
    a.call("state")  # Exactly the instruction replaced at the constructor end.
    a.mov(4, 0)
    a.call(layout)
    a.mov(0, 4)
    a.emit(0xBD10)
    return a.finish()


def _timer(address, update):
    a = _Code(address)
    a.emit(0xB510)
    a.mov(4, 0)
    _home_guard(a, "return")
    a.mov(0, 4)
    a.call(NATIVE_TIMER)
    # update rechecks home/page/panel after the native callback, before children.
    a.call(update)
    a.mark("return")
    a.emit(0xBD10)
    return a.finish()


def build_appendix(original: bytes, offset: int):
    """Return (appendix, hook replacements, portable metadata).

    The caller must first check the complete original firmware hash. Only two
    native sites change, both confined to home-screen construction/timer setup.
    """
    _require(offset >= len(original) and offset % 4 == 0, "Invalid six-row appendix offset.")
    for site, signature in ORIGINAL_SITES.items():
        _require(original[site:site + len(signature)] == signature,
                 f"Unexpected six-row hook signature at 0x{site:x}.")
    code = bytearray()
    strings = {}
    for name, value in (("ch3", b"CH3\0"), ("ch4", b"CH4\0"),
                        ("zero", b"0%\0"), ("percent", b"%d%%\0")):
        strings[name] = BASE + offset + len(code)
        code += value
    while len(code) % 4:
        code.append(0)
    functions = {}

    def append(name, builder, *args):
        functions[name] = BASE + offset + len(code)
        code.extend(builder(functions[name], *args))

    append("convert", _convert)
    append("update", _update, functions["convert"], strings["percent"])
    append("cleanup", _cleanup)
    append("layout", _layout, strings, functions["update"], functions["cleanup"])
    append("constructor", _constructor, functions["layout"])
    append("timer", _timer, functions["update"])
    replacements = {
        HOOK_CONSTRUCTOR: _branch(BASE + HOOK_CONSTRUCTOR, functions["constructor"], True),
        HOOK_TIMER: struct.pack("<I", functions["timer"] | 1),
    }
    _require(BASE + offset + len(code) <= 0x08100000, "Six-row appendix exceeds the audited application range.")
    return bytes(code), replacements, {
        "appendix_offset": offset, "appendix_bytes": len(code),
        "functions": {name: address - BASE for name, address in functions.items()},
        "strings": {name: address - BASE for name, address in strings.items()},
        "native_hook_offsets": sorted(replacements),
        "new_owned_widgets": 6, "new_timers": 0, "new_global_ram_bytes": 0,
        "row_y": [202, 218, 234, 250, 266, 282],
        "new_row_conversion": "clamp(raw,-2000,2000)*3/50, rounded symmetrically; no native 90/10 filter",
    }

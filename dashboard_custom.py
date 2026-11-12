"""Validated grid layouts and original Thumb builders; no device/file access.

The 215 x 100 native home panel is divided into six columns and four rows.
Only the home constructor and its existing timer callback are hooked. Each
gauge owns a clipping container and three children, all freed with the native
home tree. The six fixed firmware variants do not use this module.
"""
from __future__ import annotations

import json
import re
import struct

import dashboard_six as six
import dashboard_wallpaper as wallpaper

BASE, ROOT, PAGE, PANEL = six.BASE, six.ROOT, six.PAGE, six.PANEL
LAYOUT_MAX_BYTES = 4096
MAX_APPENDIX_BYTES = 32768
TRAILER_MAGIC = b"DDF350CUSTOMv1\0\0"
FORMAT_VERSION = 1
API = dict(six.API, **{name: BASE + offset for name, offset in {
    "obj_create": 0x4C1FC, "arc_create": 0x3F1B4,
    "arc_get_value": 0x3F8A8, "arc_value": 0x3FB60,
    "arc_range": 0x3FA78, "arc_bg_angles": 0x3F8CE,
    "arc_rotation": 0x3FABE, "remove_style": 0x4FA96,
    "remove_style_all": 0x4FBE8, "clear_flag": 0x4C070,
    "add_flag": 0x4B62E, "text_color": 0x50836,
}.items()})
NATIVE_ROWS = tuple(range(0x20000664, 0x20000694, 4))
# Native renderer 0x51252 tests 0x80000. When clear, 0x51270 intersects
# the child clip with the object's coordinates before recursion at 0x5129C.
# Clear clickable, scrollable AND this audited overflow-visible flag.
HIDDEN, NONINTERACTIVE_CLIPPED = 1, 0x80012


class LayoutError(ValueError):
    """The supplied layout is unsupported or exceeds a fixed bound."""


def _require(condition, message):
    if not condition:
        raise LayoutError(message)


def _keys(value, expected, label):
    _require(type(value) is dict and set(value) == set(expected), f"Unexpected {label} fields.")


def _integer(value, minimum, maximum, label):
    _require(type(value) is int and minimum <= value <= maximum,
             f"{label} must be an integer from {minimum} to {maximum}.")
    return value


def _color(value):
    _require(type(value) is str and re.fullmatch(r"#[0-9a-fA-F]{6}", value) is not None,
             "Colors must use #RRGGBB.")
    return value.lower()


def validate_layout(layout):
    """Return a fresh canonical dictionary; unknown fields are rejected."""
    if type(layout) is dict and type(layout.get('schema')) is int and layout['schema']==12:
        minimal='header' in layout
        _keys(layout,('schema','background','widgets','wallpaper')+(('header',) if minimal else ()),'full home background')
        if minimal:_require(layout['header']=='battery_only','Unknown upper dashboard style.')
        from dashboard_zones import validate_lower
        base=validate_lower({k:(10 if k=='schema' else v) for k,v in layout.items() if k not in ('wallpaper','header')})
        if layout['wallpaper'] is not None:wallpaper.raw(layout['wallpaper'])
        return {**base,'schema':12,'wallpaper':layout['wallpaper'],**({'header':'battery_only'} if minimal else {})}
    if type(layout) is dict and layout.get('schema') in (6,10):
        from dashboard_zones import validate_lower
        return validate_lower(layout)
    if type(layout) is dict and type(layout.get('schema')) is int and layout['schema']==11:
        from dashboard_zones import validate
        return {**validate({**layout,'schema':2}),'schema':11}
    if type(layout) is dict and layout.get('schema') in (5,7,8,9):
        from dashboard_fullscreen import validate
        return validate(layout)
    if type(layout) is dict and layout.get('schema')==4:
        from dashboard_faces import validate
        return validate(layout)
    if type(layout) is dict and layout.get('schema')==3:
        from dashboard_themes import validate
        return validate(layout)
    if type(layout) is dict and layout.get('schema')==2:
        from dashboard_zones import validate
        return validate(layout)
    _keys(layout, ("schema", "background", "widgets"), "layout")
    _integer(layout["schema"], 1, 1, "schema")
    background = _color(layout["background"])
    _require(type(layout["widgets"]) is list and 1 <= len(layout["widgets"]) <= 6,
             "A layout must contain one to six gauges.")
    widgets, ids, channels, occupied = [], set(), set(), set()
    for item in layout["widgets"]:
        _keys(item, ("id", "channel", "kind", "col", "row", "color"), "widget")
        name = item["id"]
        _require(type(name) is str and re.fullmatch(r"[A-Za-z0-9_-]{1,24}", name) is not None,
                 "Widget IDs must contain 1-24 ASCII letters, digits, underscores or hyphens.")
        _require(name not in ids, "Duplicate widget ID.")
        channel = _integer(item["channel"], 1, 6, "channel")
        _require(channel not in channels, "Each channel can appear only once.")
        kind = item["kind"]
        _require(type(kind) is str and kind in ("bar", "semicircle"), "Unknown gauge kind.")
        width, height = (4, 1) if kind == "bar" else (2, 2)
        col, row = _integer(item["col"], 0, 5, "col"), _integer(item["row"], 0, 3, "row")
        _require(col + width <= 6 and row + height <= 4, "Gauge extends beyond the 6 x 4 grid.")
        cells = {(x, y) for y in range(row, row + height) for x in range(col, col + width)}
        _require(not occupied.intersection(cells), "Gauges overlap.")
        occupied.update(cells)
        ids.add(name)
        channels.add(channel)
        widgets.append(dict(id=name, channel=channel, kind=kind, col=col, row=row, color=_color(item["color"])))
    widgets.sort(key=lambda item: (item["row"], item["col"], item["id"]))
    return {"schema": 1, "background": background, "widgets": widgets}


def _unique_pairs(pairs):
    result = {}
    for key, value in pairs:
        _require(key not in result, "Duplicate JSON field.")
        result[key] = value
    return result


def parse_layout(data):
    _require(isinstance(data, (str, bytes)), "Layout must be JSON text.")
    raw = data.encode("utf-8") if isinstance(data, str) else data
    _require(len(raw) <= wallpaper.JSON_LIMIT, "Layout JSON is too large.")
    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=_unique_pairs)
    except (ValueError, UnicodeError, RecursionError) as error:
        raise LayoutError("Invalid layout JSON.") from error
    _require(len(raw)<=LAYOUT_MAX_BYTES or (isinstance(value,dict) and value.get("schema")==12 and value.get("wallpaper") is not None),"Layout JSON is too large.")
    return validate_layout(value)


def canonical_json(layout):
    return json.dumps(validate_layout(layout), sort_keys=True, separators=(",", ":")).encode("ascii")

def current_layout(layout):
    """Prepare an authored design for installation; old firmware keeps its exact builder."""
    spec=validate_layout(layout)
    if spec['schema']==1:
        return {**spec,'schema':10,'widgets':[{**w,'zone':'B'} for w in spec['widgets']]}
    if spec['schema'] in (2,6):
        return {**spec,'schema':11 if spec['schema']==2 else 10}
    if 'theme' in spec:
        from dashboard_fullscreen import layout as theme_layout
        return theme_layout(spec['theme'])
    return spec

def rectangle(widget):
    if 'zone' in widget:
        from dashboard_zones import rectangle as zone_rectangle
        return zone_rectangle(widget)
    width, height = (4, 1) if widget["kind"] == "bar" else (2, 2)
    x = widget["col"] * 215 // 6
    return (x, widget["row"] * 25, (widget["col"] + width) * 215 // 6 - x, height * 25)


def widget_parts(widget):
    """Pure preview/build geometry for a validated widget.

    Container coordinates are relative to the native 215 x 100 panel. Gauge
    and text rectangles are relative to that container. A semicircle's full
    68 x 68 native object is clipped by its container; only angles 180..360
    are drawn. These same rectangles generate the firmware instructions.
    """
    if 'zone' in widget:
        from dashboard_zones import parts
        return parts(widget)
    container = rectangle(widget)
    width = container[2]
    if widget["kind"] == "bar":
        gauge, title, value = (30, 8, width - 78, 8), (0, 4, 25, 16), (width - 40, 4, 40, 16)
        align = {"title": "left", "value": "right"}
    else:
        gauge = ((width - 68) // 2, 0, 68, 68)
        title, value = ((width - 40) // 2, 14, 40, 16), ((width - 40) // 2, 33, 40, 16)
        align = {"title": "center", "value": "center"}
    return {"kind": widget["kind"], "container": container, "gauge": gauge,
            "title": title, "value": value, "text_align": align,
            "font_line_height": 16, "range": (-120, 120),
            "arc_angles": (180, 360) if widget["kind"] == "semicircle" else None,
            "arc_width": 4 if widget["kind"] == "semicircle" else None}


def native_color(color):
    red, green, blue = (int(color[index:index + 2], 16) for index in (1, 3, 5))
    rgb565 = ((red >> 3) << 11) | ((green >> 2) << 5) | (blue >> 3)
    return ((rgb565 & 255) << 8) | (rgb565 >> 8)


def track_color(color, background):
    values = [(int(color[i:i + 2], 16) + 3 * int(background[i:i + 2], 16)) // 4
              for i in (1, 3, 5)]
    return "#" + "".join(f"{value:02x}" for value in values)


class _Code(six._Code):
    def call(self, target):
        self.code += six._branch(self.address + len(self.code), API.get(target, target), True)


def _not_null(a, register, failure):
    a.cmp(register, 0)
    a.jump(failure, 0)


def _typed(a, register, parent, reference, failure):
    _not_null(a, register, failure)
    a.ldr(1, register, 4)
    a.cmp_reg(1, parent)
    a.jump(failure, 1)
    a.ldr(1, register)
    a.load_global(2, reference)
    _not_null(a, 2, failure)
    a.ldr(2, 2)
    a.cmp_reg(1, 2)
    a.jump(failure, 1)


def _array(a, dest, owner, count, failure):
    a.ldr(0, owner, 8)
    _not_null(a, 0, failure)
    a.ldr(1, 0, 4)
    a.cmp(1, count)
    a.jump(failure, 1)
    a.ldr(dest, 0)
    _not_null(a, dest, failure)


def _tree(a, widgets, failure):
    """Validate every typed ownership edge; leave container array in r4."""
    a.load_global(5, PANEL)
    _not_null(a, 5, failure)
    _array(a, 4, 5, len(widgets), failure)
    for index, widget in enumerate(widgets):
        a.ldr(6, 4, index * 4)
        _typed(a, 6, 5, PANEL, failure)
        _array(a, 7, 6, 3, failure)
        for child, reference in ((0, 0x200005CC if widget["kind"] == "semicircle" else 0x20000684),
                                 (1, 0x20000664), (2, 0x20000664)):
            a.ldr(0, 7, child * 4)
            _typed(a, 0, 6, reference, failure)


def _update(address, widgets, convert, percent_format, header_refresh=None):
    a = _Code(address)
    a.emit(0xB5F8)
    six._home_guard(a, "return")
    _tree(a, widgets, "return")
    for index, widget in enumerate(widgets):
        a.ldr(0, 4, index * 4)
        a.ldr(0, 0, 8)
        a.ldr(0, 0)
        a.ldr(6, 0)
        a.ldr(7, 0, 8)
        if widget['kind']=='battery':
            a.load_global(0,0x200005cc)
            _not_null(a,0,'return')
            a.call('arc_get_value')
        else:
            a.load_global(0, 0x20000200 + widget["channel"] * 4)
            a.call(convert)
        a.mov(5, 0)
        a.mov(0, 6)
        a.call("arc_get_value" if widget["kind"] == "semicircle" else "bar_get_value")
        a.cmp_reg(0, 5)
        a.jump(f"next{index}", 0)
        a.mov(0, 6)
        a.mov(1, 5)
        a.imm(2, 0)
        a.call("arc_value" if widget["kind"] == "semicircle" else "bar_value")
        a.mov(0, 7)
        a.imm(1, percent_format)
        a.mov(2, 5)
        a.call("label_fmt")
        a.mark(f"next{index}")
    if header_refresh:a.call(header_refresh)
    a.mark("return")
    a.emit(0xBDF8)
    return a.finish()


def _undecorated(a, parts=(0,)):
    for part in parts:
        for prop in (0x21, 0x1032, 0x840, 0x83A, 0x1010, 0x1011, 0x1012, 0x1013):
            a.method("style", prop, 0, part)


def _layout(address, layout, strings, update, cleanup, header_create=None):
    a = _Code(address)
    a.emit(0xB5F8)
    six._home_guard(a, "return")
    a.load_global(5, PANEL)
    _not_null(a, 5, "return")
    if layout['schema']==12:
        a.load_global(0,ROOT);a.ldr(1,5,4);a.cmp_reg(1,0);a.jump('return',1)
    a.ldr(0, 5, 8)
    a.cmp(0, 0)
    a.jump("create", 0)
    a.ldr(0, 0, 4)
    a.cmp(0, 0)
    a.jump("return", 1)
    a.mark("create")
    # Every top-level container starts hidden; native rows stay visible until
    # the complete tree is available. Failed allocation deletes only our tree.
    for widget in layout["widgets"]:
        parts = widget_parts(widget)
        a.mov(0, 5)
        a.call("obj_create")
        a.mov(4, 0)
        _not_null(a, 4, "allocation_failed")
        a.mov(6, 4)
        a.method("add_flag", HIDDEN)
        a.method("remove_style_all")
        a.method("clear_flag", NONINTERACTIVE_CLIPPED)
        x,y,w,h=parts["container"]
        a.box(x,y-170 if layout["schema"] in (6,10,12) else y,w,h)
        # Container owns gauge first, then title, then value.
        a.mov(0, 6)
        a.call("arc_create" if widget["kind"] == "semicircle" else "bar_create")
        a.mov(4, 0)
        _not_null(a, 4, "allocation_failed")
        foreground = native_color(widget["color"])
        track = native_color(track_color(widget["color"], layout["background"]))
        a.method("clear_flag", NONINTERACTIVE_CLIPPED)
        if widget["kind"] != "semicircle":
            a.box(*parts["gauge"])
            _undecorated(a, (0, 0x20000))
            for part, color in ((0, track), (0x20000, foreground)):
                a.method("bg_color", color, part)
                a.method("style", 0x21, 255, part)
            a.method("radius", 0, 0)
            a.method("bar_mode", 0 if widget['kind']=='battery' else 1)
            a.method("bar_range", 0 if widget['kind']=='battery' else -120, 100 if widget['kind']=='battery' else 120)
            a.method("bar_value", 0, 0)
            if widget['kind']=='number':a.method('add_flag',HIDDEN)
            if widget['kind']=='battery':
                a.method('style',0x1032,1,0)  # native border width (layout flag)
                a.method('style',0x30,foreground,0)
                a.method('style',0x31,255,0)
        else:
            a.box(*parts["gauge"])
            if layout['schema'] in (10,11,12):
                # The 2.0.5 arc constructor clears mode bits [2:1] in its
                # own option word at +0x34. Set symmetrical mode (01)
                # before configuring the sweep, preserving every other bit.
                a.emit(0x8ea0);a.imm(1,6);a.emit(0x4388)
                a.imm(1,2);a.emit(0x4308,0x86a0)
            a.method("remove_style", 0, 0x30000)
            _undecorated(a)
            for part, color in ((0, track), (0x20000, foreground)):
                a.method("style", 0x850, 4, part)
                a.method("style", 0x51, 1, part)
                a.method("style", 0x52, color, part)
                a.method("style", 0x53, 255, part)
            a.method("arc_bg_angles", 180, 360)
            a.method("arc_rotation", 0)
            a.method("arc_range", -120, 120)
            a.method("arc_value", 0)
        for kind in ("title", "value"):
            a.mov(0, 6)
            a.call("label_create")
            a.mov(4, 0)
            _not_null(a, 4, "allocation_failed")
            a.method("add_style", six.LABEL_STYLE, 0)
            a.method("font", six.FONT, 0)
            a.method("text_color", foreground, 0)
            a.method("text_align", 2 if widget["kind"] in ('semicircle','number') else (0 if kind == "title" else 3), 0)
            a.box(*parts[kind])
            a.method("label", strings['battery'] if kind=='title' and widget['kind']=='battery' else strings[f"ch{widget['channel']}"] if kind == "title" else strings["zero"])
    _tree(a, layout["widgets"], "allocation_failed")
    # Verify native pointers before hiding anything, then expose all containers.
    for pointer in NATIVE_ROWS:
        a.load_global(0, pointer)
        _not_null(a, 0, "allocation_failed")
    if layout['schema'] in (2,11):
        from dashboard_zones import UPPER_NATIVE
        for pointer in UPPER_NATIVE:
            a.load_global(0,pointer)
            _not_null(a,0,'allocation_failed')
    if header_create:
        a.call(header_create);_not_null(a,0,'allocation_failed')
    a.mov(4, 5)
    a.method("bg_color", native_color(layout["background"]), 0)
    if layout['schema']==12:
        # Verified 2.0.5: the native home owns this 240x320 root, and PANEL
        # is its opaque, lower 215x100 child. No changes to the widget tree.
        a.method('style',0x21,0,0)
        a.load_global(4,ROOT)
        a.method('bg_color',native_color(layout['background']),0)
        if layout['wallpaper'] is not None:
            # Native 0x50558 passes property 0x828 (BG_IMG_SRC) to style.
            a.method('style',0x828,strings['wallpaper'],0)
            a.method('style',0x29,255,0)
        a.mov(4,5)
    for prop in (0x1010, 0x1011, 0x1012, 0x1013):
        a.method("style", prop, 0, 0)
    for pointer in NATIVE_ROWS:
        a.load_global(4, pointer)
        a.method("add_flag", HIDDEN)
    if layout['schema'] in (2,11):
        a.mov(4,5)
        a.box(20,30,215,270)
        a.method('style',0x21,255,0)
        a.method('clear_flag',NONINTERACTIVE_CLIPPED)
        for pointer in UPPER_NATIVE:
            a.load_global(4,pointer);a.method('add_flag',HIDDEN)
    _array(a, 7, 5, len(layout["widgets"]), "return")
    for index in range(len(layout["widgets"])):
        a.ldr(4, 7, index * 4)
        a.method("clear_flag", HIDDEN)
    a.call(update)
    a.jump("return")
    a.mark("allocation_failed")
    a.mov(0, 5)
    a.call(cleanup)  # Existing helper is bounded at six owned containers.
    a.mark("return")
    a.emit(0xBDF8)
    return a.finish()


def build_appendix(original, offset, layout):
    layout = validate_layout(layout)
    if layout['schema'] in (5,7,8,9):
        from dashboard_faces import build_appendix as build_face
        return build_face(original,offset,layout,full=True)
    if layout['schema']==4:
        from dashboard_faces import build_appendix as build_face
        return build_face(original,offset,layout)
    if layout['schema']==3:
        from dashboard_themes import build_appendix as build_theme
        return build_theme(original,offset,layout)
    _require(offset >= len(original) and offset % 4 == 0, "Invalid custom appendix offset.")
    for site, signature in six.ORIGINAL_SITES.items():
        _require(original[site:site + len(signature)] == signature, "Custom home hook signature differs.")
    code, strings, functions = bytearray(), {}, {}
    for name, data in [(f"ch{channel}", f"CH{channel}\0".encode("ascii")) for channel in range(1, 7)] + [
            ("zero", b"0%\0"), ("percent", b"%d%%\0")]:
        strings[name] = BASE + offset + len(code)
        code.extend(data)
    if layout['schema'] in (2,6,10,11,12):
        strings['battery']=BASE+offset+len(code);code.extend(b'BAT\0')
    while len(code) % 4:
        code.append(0)

    if layout['schema']==12 and layout['wallpaper'] is not None:
        strings['wallpaper']=BASE+offset+len(code);code.extend(wallpaper.descriptor())

    def append(name, builder, *args):
        functions[name] = BASE + offset + len(code)
        code.extend(builder(functions[name], *args))

    minimal=layout.get('header')=='battery_only'
    if minimal:
        import dashboard_header as header
        import dashboard_fullscreen as full
        desc=None
        if layout.get('wallpaper'):
            desc=BASE+offset+len(code);code.extend(wallpaper.descriptor(header.HEIGHT))
        append('header_usb',full.usb_power_status,2,None)
        append('header_refresh',header.refresh,functions['header_usb'])
        append('header_create',header.create,layout['background'],desc)
    append("convert", six._convert)
    append("update", _update, layout["widgets"], functions["convert"], strings["percent"], functions.get("header_refresh"))
    if layout['schema'] in (2,6,10,11,12):
        def cleanup_v2(address):
            # Identical bounded ownership cleanup, with room for battery + CH1-6.
            code=bytearray(six._cleanup(address))
            # MOVS r6,#6 and CMP r1,#6 are unique in this audited helper.
            for before,after in ((b'\x06\x26',b'\x07\x26'),(b'\x06\x29',b'\x07\x29')):
                _require(code.count(before)==1,'Unexpected custom cleanup shape.')
                code[:]=code.replace(before,after)
            return bytes(code)
        append('cleanup',cleanup_v2)
    else:append("cleanup", six._cleanup)
    append("layout", _layout, layout, strings, functions["update"], functions["cleanup"], functions.get("header_create"))
    append("constructor", six._constructor, functions["layout"])
    append("timer", six._timer, functions["update"])
    _require(len(code) <= MAX_APPENDIX_BYTES - LAYOUT_MAX_BYTES - 23,
             "Custom code exceeds its fixed size limit.")
    _require(BASE + offset + len(code) < 0x080F5000, "Custom code reaches the settings area.")
    replacements = {
        six.HOOK_CONSTRUCTOR: six._branch(BASE + six.HOOK_CONSTRUCTOR, functions["constructor"], True),
        six.HOOK_TIMER: struct.pack("<I", functions["timer"] | 1),
    }
    if layout['schema']==12 and layout['wallpaper'] is not None:
        _require(offset+len(code)<wallpaper.PLAYER_OFFSET,'Layout overlaps startup player.')
        code.extend(b'\xff'*(wallpaper.DATA_OFFSET-offset-len(code)))
        code.extend(wallpaper.raw(layout['wallpaper']))
    return bytes(code), replacements, {
        "appendix_offset": offset, "code_bytes": len(code),
        "functions": {name: address - BASE for name, address in functions.items()},
        "new_owned_widgets": 4 * len(layout["widgets"])+(4 if minimal else 0), "new_timers": 0,
        "new_global_ram_bytes": 0, "layout": layout,
    }


def make_trailer(layout, usb_1ms):
    _require(type(usb_1ms) is bool, "USB choice must be a boolean.")
    data = json.dumps({"format": FORMAT_VERSION, "usb_1ms": usb_1ms,
                       "layout": wallpaper.stored(validate_layout(layout))}, sort_keys=True, separators=(",", ":")).encode("ascii")
    _require(len(data) <= LAYOUT_MAX_BYTES, "Custom trailer exceeds its fixed size limit.")
    # Keep the entire firmware word-aligned; regeneration also authenticates
    # these padding bytes instead of ignoring arbitrary data before the JSON.
    padding = b"\0" * (-(len(data) + 4 + len(TRAILER_MAGIC)) % 4)
    return padding + data + struct.pack("<I", len(data)) + TRAILER_MAGIC


def read_trailer(image):
    """Parse bounded metadata only; caller MUST reconstruct/compare all bytes."""
    _require(image.endswith(TRAILER_MAGIC) and len(image) >= len(TRAILER_MAGIC) + 4,
             "Custom trailer is missing.")
    footer = len(TRAILER_MAGIC) + 4
    length = struct.unpack_from("<I", image, len(image) - footer)[0]
    _require(0 < length <= LAYOUT_MAX_BYTES and length <= len(image) - footer,
             "Invalid custom trailer length.")
    try:
        value = json.loads(image[-footer - length:-footer].decode("ascii"), object_pairs_hook=_unique_pairs)
    except (ValueError, UnicodeError, RecursionError) as error:
        raise LayoutError("Invalid custom trailer JSON.") from error
    _keys(value, ("format", "usb_1ms", "layout"), "custom trailer")
    _integer(value["format"], FORMAT_VERSION, FORMAT_VERSION, "format")
    _require(type(value["usb_1ms"]) is bool, "Invalid custom USB choice.")
    return validate_layout(wallpaper.restore(value["layout"],image,len(image)-footer-length)), value["usb_1ms"]

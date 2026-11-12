"""One static RGB565 image owned by the stock welcome screen (2.0.5)."""
import hashlib
import struct

import dashboard_custom as gui
import dashboard_six as six
import startup_animation as legacy

WIDTH, HEIGHT = 192, 256
PIXELS = WIDTH * HEIGHT * 2
SLOT = 0xc0000  # Beyond the largest supported dashboard, including a wallpaper.
MAGIC = b'DDFPHOTO1'
META = struct.Struct('<9s3xI32s')
CODE = SLOT + META.size
DESCRIPTOR = SLOT + 256
DATA = DESCRIPTOR + 12
END = DATA + PIXELS
HOOK = 0x10afe
ORIGINAL = legacy.ORIGINAL_SITES[HOOK]
BRANCH = six._branch(six.BASE + HOOK, six.BASE + CODE, True)


def constructor():
    a = gui._Code(six.BASE + CODE)
    a.emit(0xb570)  # Preserve r4–r6 and LR; keep 8-byte stack alignment.
    a.call(six.BASE + 0x5b2d0)  # Always run the stock welcome constructor first.
    a.mov(5, 0)
    a.imm(0, 0x200005b0); a.emit(0x7800); a.cmp(0, 1); a.jump('done', 1)
    a.load_global(0, 0x200005ac); gui._not_null(a, 0, 'done')
    a.call('obj_create'); a.mov(4, 0); gui._not_null(a, 4, 'done')
    a.method('remove_style_all'); a.method('clear_flag', gui.NONINTERACTIVE_CLIPPED)
    a.box(0, 0, 240, 320)
    a.method('bg_color', 0, 0); a.method('style', 0x21, 255, 0)
    # LVGL centers a non-tiled background image within the object.
    a.method('style', 0x828, six.BASE + DESCRIPTOR, 0)
    a.method('style', 0x29, 255, 0)
    a.mark('done'); a.mov(0, 5); a.emit(0xbd70)
    return a.finish()


def attach(base, pixels):
    if type(pixels) is not bytes or len(pixels) != PIXELS:
        raise ValueError('Invalid RGB565 startup photo.')
    if not 626956 <= len(base) < SLOT or base[HOOK:HOOK+4] != ORIGINAL:
        raise ValueError('Invalid startup photo base.')
    code = constructor()
    if CODE + len(code) > DESCRIPTOR or END > legacy.MAX_IMAGE_SIZE:
        raise ValueError('Startup photo exceeds its flash area.')
    out = bytearray(base)
    out[HOOK:HOOK+4] = BRANCH
    out.extend(b'\xff' * (SLOT - len(out)))
    out.extend(META.pack(MAGIC, len(base), hashlib.sha256(pixels).digest()))
    out.extend(code); out.extend(b'\xff' * (DESCRIPTOR - len(out)))
    out.extend(struct.pack('<III', 4 | WIDTH << 10 | HEIGHT << 21, PIXELS, six.BASE + DATA))
    return bytes(out) + pixels


def unpack(image):
    if len(image) != END or image[HOOK:HOOK+4] != BRANCH:
        raise ValueError('Not a startup photo.')
    magic, size, digest = META.unpack_from(image, SLOT)
    if magic != MAGIC or not 626956 <= size < SLOT:
        raise ValueError('Invalid startup photo header.')
    pixels = image[DATA:END]
    if hashlib.sha256(pixels).digest() != digest:
        raise ValueError('Startup photo checksum mismatch.')
    base = bytearray(image[:size]); base[HOOK:HOOK+4] = ORIGINAL
    return bytes(base), pixels

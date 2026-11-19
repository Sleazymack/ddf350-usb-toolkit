"""Reproducible native LCD artwork for the three November 2026 presets.

Draw directly on the 240 x 320 pixel grid. Runtime uses these same indexed
sprites for the PC preview and the radio, including every live digit and needle.
"""
import base64
from functools import lru_cache
import json
import math
from pathlib import Path
import zlib

from PIL import Image, ImageDraw

import compile_native_faces as native
import pixel_font

KEYS = ('equalizer_gold', 'classic_chrome', 'neon_hex')


def point(cx, cy, radius, angle):
    radians = math.radians(angle)
    return round(cx + radius * math.cos(radians)), round(cy + radius * math.sin(radians))


def text(draw, xy, value, size, color):
    pixel_font.draw_centered(draw, xy, value, size, color)


def sprite(image):
    """Pack opaque native pixels with a transparent zero index, at most 4 bpp."""
    rgb = image.convert('RGB')
    visible = sorted(set(rgb.getdata()) - {(0, 0, 0)})
    if len(visible) > 15:
        reduced = rgb.quantize(colors=15, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.NONE)
        rgb = reduced.convert('RGB')
        # Restore the intentional transparent background after quantization.
        black = image.convert('RGB').convert('L').point(lambda value: 255 if value == 0 else 0)
        rgb.paste((0, 0, 0), mask=black)
        visible = sorted(set(rgb.getdata()) - {(0, 0, 0)})
    bits = next(value for value in (1, 2, 4) if len(visible) < 1 << value)
    palette = bytearray(4 << bits)
    lookup = {(0, 0, 0): 0}
    for index, color in enumerate(visible, 1):
        lookup[color] = index
        r, g, b = color
        palette[index * 4:index * 4 + 4] = bytes((b, g, r, 255))
    pixels = list(rgb.getdata())
    per_byte = 8 // bits
    for y in range(rgb.height):
        row = pixels[y * rgb.width:(y + 1) * rgb.width]
        for x in range(0, rgb.width, per_byte):
            value = 0
            for offset, color in enumerate(row[x:x + per_byte]):
                value |= lookup[color] << (8 - bits * (offset + 1))
            palette.append(value)
    return [rgb.width, rgb.height, bits, base64.b85encode(zlib.compress(palette, 9)).decode('ascii')]


def polygon_frame(draw, points, color, *, inner=None):
    draw.line([*points, points[0]], fill=color, width=1)
    if inner:
        draw.line(inner, fill='#d9d8db', width=1)


def battery(draw, face, *, gold=False):
    edge = '#ffce55' if gold else '#eaf6f2'
    draw.rounded_rectangle((191, 14, 228, 30), radius=2, outline=edge, width=1)
    draw.rectangle((229, 19, 231, 25), fill=edge)
    face['battery'] = [194, 17, 31, 10]
    face['digits']['0'] = [195, 18, 6, 9, 3]
    face['digit_colors']['0'] = '#edffcf' if gold else '#040b09'
    face['battery_color'] = '#3a2d14' if gold else '#75ee59'
    face['usb_position'] = [167, 17]


def footer(draw, color):
    draw.arc((13, 295, 21, 305), 180, 360, fill=color, width=2)
    draw.rounded_rectangle((11, 301, 23, 312), radius=1, fill=color)
    draw.rectangle((16, 305, 18, 309), fill='#090d12')
    draw.line([(217, 300), (223, 306), (217, 312)], fill=color, width=2)


def needle_bank(face, *, radius, color, start, sweep, channels):
    face['needle_color'] = color
    face['needle_width'] = 1
    face['needle_hubs'] = {}
    for channel, cx, cy in channels:
        hub = Image.new('RGB', (9, 9))
        draw = ImageDraw.Draw(hub)
        draw.ellipse((0, 0, 8, 8), fill='#4a4b4c', outline='#eef2f0')
        draw.ellipse((2, 2, 6, 6), fill='#9a9b9c', outline=color)
        face['sprites'][f'hub{channel}'] = sprite(hub)
        face['needle_hubs'][str(channel)] = f'hub{channel}'
        face['needles'].append([cx, cy, radius, radius, start, sweep])


def gold_equalizer(draw, face):
    frame = [(3, 7), (8, 2), (232, 2), (237, 7), (237, 314), (231, 318), (8, 318), (3, 313)]
    polygon_frame(draw, frame, '#77717f')
    polygon_frame(draw, [(6, 11), (11, 6), (229, 6), (234, 11), (234, 312), (7, 312)], '#383139')
    draw.line([(42, 12), (198, 12)], fill='#660c1e', width=3)
    draw.line([(64, 12), (177, 12)], fill='#f52739')
    draw.line([(111, 12), (133, 12)], fill='#ffc2aa')
    polygon_frame(draw, [(9, 21), (15, 16), (37, 16), (44, 23), (196, 23), (204, 16), (226, 16), (232, 22), (232, 39), (9, 39)], '#645967')
    battery(draw, face, gold=True)
    face['digit_colors'].update({str(ch): '#e7ffd1' for ch in range(1, 5)})
    for channel, y in ((1, 45), (2, 126)):
        border = [(9, y + 6), (15, y), (226, y), (232, y + 6), (232, y + 71), (226, y + 77), (15, y + 77), (9, y + 71)]
        polygon_frame(draw, border, '#655368')
        draw.line([(10, y + 7), (16, y + 1), (224, y + 1)], fill='#c5b2b7')
        draw.line([(11, y + 70), (16, y + 75), (226, y + 75), (230, y + 70)], fill='#733b4b')
        polygon_frame(draw, [(12, y + 5), (77, y + 5), (65, y + 24), (12, y + 24)], '#b8aab9')
        text(draw, (43, y + 14), f'CH{channel}', 14, '#ffcc38')
        face['digits'][str(channel)] = [153, y + 6, 13, 21, 4]
        for slot in range(16):
            distance = abs(slot - 7.5) / 7.5
            height = round(2 + 29 * distance ** 2)
            x = 16 + 13 * slot
            on = '#ff1813' if distance > .84 else '#ffae17' if distance > .58 else '#7bf000'
            dark = '#4f0809' if distance > .84 else '#543009' if distance > .58 else '#1e3907'
            draw.rectangle((x, y + 60 - height, x + 8, y + 60), fill=dark, outline=on)
            name = f'lamp{channel}_{slot}'
            lamp = Image.new('RGB', (9, height + 1), on)
            ImageDraw.Draw(lamp).line((0, 0, 8, 0), fill='#f5e258')
            face['sprites'][name] = sprite(lamp)
            face['lamps'].append(dict(sprite=name, x=x, y=y + 60 - height, channel=channel, threshold=slot))
        draw.line((23, y + 63, 217, y + 63), fill='#efbb45')
        for x in range(23, 218, 24):
            draw.line((x, y + 63, x, y + 66), fill='#efbb45')
        for x, value in ((24, '-100'), (120, '0'), (215, '+100')):
            text(draw, (x, y + 70), value, 9, '#ffca46')
    for channel, cx in ((3, 63), (4, 177)):
        polygon_frame(draw, [(cx - 54, 212), (cx - 49, 207), (cx + 49, 207), (cx + 54, 212), (cx + 54, 283), (cx + 49, 288), (cx - 49, 288), (cx - 54, 283)], '#817084')
        cy = 278
        for slot in range(24):
            angle = 183 + slot * 174 / 24
            poly = [point(cx, cy, r, angle + step) for r, steps in ((50, (0, 5.5)), (46, (5.5, 0))) for step in steps]
            color = '#ff2920' if slot < 3 or slot > 20 else '#f6bc2c' if slot < 6 or slot > 17 else '#8af11b'
            draw.polygon(poly, fill=color)
        for angle in range(180, 361, 30):
            draw.line([point(cx, cy, 44, angle), point(cx, cy, 39, angle)], fill='#f4d068')
        text(draw, (cx, 220), '0', 9, '#ffca46')
        draw.line((cx, 225, cx, 232), fill='#f6c73a')
        text(draw, (cx, 242), f'CH{channel}', 14, '#ffca46')
        face['digits'][str(channel)] = [cx - 27, 253, 11, 17, 4]
        for x, label in ((cx - 43, '-100'), (cx + 40, '+100')):
            text(draw, (x, 284), label, 8, '#ffca46')
    needle_bank(face, radius=39, color='#fff3bc', start=180, sweep=180, channels=((3, 63, 278), (4, 177, 278)))
    polygon_frame(draw, [(11, 296), (16, 292), (225, 292), (230, 296), (230, 313), (11, 313)], '#76616a')
    footer(draw, '#ffd05c')


def classic_chrome(draw, face):
    draw.rounded_rectangle((3, 3, 236, 317), radius=8, outline='#123a8d', width=3)
    draw.rounded_rectangle((4, 4, 235, 316), radius=7, outline='#155bff', width=2)
    draw.rounded_rectangle((5, 5, 234, 315), radius=6, outline='#25e9ff', width=1)
    draw.line((6, 34, 234, 34), fill='#56677a')
    battery(draw, face)
    for channel, x in ((1, 10), (2, 184)):
        draw.rounded_rectangle((x, 41, x + 46, 71), radius=4, outline='#5e738b')
        draw.line((x + 3, 54, x + 43, 54), fill='#64717b')
        text(draw, (x + 23, 48), f'CH{channel}', 11, '#f3f3ed')
        face['digits'][str(channel)] = [x + 3, 57, 8, 13, 4]
        face['digit_colors'][str(channel)] = '#f3f3ed'
    for channel, cy in ((3, 109), (4, 232)):
        cx = 120
        # Concentric hard-edged chrome, with a warm instrument face.
        for radius, color in ((72, '#222b34'), (71, '#66717d'), (70, '#bdc5c8'), (69, '#e9eded'), (68, '#a6afb4'), (67, '#4a4b48'), (65, '#dedacc'), (64, '#f4f1e7')):
            draw.ellipse((cx - radius, cy - radius, cx + radius, cy + radius), fill=color)
        draw.arc((cx - 69, cy - 69, cx + 69, cy + 69), 200, 310, fill='#ffffff', width=2)
        for tick in range(41):
            angle = 140 + 260 * tick / 40
            major = tick % 10 == 0
            draw.line([point(cx, cy, 61, angle), point(cx, cy, 54 if major else 57, angle)], fill='#101716', width=2 if major else 1)
        for angle, value in ((140, '-100'), (205, '-50'), (270, '0'), (335, '+50'), (400, '+100')):
            position = point(cx, cy, 45, angle)
            if angle in (140, 400):
                position = (cx - 47 if angle == 140 else cx + 47, cy + 17)
            text(draw, position, value, 11, '#111715')
        text(draw, (cx, cy - 31), f'CH{channel}', 14, '#101512')
        draw.rounded_rectangle((77, cy + 27, 163, cy + 54), radius=5, fill='#e4dfd0', outline='#776e61', width=1)
        draw.line((83, cy + 29, 157, cy + 29), fill='#faf8f0')
        face['digits'][str(channel)] = [80, cy + 30, 16, 23, 4]
        face['digit_colors'][str(channel)] = '#080e0c'
    needle_bank(face, radius=49, color='#ff1c26', start=140, sweep=260, channels=((3, 120, 109), (4, 120, 232)))
    draw.rectangle((7, 293, 233, 314), fill='#000000')
    draw.line((6, 293, 234, 293), fill='#647486')
    footer(draw, '#f0f1ec')


def neon_hex(draw, face):
    border = [(5, 17), (9, 13), (20, 13), (26, 7), (220, 7), (227, 14), (234, 14), (236, 19), (236, 309), (229, 316), (10, 316), (5, 310)]
    polygon_frame(draw, border, '#2787ae')
    draw.line([(5, 32), (166, 32), (183, 7)], fill='#09c5e8')
    for x in (9, 14, 19, 223, 228):
        draw.line((x, 7, x + 3, 3), fill='#84cfff', width=2)
    battery(draw, face)
    for channel, x, color in ((1, 10, '#14f2f2'), (2, 127, '#f126f4')):
        points = [(x, 44), (x + 6, 38), (x + 95, 38), (x + 101, 44), (x + 101, 61), (x + 95, 67), (x, 67)]
        polygon_frame(draw, points, '#58c6f1')
        draw.line([(x + 93, 65), (x + 99, 59)], fill=color, width=2)
        text(draw, (x + 50, 46), f'CH{channel}', 12, '#e1ebf5')
        face['digits'][str(channel)] = [x + 28, 51, 9, 15, 4]
        face['digit_colors'][str(channel)] = '#eff7fd'
    for channel, y, color, shade in ((3, 80, '#04e9ef', '#11445a'), (4, 186, '#ed24f7', '#3a1557')):
        left, right, shoulder = 22, 218, 48
        outline = [(shoulder, y), (192, y), (right, y + 48), (192, y + 96), (shoulder, y + 96), (left, y + 48)]
        draw.polygon(outline, fill='#061724' if channel == 3 else '#100a1d')
        draw.polygon([(52, y + 9), (187, y + 9), (156, y + 45), (34, y + 45)], fill='#082e44' if channel == 3 else '#271038')
        polygon_frame(draw, outline, shade)
        for width, ink in ((5, shade), (3, color)):
            draw.line([(30, y + 28), (48, y + 1), (114, y + 1)], fill=ink, width=width)
            draw.line([(125, y + 1), (191, y + 1), (209, y + 28)], fill=ink, width=width)
            draw.line([(30, y + 68), (48, y + 94), (114, y + 94)], fill=ink, width=width)
            draw.line([(125, y + 94), (191, y + 94), (209, y + 68)], fill=ink, width=width)
            draw.line([(27, y + 37), (21, y + 48), (27, y + 60)], fill=ink, width=width)
            draw.line([(212, y + 37), (218, y + 48), (212, y + 60)], fill=ink, width=width)
        polygon_frame(draw, [(52, y + 9), (188, y + 9), (207, y + 48), (187, y + 87), (53, y + 87), (33, y + 48)], '#1c5475' if channel == 3 else '#4c2677')
        text(draw, (120, y + 21), f'CH{channel}', 20, '#f0f6ff')
        draw.line((65, y + 20, 91, y + 20), fill='#7ac4e2')
        draw.line((149, y + 20, 176, y + 20), fill='#7ac4e2')
        face['digits'][str(channel)] = [55, y + 33, 26, 35, 4]
        face['digit_colors'][str(channel)] = '#f4f8fc'
        for x, value in ((73, '-100'), (120, '0'), (169, '+100')):
            text(draw, (x, y + 77), value, 10, '#e4f0ff')
        draw.line((91, y + 77, 109, y + 77), fill='#57b8da')
        draw.line((132, y + 77, 148, y + 77), fill='#57b8da')
    for x in (11, 229):
        for y in (78, 280):
            draw.ellipse((x - 2, y - 2, x + 2, y + 2), fill='#15364b', outline='#68a0c8')
    draw.line([(6, 292), (36, 292), (47, 303), (222, 303), (233, 292)], fill='#14bddd')
    footer(draw, '#f4f7fd')


def glyphs(face):
    for channel in range(5):
        _, _, width, height, _ = face['digits'][str(channel)]
        color = face['digit_colors'][str(channel)]
        alphabet = native.CHARACTERS if channel else native.CHARACTERS[:-1]
        for index, character in enumerate(alphabet):
            image = pixel_font.cell(character, width, height, color)
            face['sprites'][f'd{channel}_{index}'] = sprite(image)


def background_parts(image):
    """Crop empty space and split mixed-color regions to fit application flash.

    Each part has its own 1/2/4-bit palette. Forty-four parts also keep the
    two equalizer LED groups below the native updater's immediate-offset limit.
    """
    @lru_cache(maxsize=None)
    def bounds(box):
        cropped = image.crop(box).getbbox()
        if cropped:
            x, y, _, _ = box
            return x + cropped[0], y + cropped[1], x + cropped[2], y + cropped[3]

    @lru_cache(maxsize=None)
    def cost(box):
        part = image.crop(box)
        colors = len(set(part.getdata()) - {(0, 0, 0)})
        bits = 1 if colors < 2 else 2 if colors < 4 else 4
        return (part.width * bits + 7) // 8 * part.height + (4 << bits) + 40

    @lru_cache(maxsize=None)
    def best(box):
        x, y, right, bottom = box
        splits = [((x, y, cut, bottom), (cut, y, right, bottom)) for cut in range(x + 4, right - 3, 4)]
        splits += [((x, y, right, cut), (x, cut, right, bottom)) for cut in range(y + 4, bottom - 3, 4)]
        gain, chosen = 0, None
        for split in splits:
            pieces = tuple(part for half in split if (part := bounds(half)))
            saved = cost(box) - sum(cost(part) for part in pieces)
            if saved > gain:
                gain, chosen = saved, pieces
        return gain, chosen

    parts = [box for y in range(0, 320, 28) if (box := bounds((0, y, 240, min(y + 28, 320))))]
    while len(parts) < 44:
        box = max(parts, key=lambda part: best(part)[0])
        gain, pieces = best(box)
        if gain < 40:
            break
        parts.remove(box)
        parts.extend(pieces)
    return sorted(parts, key=lambda box: (box[1], box[0]))


def compile_theme(key):
    image = Image.new('RGB', (240, 320))
    face = dict(sprites={}, bands=[], lamps=[], digits={}, digit_colors={}, needles=[], hands=[])
    {'equalizer_gold': gold_equalizer, 'classic_chrome': classic_chrome, 'neon_hex': neon_hex}[key](ImageDraw.Draw(image), face)
    for number, box in enumerate(background_parts(image)):
        name = f'background{number}'
        face['sprites'][name] = sprite(image.crop(box))
        face['bands'].append(dict(sprite=name, x=box[0], y=box[1]))
    badge = Image.new('RGB', (21, 10))
    text(ImageDraw.Draw(badge), (10, 5), 'USB', 9, '#71e7f1')
    face['sprites']['usb'] = sprite(badge)
    glyphs(face)
    return face


def main():
    faces = {key + '_v2': compile_theme(key) for key in KEYS}
    payload = base64.b85encode(zlib.compress(json.dumps(faces, separators=(',', ':')).encode('ascii'), 9)).decode('ascii')
    output = Path(__file__).resolve().parents[1] / 'dashboard_extra_assets.py'
    output.write_text(
        '# Generated by artwork/compile_extra_faces.py\nimport base64, json, zlib\n'
        'FACES = json.loads(zlib.decompress(base64.b85decode(\n'
        + ''.join(repr(payload[index:index + 100]) + '\n' for index in range(0, len(payload), 100))
        + ')))\n', encoding='ascii')
    print(output.name, len(payload), 'encoded bytes')


if __name__ == '__main__':
    main()

"""Hinted LCD typography, binary coverage and a tiny original 5 x 7 alphabet."""
from functools import lru_cache

from PIL import Image, ImageDraw, ImageFont

ROWS = {
    '0': ('01110', '10001', '10001', '10001', '10001', '10001', '01110'),
    '1': ('00100', '01100', '00100', '00100', '00100', '00100', '01110'),
    '2': ('01110', '10001', '00001', '00110', '01000', '10000', '11111'),
    '3': ('11110', '00001', '00001', '01110', '00001', '00001', '11110'),
    '4': ('00010', '00110', '01010', '10010', '11111', '00010', '00010'),
    '5': ('11111', '10000', '10000', '11110', '00001', '00001', '11110'),
    '6': ('01110', '10000', '10000', '11110', '10001', '10001', '01110'),
    '7': ('11111', '00001', '00010', '00100', '01000', '01000', '01000'),
    '8': ('01110', '10001', '10001', '01110', '10001', '10001', '01110'),
    '9': ('01110', '10001', '10001', '01111', '00001', '00001', '01110'),
    'C': ('01111', '10000', '10000', '10000', '10000', '10000', '01111'),
    'H': ('10001', '10001', '10001', '11111', '10001', '10001', '10001'),
    'U': ('10001', '10001', '10001', '10001', '10001', '10001', '01110'),
    'S': ('01111', '10000', '10000', '01110', '00001', '00001', '11110'),
    'B': ('11110', '10001', '10001', '11110', '10001', '10001', '11110'),
    '+': ('00000', '00100', '00100', '11111', '00100', '00100', '00000'),
    '-': ('00000', '00000', '00000', '11111', '00000', '00000', '00000'),
    '%': ('11001', '11010', '00010', '00100', '01000', '01011', '10011'),
    ' ': ('00000',) * 7,
}


def mask(value, scale=1):
    """Return a binary mask, with a one-pixel gap at the selected integer scale."""
    width = max(1, (6 * len(value) - 1) * scale)
    image = Image.new('1', (width, 7 * scale))
    draw = ImageDraw.Draw(image)
    for index, character in enumerate(value):
        for y, row in enumerate(ROWS[character]):
            for x, pixel in enumerate(row):
                if pixel == '1':
                    left = (6 * index + x) * scale
                    top = y * scale
                    draw.rectangle((left, top, left + scale - 1, top + scale - 1), fill=1)
    return image


def draw_centered(draw, xy, value, height, color):
    if height < 11:
        image = mask(value)
    else:
        face = fitted_label(value, height)
        left, top, right, bottom = face.getbbox(value)
        image = Image.new('1', (right - left, bottom - top))
        ImageDraw.Draw(image).text((-left, -top), value, font=face, fill=1)
    x, y = xy
    draw.bitmap((round(x - image.width / 2), round(y - image.height / 2)), image, fill=color)


@lru_cache(maxsize=128)
def typeface(size, width=90):
    face = ImageFont.truetype('bahnschrift.ttf', size)
    face.set_variation_by_axes([650, width])
    return face


@lru_cache(maxsize=64)
def fitted_label(value, height):
    for size in range(height * 2, 3, -1):
        face = typeface(size, 100)
        box = face.getbbox(value)
        if box[3] - box[1] <= height:
            return face
    raise ValueError('Label does not fit the native text height')


@lru_cache(maxsize=64)
def numeric_face(width, height):
    for size in range(height * 2, 3, -1):
        face = typeface(size)
        boxes = [face.getbbox(character, anchor='ls') for character in '0123456789+-']
        top = min(box[1] for box in boxes)
        bottom = max(box[3] for box in boxes)
        if bottom - top <= height - 2 and max(box[2] - box[0] for box in boxes) <= width - 2:
            return face, (height - (bottom - top)) // 2 - top
    raise ValueError('Digits do not fit the native text cell')


def cell(character, width, height, color):
    if height < 11:
        glyph = mask(character)
    else:
        face, baseline = numeric_face(width, height)
        # Keep the unit within its cell without shrinking every digit to its width.
        if character == '%':
            size = face.size
            while face.getbbox(character, anchor='ls')[2] > width - 2:
                size -= 1
                face = typeface(size)
        left, _, right, _ = face.getbbox(character, anchor='ls')
        glyph = Image.new('1', (width, height))
        ImageDraw.Draw(glyph).text(((width - (right - left)) // 2 - left, baseline),
                                  character, font=face, anchor='ls', fill=1)
    image = Image.new('RGB', (width, height))
    image.paste(color, ((width - glyph.width) // 2, (height - glyph.height) // 2), glyph)
    return image

"""Validate a prepared GIF and package its existing frames for the native player.

No resizing, palette quantization, frame dropping, timing adjustment or file export.
"""
import struct

from .gif_codec import HEADER, MAGIC, encode_delta, decode_delta

RGB_MAGIC = b'DDFRGB1\0'

GIF_BYTES = 280_000
GIF_MAX_FRAMES = 20
GIF_MIN_MS = 200
GIF_MAX_MS = 1000
GIF_MAX_DURATION = 4000
GIF_HELP = ('GIF préparé : 16 × 16 à 128 × 160 px, largeur paire. Couleurs : écran RGB565.\n'
            'Moins de 280 Ko · 2 à 20 images · 5 images/s max. · 4 s max.')
GIF_WARNING = 'Attention : les GIF peuvent faire planter ou figer la radio, même conformes.'
GIF_RECOVERY = 'Si la radio se fige, réinstalle une version avec le démarrage d’origine.'
GIF_TIMING = 'Chaque image du GIF doit durer entre 200 et 1 000 ms (5 images/s maximum).'
GIF_SIZE = 'Le GIF et ses données intégrées doivent faire moins de 280 Ko (280 000 octets).'
GIF_COUNT = 'Le GIF doit contenir 2 à 20 images et durer 4 secondes maximum.'
GIF_DIMENSIONS = 'Prépare un GIF de 16 × 16 à 128 × 160 pixels, avec une largeur paire. Aucun redimensionnement automatique.'


def prepared_asset(image):
    from PIL import Image
    width, height = image.size
    if not (16 <= width <= 128 and width % 2 == 0 and 16 <= height <= 160):
        raise ValueError(GIF_DIMENSIONS)
    frames = []
    durations = []
    colors = set()
    direct = False
    for index in range(GIF_MAX_FRAMES + 1):
        try:
            image.seek(index)
        except EOFError:
            break
        if index == GIF_MAX_FRAMES:
            raise ValueError(GIF_COUNT)
        if image.size != (width, height):
            raise ValueError(GIF_DIMENSIONS)
        duration = image.info.get('duration')
        if type(duration) is not int or not GIF_MIN_MS <= duration <= GIF_MAX_MS:
            raise ValueError(GIF_TIMING)
        durations.append(duration)
        if sum(durations) > GIF_MAX_DURATION:
            raise ValueError(GIF_COUNT)
        # GIF disposal is resolved by Pillow. Transparent pixels display on black.
        frame = Image.new('RGBA', image.size, (0, 0, 0, 255))
        frame.alpha_composite(image.convert('RGBA'))
        frame = frame.convert('RGB')
        if not direct:
            used = frame.getcolors(16)
            if used is None:
                # Stop collecting once we know the compact legacy format cannot
                # preserve the colors. RGB565 has no indexed-palette restriction.
                direct = True
            else:
                colors.update(color for _, color in used)
                direct = len(colors) > 16
        frames.append(frame.tobytes())
    if len(frames) < 2:
        raise ValueError(GIF_COUNT)
    palette = [] if direct else sorted(colors)
    lookup = {color: index for index, color in enumerate(palette)}
    rgb565 = b''.join(struct.pack('<H', (r >> 3) << 11 | (g >> 2) << 5 | b >> 3)
                      for r, g, b in palette).ljust(32, b'\0')
    frame_bytes = width * height * 2 if direct else width * height // 2
    result = bytearray(HEADER.pack(RGB_MAGIC if direct else MAGIC, width, height,
                                  len(frames), 0 if direct else 16, frame_bytes) + rgb565)
    previous = bytes(frame_bytes)
    for frame, duration in zip(frames, durations):
        if direct:
            packed = b''.join(struct.pack('<H', (r >> 3) << 11 | (g >> 2) << 5 | b >> 3)
                              for r, g, b in zip(frame[::3], frame[1::3], frame[2::3]))
        else:
            indices = [lookup[color] for color in zip(frame[::3], frame[1::3], frame[2::3])]
            packed = bytes(high << 4 | low for high, low in zip(indices[::2], indices[1::2]))
        delta = encode_delta(previous, packed)
        if decode_delta(previous, delta) != packed:
            raise ValueError('Échec de vérification du GIF intégré.')
        result += struct.pack('<HI', duration, len(delta)) + delta
        previous = packed
    if len(result) >= GIF_BYTES:
        raise ValueError(GIF_SIZE)
    return bytes(result)


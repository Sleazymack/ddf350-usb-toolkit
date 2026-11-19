"""Native animation packing primitives. No image processing or command line."""
import struct

MAGIC = b'DDFANM1\0'
HEADER = struct.Struct('<8sHHHHI')


def encode_delta(before, after):
    if len(before) != len(after) or len(after) > 65534:
        raise ValueError('Invalid frame length')
    result = bytearray()
    position = 0
    cursor = 0
    while position < len(after):
        while position < len(after) and before[position] == after[position]:
            position += 1
        if position == len(after):
            break
        start = position
        last = position + 1
        position += 1
        while position < len(after):
            if before[position] != after[position]:
                last = position + 1
            if position - last >= 4:
                break
            position += 1
        result += struct.pack('<HH', start - cursor, last - start) + after[start:last]
        cursor = last
        position = last
    result += struct.pack('<HH', 65535, 0)
    return bytes(result)


def decode_delta(before, payload):
    result = bytearray(before)
    position = 0
    offset = 0
    while True:
        if offset + 4 > len(payload):
            raise ValueError('Truncated delta')
        skip, count = struct.unpack_from('<HH', payload, offset)
        offset += 4
        if skip == 65535 and count == 0:
            if offset != len(payload):
                raise ValueError('Trailing delta bytes')
            return bytes(result)
        position += skip
        if not count or position + count > len(result) or offset + count > len(payload):
            raise ValueError('Invalid delta bounds')
        result[position:position + count] = payload[offset:offset + count]
        position += count
        offset += count


"""Export our own ARM ELF32 code and ABI metadata, without any vendor image.

Usage: python startup/export_player.py player.elf player.bin startup_player_blob.py
Build with Zig 0.13.0; see docs/startup-animation.md.
"""
import hashlib
import json
from pathlib import Path
import struct
import sys


def export(elf_path, binary_path, output_path, variant='standard'):
    if variant not in ('standard','simple-loop'):raise ValueError('Unknown player variant')
    elf=Path(elf_path).read_bytes();code=Path(binary_path).read_bytes()
    if elf[:7]!=b'\x7fELF\x01\x01\x01':raise ValueError('Expected little-endian ELF32')
    shoff=struct.unpack_from('<I',elf,32)[0]
    entsize,count=struct.unpack_from('<HH',elf,46)
    sections=[struct.unpack_from('<10I',elf,shoff+i*entsize) for i in range(count)]
    symbols={}
    for section in sections:
        if section[1]!=2:continue
        names=sections[section[6]];strings=elf[names[4]:names[4]+names[5]]
        for pos in range(section[4],section[4]+section[5],section[9]):
            name,address,size,info,other,index=struct.unpack_from('<IIIBBH',elf,pos)
            name=strings[name:].split(b'\0')[0].decode('ascii')
            if index and name and not name.startswith('$') and address>=0x080a8000:
                symbols[name]={'address':address,'size':size}
    base=0x080a8000
    def words(name):
        item=symbols[name];offset=(item['address']&~1)-base
        return list(struct.unpack_from('<'+'I'*(item['size']//4),code,offset))
    root=Path(__file__).parent
    data={'base':base,'sha256':hashlib.sha256(code).hexdigest(),'code_hex':code.hex(),
          'symbols':symbols,'context_size':words('boot_context_size')[0],
          'context_offsets':dict(zip(('active','dead','root','image','timer','decoder','pixels','frame','next','descriptor','sw','sh'),words('boot_context_offsets'))),
          'c_sha256':hashlib.sha256((root/'player.c').read_bytes()).hexdigest(),
          'linker_sha256':hashlib.sha256((root/'player.ld').read_bytes()).hexdigest(),
          'compiler':'Zig 0.13.0 cc thumb-freestanding-eabi cortex_m3 -Oz'}
    if variant=='simple-loop':data['compiler']+=' -DDDF_SIMPLE_LOOP'
    Path(output_path).write_text('"""Generated original player code; rebuild instructions in docs/startup-animation.md."""\nimport json\nDATA = json.loads('+repr(json.dumps(data,sort_keys=True,separators=(',',':')))+')\nCODE = bytes.fromhex(DATA["code_hex"])\n',encoding='utf-8')
    print(json.dumps({k:v for k,v in data.items() if k not in ('code_hex','symbols')},indent=2))


if __name__=='__main__':export(*sys.argv[1:])

#!/usr/bin/env python3
"""Builds touchcal.nds with zig cc (pip install ziglang) - no devkitPro needed."""
import os, struct, subprocess, sys
from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, 'build'); os.makedirs(OUT, exist_ok=True)
ZIG = [sys.executable, '-m', 'ziglang']

def font_h():
    f = ImageFont.load_default()
    W, H = 6, 10
    rows = []
    for c in range(32, 128):
        im = Image.new('1', (8, 12), 0)
        ImageDraw.Draw(im).text((0, 0), chr(c), font=f, fill=1)
        g = []
        for y in range(1, 11):
            v = 0
            for x in range(W):
                if im.getpixel((x, y)):
                    v |= 0x80 >> x
            g.append(v)
        rows.append(g)
    with open(os.path.join(OUT, 'font.h'), 'w') as fh:
        fh.write(f'#define FONT_W {W}\n#define FONT_H {H}\nstatic const unsigned char font[96][{H}] = {{\n')
        for g in rows:
            fh.write('  {' + ','.join(f'0x{v:02x}' for v in g) + '},\n')
        fh.write('};\n')

def cc(cpu, src, obj):
    subprocess.check_call(ZIG + ['cc', '-target', 'arm-freestanding-eabi', f'-mcpu={cpu}', '-marm',
                                 '-O2', '-ffreestanding', '-fno-builtin', '-nostdlib', '-I', OUT,
                                 '-I', os.path.join(HERE, 'src'), '-c', src, '-o', obj])

def link(objs, ld, elf):
    subprocess.check_call(ZIG + ['cc', '-target', 'arm-freestanding-eabi', '-nostdlib', '-static',
                                 '-Wl,-T,' + ld, '-Wl,--no-gc-sections'] + objs + ['-o', elf])

def binary(elf, out):
    subprocess.check_call(ZIG + ['objcopy', '-O', 'binary', elf, out])
    return open(out, 'rb').read()

def crc16(d, c=0xFFFF):
    for b in d:
        c ^= b
        for _ in range(8):
            c = (c >> 1) ^ 0xA001 if c & 1 else c >> 1
    return c

def main():
    font_h()
    cc('arm946e_s', os.path.join(HERE, 'src', 'arm9.c'), os.path.join(OUT, 'arm9.o'))
    cc('arm7tdmi', os.path.join(HERE, 'src', 'arm7.c'), os.path.join(OUT, 'arm7.o'))
    link([os.path.join(OUT, 'arm9.o')], os.path.join(HERE, 'link9.ld'), os.path.join(OUT, 'arm9.elf'))
    link([os.path.join(OUT, 'arm7.o')], os.path.join(HERE, 'link7.ld'), os.path.join(OUT, 'arm7.elf'))
    a9 = binary(os.path.join(OUT, 'arm9.elf'), os.path.join(OUT, 'arm9.bin'))
    a7 = binary(os.path.join(OUT, 'arm7.elf'), os.path.join(OUT, 'arm7.bin'))
    al = lambda n: (n + 0x1FF) & ~0x1FF
    a9off = 0x200; a7off = al(a9off + len(a9)); end = al(a7off + len(a7))
    rom = bytearray(end)
    rom[a9off:a9off + len(a9)] = a9; rom[a7off:a7off + len(a7)] = a7
    h = bytearray(0x200)
    h[0:12] = b'TOUCHCALTEST'; h[0x0C:0x10] = b'TCAL'; h[0x10:0x12] = b'00'
    h[0x14] = 0  # capacity 128KB
    struct.pack_into('<4I', h, 0x20, a9off, 0x02000000, 0x02000000, len(a9))
    struct.pack_into('<4I', h, 0x30, a7off, 0x037F8000, 0x037F8000, len(a7))
    struct.pack_into('<II', h, 0x60, 0x00586000, 0x001808F8)
    struct.pack_into('<H', h, 0x6E, 0x051E)
    struct.pack_into('<II', h, 0x80, end, 0x200)
    struct.pack_into('<H', h, 0x15E, crc16(h[:0x15E]))
    rom[0:0x200] = h
    out = os.path.join(HERE, 'touchcal.nds')
    open(out, 'wb').write(rom)
    print(f'{out}: ARM9 {len(a9):#x} bytes, ARM7 {len(a7):#x} bytes, total {len(rom):#x}')

if __name__ == '__main__':
    main()

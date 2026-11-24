#!/usr/bin/env python3
"""
NVRAM-Emu ROM patcher
=====================

Patches DS ROMs (.nds) so they do not freeze on consoles with a dead NVRAM.

Nintendo SDK games include their own ARM7 NVRAM driver and wait forever for
the chip to become ready. This tool finds that driver in the ARM7 binary and
replaces it with the same RAM-backed emulator used for the DS launcher.

Use the patched ROMs with TWiLight Menu++ / nds-bootstrap.

    python3 nvramemu_rompatch.py game.nds              -> game.nvramemu.nds
    python3 nvramemu_rompatch.py game.nds -o out.nds
    python3 nvramemu_rompatch.py --inplace roms/*.nds

Requires: keystone-engine, capstone   (pip install keystone-engine capstone)
"""
import argparse, glob, os, struct, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import romemu  # noqa: E402

VERSION = "1.2.0"


def patch_rom(path, out_path):
    rom = bytearray(open(path, 'rb').read())
    title = rom[0:12].rstrip(b'\0').decode('ascii', 'replace')
    code = rom[0x0C:0x10].decode('ascii', 'replace')
    off, entry, ram, size = struct.unpack_from('<4I', rom, 0x30)
    if off == 0 or off + size > len(rom):
        print(f'  [{code}] {title}: invalid ARM7 header, skipped')
        return False
    arm7 = bytes(rom[off:off + size])
    new, info = romemu.patch_arm7(arm7, ram)
    new, waits = romemu.neutralise_wifi_waits(new or arm7, ram)
    if info is None and not waits:
        print(f'  [{code}] {title}: nothing to patch (already patched or not needed)')
        return False
    rom[off:off + size] = new
    open(out_path, 'wb').write(rom)
    if info:
        entries, lo, hi = info
        print(f'  [{code}] {title}: NVRAM driver {lo:#x}-{hi:#x} emulated ({len(entries)} functions)')
    if waits:
        print(f'  [{code}] {title}: {len(waits)} DS Wi-Fi busy-wait(s) neutralised')
    print(f'        -> {out_path}')
    return True


def main():
    ap = argparse.ArgumentParser(description=f'NVRAM-Emu ROM patcher v{VERSION}')
    ap.add_argument('roms', nargs='+', help='.nds files (wildcards allowed)')
    ap.add_argument('-o', '--out', help='output file (single ROM only)')
    ap.add_argument('--inplace', action='store_true', help='overwrite the input ROMs')
    a = ap.parse_args()
    files = [f for p in a.roms for f in (glob.glob(p) or [p])]
    if a.out and len(files) != 1:
        ap.error('-o can only be used with a single ROM')
    print(f'NVRAM-Emu ROM patcher v{VERSION}')
    ok = 0
    for f in files:
        if a.out:
            out = a.out
        elif a.inplace:
            out = f
        else:
            root, ext = os.path.splitext(f)
            out = root + '.nvramemu' + (ext or '.nds')
        ok += patch_rom(f, out)
    print(f'{ok}/{len(files)} ROM(s) patched')


if __name__ == '__main__':
    main()

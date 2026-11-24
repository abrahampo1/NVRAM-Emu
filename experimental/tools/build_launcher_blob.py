#!/usr/bin/env python3
"""
Rebuilds the launcher payload embedded in patcher/nvramemu_patcher.py.

Input : decrypted ARM7i of the HNAA launcher (RAM 0x2300000), e.g. extracted
        with --dump-arm7i from nvramemu_patcher.py
Output: prints the zlib+base64 blob of the NVRAM driver region (emulator +
        game hook) and the hook-site instruction.

Requires keystone-engine and capstone.
"""
import base64, hashlib, struct, sys, zlib, os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
import romemu, launcherhook  # noqa: E402

RAM = 0x2300000
d = open(sys.argv[1], 'rb').read()
entries, lo, hi = romemu.find_driver(d, RAM)
assert len(entries) == 14, entries
region, A = launcherhook.build_launcher_region(d, RAM, entries, lo, hi)
hook, tmpl = A['HK'], A['T']
site = launcherhook.HOOK_SITE
assert struct.unpack_from('<I', d, site - RAM)[0] == launcherhook.HOOK_SITE_ORIG
call = romemu.asm(f'bl {hook:#x}', site)
print(f'EMU_LO, EMU_HI = {lo:#x}, {hi:#x}')
print(f'EMU_REGION_ORIG_SHA256 = "{hashlib.sha256(d[lo-RAM:hi-RAM]).hexdigest()}"')
print(f'HOOK_SITE, HOOK_SITE_ORIG, HOOK_SITE_NEW = {site:#x}, {launcherhook.HOOK_SITE_ORIG:#010x}, {struct.unpack("<I", call)[0]:#010x}')
print(f'# hook entry {hook:#x}, reader template {tmpl:#x}')
print('EMU_BLOB = (')
b = base64.b64encode(zlib.compress(region, 9)).decode()
for i in range(0, len(b), 100):
    print(f'    "{b[i:i+100]}"')
print(')')

"""
Generic NVRAM emulator injector for NitroSDK/TwlSDK ARM7 binaries.

Nintendo SDK games carry their own ARM7 NVRAM (SPI flash) driver. Before every
access the SDK waits on the status register (RDSR) until WIP==0; on a console
whose NVRAM is dead the status reads 0xFF forever and the game freezes.

This module finds that driver inside an ARM7 binary (by its SPI command
functions) and replaces it with a position-independent, RAM-backed emulator
(same behaviour as the one injected in the DS launcher).
"""
import struct
from keystone import Ks, KS_ARCH_ARM, KS_MODE_ARM
from capstone import Cs, CS_ARCH_ARM, CS_MODE_ARM

_ks = Ks(KS_ARCH_ARM, KS_MODE_ARM)
_md = Cs(CS_ARCH_ARM, CS_MODE_ARM)

CMDS = {0x03: 'READ', 0x0B: 'FREAD', 0x0A: 'PW', 0x02: 'PP', 0xDB: 'PE', 0xD8: 'SE',
        0x05: 'RDSR', 0x9F: 'RDID', 0x06: 'WREN', 0x04: 'WRDI', 0xB9: 'DP', 0xAB: 'RDP',
        0xC7: 'CE', 0xFF: 'FF'}


def asm(code, addr):
    enc, _ = _ks.asm(code, addr)
    return bytes(enc)


def crc16(data, init):
    c = init
    for b in data:
        c ^= b
        for _ in range(8):
            c = (c >> 1) ^ 0xA001 if c & 1 else c >> 1
    return c


def user_settings(lang=5):
    u = bytearray(0x100)
    struct.pack_into('<H', u, 0x00, 5)
    u[0x03] = 1; u[0x04] = 1
    nick = 'USER'
    u[0x06:0x06 + 2 * len(nick)] = nick.encode('utf-16le')
    struct.pack_into('<H', u, 0x1A, len(nick))
    struct.pack_into('<HHBBHHBB', u, 0x58, 0x20 * 16, 0x20 * 16, 0x20, 0x20, 0xE0 * 16, 0xA0 * 16, 0xE0, 0xA0)
    struct.pack_into('<H', u, 0x64, 0xFC00 | 0x30 | (lang & 7))
    u[0x66] = 0x18
    struct.pack_into('<H', u, 0x70, 1)
    struct.pack_into('<H', u, 0x72, crc16(u[0:0x70], 0xFFFF))
    u[0x74] = 1; u[0x75] = lang
    struct.pack_into('<H', u, 0x76, 0x3E)
    for i in range(0x80, 0xFE):
        u[i] = 0xFF
    struct.pack_into('<H', u, 0xFE, crc16(u[0x74:0xFE], 0xFFFF))
    return bytes(u)


def header():
    h = bytearray(0x40)
    h[0x1D] = 0x57
    h[0x1E] = h[0x1F] = 0xFF
    struct.pack_into('<H', h, 0x20, 0x1FE00 // 8)
    struct.pack_into('<H', h, 0x2C, 0x138)
    h[0x2F] = 5
    h[0x36:0x3C] = bytes([0x00, 0x09, 0xBF, 0x12, 0x34, 0x56])
    struct.pack_into('<H', h, 0x3C, 0x3FFE)
    h[0x3E] = h[0x3F] = 0xFF
    wifi = bytes(h[0x2C:0x40]) + b'\xFF' * (0x138 - (0x40 - 0x2C))
    struct.pack_into('<H', h, 0x2A, crc16(wifi, 0x0000))
    return bytes(h)


# ---------------------------------------------------------------------------
# Driver detection
# ---------------------------------------------------------------------------
def _ins(d, base, a):
    o = a - base
    if o < 0 or o + 4 > len(d):
        return None
    return next(_md.disasm(d[o:o + 4], a), None)


def find_driver(d, base):
    """Return (entries{name: addr}, lo, hi) or None.

    Same algorithm as the on-console scanner (launcher hook):
    * a function entry is the first AL-condition word after a terminator
      (``bx lr`` or ``pop {..., pc}``), skipping literal words;
    * a function is classified by its first NVRAM chip-select
      (``mov rX, #0x8900`` / ``#0x8100``) followed within 4 words by
      ``mov rY, #cmd`` with an SPI flash command byte.
    """
    entries, ends = {}, {}
    pending, cur, classified = False, None, False
    n = len(d) // 4
    words = struct.unpack_from('<%dI' % n, d, 0)
    for k, w in enumerate(words):
        if w == 0xE12FFF1E or (w >> 15) == (0xE8BD8000 >> 15):
            if cur is not None and cur not in ends:
                ends[cur] = base + 4 * k
            pending = True
            continue
        if pending:
            if (w >> 28) != 0xE:
                continue
            cur, pending, classified = base + 4 * k, False, False
        if classified or cur is None:
            continue
        if (w & ~0xF000) in (0xE3A00C89, 0xE3A00C81):
            for j in range(1, 5):
                if k + j >= n:
                    break
                v = words[k + j]
                if (v & ~0xF0FF) == 0xE3A00000 and (v & 0xFF) in CMDS:
                    name = CMDS[v & 0xFF]
                    if name not in entries:
                        entries[name] = cur
                    classified = True
                    break
    if not {'READ', 'RDSR'} <= set(entries):
        return None
    lo = min(entries.values())
    hi = max(ends.get(e, e + 4) for e in entries.values())
    while struct.unpack_from('<I', d, hi - base + 4)[0] >> 28 != 0xE:  # literal pool
        hi += 4
    hi += 4
    return entries, lo, hi


# ---------------------------------------------------------------------------
# Emulator layout (position independent)
# ---------------------------------------------------------------------------
def build_patch(d, base, entries, lo, hi, extra=None):
    region = bytearray(hi - lo)
    used = bytearray(hi - lo)

    def put(addr, data):
        o = addr - lo
        assert 0 <= o and o + len(data) <= len(region), (hex(addr), len(data))
        region[o:o + len(data)] = data
        for k in range(o, o + len(data)):
            used[k] = 1

    stub_len = {'RDSR': 12, 'RDID': 20}
    for name, a in entries.items():
        used[a - lo:a - lo + stub_len.get(name, 4)] = b'\x01' * stub_len.get(name, 4)

    def alloc(size, align=4):
        run = 0
        for o in range(0, len(region)):
            if used[o]:
                run = 0; continue
            if run == 0:
                start = o
                if (lo + start) % align:
                    continue
            run += 1
            if run == size:
                for k in range(start, start + size):
                    used[k] = 1
                return lo + start
        raise RuntimeError(f'no space for {size:#x} bytes in driver region')

    US = alloc(0x100); put(US, user_settings())
    HDR = alloc(0x40); put(HDR, header())

    # map(r0=addr) -> r0=ptr or 0 ; clobbers r1, r2
    _map_src = f'''
        ldr r1, k_mask
        and r0, r0, r1
        cmp r0, #0x40
        bhs m1
        ldr r1, k_hdr
    lh: add r1, pc, r1
        add r0, r1, r0
        bx lr
    m1: ldr r1, k_us0
        subs r0, r0, r1
        movlo r0, #0
        bxlo lr
        and r0, r0, #0xff
        ldr r1, k_us
    lu: add r1, pc, r1
        add r0, r1, r0
        bx lr
    k_mask: .word 0x1ffff
    k_hdr:  .word 0
    k_us0:  .word 0x1fe00
    k_us:   .word 0
    '''
    MAP = alloc(len(asm(_map_src, lo)))
    m = bytearray(asm(_map_src, MAP))
    # patch PC-relative offsets: literal k_hdr at +0x3c? compute from disassembly
    ins = list(_md.disasm(bytes(m), MAP))
    lh = next(i.address for i in ins if i.mnemonic == 'add' and i.op_str == 'r1, pc, r1')
    lu = [i.address for i in ins if i.mnemonic == 'add' and i.op_str == 'r1, pc, r1'][1]
    size_code = (len(m) - 16)
    k_hdr_off, k_us_off = size_code + 4, size_code + 12
    struct.pack_into('<i', m, k_hdr_off, HDR - (lh + 8))
    struct.pack_into('<i', m, k_us_off, US - (lu + 8))
    put(MAP, bytes(m))

    _rd = lambda RD: asm(f'''
        push {{r4, r5, r6, lr}}
        mov r4, r0
        mov r5, r1
        mov r6, r2
    r1l: cmp r5, #0
        beq r2l
        mov r0, r4
        bl {MAP:#x}
        cmp r0, #0
        ldrbne r0, [r0]
        moveq r0, #0xff
        strb r0, [r6], #1
        add r4, r4, #1
        sub r5, r5, #1
        b r1l
    r2l: pop {{r4, r5, r6, lr}}
        bx lr
    ''', RD)
    RD = alloc(len(_rd(lo))); put(RD, _rd(RD))
    _wr = lambda WR: asm(f'''
        push {{r4, r5, r6, lr}}
        cmp r1, #0
        beq wd
        add r3, r0, r1
        sub r3, r3, #1
        lsr r3, r3, #8
        cmp r3, r0, lsr #8
        andhi r3, r0, #0xff
        rsbhi r1, r3, #0x100
        mov r4, r0
        mov r5, r1
        mov r6, r2
    wl: cmp r5, #0
        beq wd
        mov r0, r4
        bl {MAP:#x}
        cmp r0, #0
        ldrbne r1, [r6]
        strbne r1, [r0]
        add r6, r6, #1
        add r4, r4, #1
        sub r5, r5, #1
        b wl
    wd: pop {{r4, r5, r6, lr}}
        bx lr
    ''', WR)
    WR = alloc(len(_wr(lo))); put(WR, _wr(WR))

    def eraser(clear, count):
        src = lambda a: asm(f'''
        push {{r4, r5, lr}}
        {clear}
        ldr r5, kc
    el: mov r0, r4
        bl {MAP:#x}
        cmp r0, #0
        movne r1, #0xff
        strbne r1, [r0]
        add r4, r4, #1
        subs r5, r5, #1
        bne el
        pop {{r4, r5, lr}}
        bx lr
    kc: .word {count:#x}
        ''', a)
        a = alloc(len(src(lo)))
        put(a, src(a))
        return a
    EP = eraser('bic r4, r0, #0xff', 0x100)
    ES = eraser('bic r4, r0, #0xff00\n        bic r4, r4, #0xff', 0x10000)

    extra_info = extra(alloc, put) if extra else None
    route = {'READ': RD, 'FREAD': RD, 'PW': WR, 'PP': WR, 'PE': EP, 'SE': ES}
    for name, a in entries.items():
        o = a - lo
        if name == 'RDSR':
            code = asm('mov r1, #0; strb r1, [r0]; bx lr', a)
        elif name == 'RDID':
            code = asm('mov r1, #0x20; strb r1, [r0]; mov r1, #0x40; strb r1, [r0, #1]; bx lr', a)
        elif name in route:
            code = asm(f'b {route[name]:#x}', a)
        else:
            code = asm('bx lr', a)
        region[o:o + len(code)] = code
    if extra:
        return bytes(region), extra_info
    return bytes(region)


def patch_arm7(d, base):
    found = find_driver(d, base)
    if not found:
        return None, None
    entries, lo, hi = found
    region = build_patch(d, base, entries, lo, hi)
    out = bytearray(d)
    out[lo - base:hi - base] = region
    return bytes(out), (entries, lo, hi)


def neutralise_wifi_waits(d, base):
    """Python twin of launcherhook._wifi_src/_wcheck_src. Returns (new_bytes, [addrs])."""
    out = bytearray(d)
    n = len(d) // 4
    w = list(struct.unpack_from('<%dI' % n, d, 0))
    hits = []
    for k in range(n):
        x = w[k]
        if (x & 0x0F000000) != 0x0A000000 or (x >> 28) >= 0xE:
            continue
        off = ((x << 8) & 0xFFFFFFFF)
        off = (off - (1 << 32) if off & 0x80000000 else off) >> 6
        t = k * 4 + 8 + off
        if t >= k * 4 or k * 4 - t > 0x28 or t < 0:
            continue
        reg, ok = None, True
        for j in range(t // 4, k):
            y = w[j]
            if not (y & 0x0C000000) and (y & 0x01E00000) in (0x00400000, 0x00800000):
                ok = False; break
            if (y & 0x0F5000F0) == 0x015000B0 and reg is None:
                reg = (y >> 16) & 0xF
        if not ok or reg is None:
            continue
        for j in range(t // 4 - 1, t // 4 - 17, -1):
            if j < 0:
                break
            y = w[j]
            if (y & 0x0F7F0000) == 0x051F0000 and ((y >> 12) & 0xF) == reg:
                imm = y & 0xFFF
                la = j * 4 + 8 + (imm if y & 0x00800000 else -imm)
                if 0 <= la <= len(d) - 4 and (struct.unpack_from('<I', d, la)[0] >> 16) == 0x0480:
                    struct.pack_into('<I', out, k * 4, 0xE1A00000)
                    hits.append(base + k * 4)
                break
    return bytes(out), hits

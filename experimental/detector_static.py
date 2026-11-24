"""
Diagnostic "beep detector", game-specific variant.

The instrumentation for one game is computed offline (Python) from its ARM7
binary and stored in the launcher as a list of memory blocks. At boot the
launcher hook checks the game code and a few verification words, then copies
the blocks into the freshly loaded ARM7 binary.

Categories (number of beeps, repeated):
  1 = cartridge save SPI (AUXSPICNT 0x040001A0..A3)
  2 = cartridge ROM bus  (0x040001A4..AF, 0x04100010)
  3 = IPC / FIFO          (0x04000180..8F, 0x04100000)
  4 = other I/O
  5 = DS Wi-Fi            (0x0480xxxx)
"""
import struct, hashlib
import romemu as R
from romemu import asm
import launcherhook as LH
import detector as D

LIMIT = 0x02000000


def category(v):
    if 0x04000180 <= v < 0x04000190 or v == 0x04100000:
        return 3
    if 0x040001A0 <= v < 0x040001A4:
        return 1
    if 0x040001A4 <= v < 0x040001B0 or v == 0x04100010:
        return 2
    if 0x040001C0 <= v < 0x040001C4:
        return 0
    if (v >> 16) == 0x0480:
        return 5
    if (v >> 24) == 4:
        return 4
    return 0


def find_wait_loops(d, base):
    n = len(d) // 4
    w = struct.unpack_from('<%dI' % n, d, 0)
    out = []
    for k in range(n):
        x = w[k]
        if (x & 0x0F000000) != 0x0A000000 or (x >> 28) >= 0xE:
            continue
        off = (x << 8) & 0xFFFFFFFF
        off = (off - (1 << 32) if off & 0x80000000 else off) >> 6
        t = k * 4 + 8 + off
        if t >= k * 4 or k * 4 - t > 0x18 or t < 0:
            continue
        reg, ok = None, True
        for j in range(t // 4, k):
            y = w[j]
            if not (y & 0x0C000000) and (y & 0x01E00000) in (0x00400000, 0x00800000):
                ok = False; break
            if ((y & 0x0F5000F0) == 0x015000B0 or (y & 0x0F500000) == 0x05100000) and reg is None:
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
                if 0 <= la <= len(d) - 4:
                    v = struct.unpack_from('<I', d, la)[0]
                    c = category(v)
                    if c:
                        out.append((base + k * 4, base + t, c, v))
                break
    return out


def b_enc(cond_bits, src, dst):
    return cond_bits | (((dst - (src + 8)) >> 2) & 0xFFFFFF)


def instrument(d, base):
    """Returns (blocks [(addr, bytes)], verify [(addr, word)], report)."""
    entries, lo, hi = R.find_driver(d, base)
    # free space: bodies of NVRAM write functions (entry stubbed with bx lr)
    free = []
    blocks = []
    for name in ('PP', 'PW', 'PE', 'SE'):
        e = entries[name]
        a = e
        while struct.unpack_from('<I', d, a - base)[0] != 0xE12FFF1E:
            a += 4
        free.append([e + 4, a])
        blocks.append((e, struct.pack('<I', 0xE12FFF1E)))

    def alloc(n):
        for r in free:
            if r[1] - r[0] >= n:
                a = r[0]; r[0] += n
                return a
        raise RuntimeError('no game space')
    beep = D.beep_template()
    BEEP = alloc(len(beep))
    blocks.append((BEEP, beep))
    loops = find_wait_loops(d, base)
    tt = D.tramp_template()
    placed = []
    for br, top, cat, v in loops:
        try:
            T = alloc(len(tt))
        except RuntimeError:
            break
        t = bytearray(tt)
        struct.pack_into('<I', t, 0x1C, b_enc(0x3A000000, T + 0x1C, top))
        struct.pack_into('<I', t, 0x20, 0xE3A00000 | cat)
        struct.pack_into('<I', t, 0x24, b_enc(0xEA000000, T + 0x24, BEEP))
        blocks.append((T, bytes(t)))
        orig = struct.unpack_from('<I', d, br - base)[0]
        blocks.append((br, struct.pack('<I', b_enc(orig & 0xFF000000, br, T))))
        placed.append((br, top, cat, v, T))
    # verification words: the original branch words + entries
    verify = [(br, struct.unpack_from('<I', d, br - base)[0]) for br, *_ in placed[:1]]
    verify.append((entries['READ'], struct.unpack_from('<I', d, entries['READ'] - base)[0]))
    return blocks, verify, placed, loops


def merge_blocks(blocks, maxlen=0x34):
    """Merge contiguous blocks, then split into chunks that fit small free spans."""
    blocks = sorted(blocks)
    out = []
    for a, b in blocks:
        if out and out[-1][0] + len(out[-1][1]) == a:
            out[-1] = (out[-1][0], out[-1][1] + b)
        else:
            out.append((a, b))
    res = []
    for a, b in out:
        for i in range(0, len(b), maxlen):
            res.append((a + i, b[i:i + maxlen]))
    return res


def _applier_src(at, LIST, gamecode, verify):
    vchk = ''
    lits = ''
    for i, (a, w) in enumerate(verify):
        vchk += f'''
        ldr r2, va{i}
        ldr r0, [r2]
        ldr r1, vv{i}
        cmp r0, r1
        bne a_done'''
        lits += f'''
    va{i}: .word {a:#x}
    vv{i}: .word {w:#x}'''
    return asm(f'''
        push {{r4, r5, r6, r7, lr}}
        ldr r0, [r9, #0xc]
        ldr r1, k_code
        cmp r0, r1
        bne a_done{vchk}
        ldr r4, k_list
    a_loop:
        ldr r5, [r4], #4
        cmp r5, #0
        beq a_done
        ldr r6, [r5], #4
        ldr r7, [r5], #4
    a_cp:
        ldr r0, [r5], #4
        str r0, [r6], #4
        subs r7, r7, #1
        bne a_cp
        b a_loop
    a_done:
        pop {{r4, r5, r6, r7, lr}}
        mov r0, #0
        bx lr
    k_code: .word {struct.unpack('<I', gamecode)[0]:#x}
    k_list: .word {LIST:#x}{lits}
    ''', at)


def build_region(a7i, ram, entries, lo, hi, game_arm7, game_base, gamecode):
    blocks, verify, placed, loops = instrument(game_arm7, game_base)
    blocks = merge_blocks(blocks)
    region = bytearray(hi - lo)
    used = bytearray(hi - lo)
    stub_len = {'RDSR': 12, 'RDID': 20}
    for name, a in entries.items():
        n = stub_len.get(name, 4)
        used[a - lo:a - lo + n] = b'\x01' * n
    srcs = {
        'US':  lambda A: R.user_settings(),
        'HDR': lambda A: R.header(),
        'MAP': lambda A: LH._map_src(A),
        'RD':  lambda A: R.asm(LH._RD_ASM.format(MAP=A['MAP']), A['RD']),
        'WR':  lambda A: R.asm(LH._WR_ASM.format(MAP=A['MAP']), A['WR']),
        'AP':  lambda A: _applier_src(A['AP'], A['LIST'], gamecode, verify),
        'LIST': lambda A: b''.join(struct.pack('<I', A[f'B{i}']) for i in range(len(blocks))) + b'\0\0\0\0',
    }
    for i, (a, b) in enumerate(blocks):
        srcs[f'B{i}'] = (lambda a, b: (lambda A: struct.pack('<II', a, len(b) // 4) + b))(a, b)
    P = lo
    dummy = {k: P for k in srcs}
    sizes = {k: len(f(dummy)) for k, f in srcs.items()}
    spans, o = [], 0
    while o < len(used):
        if used[o] or (lo + o) % 4:
            o += 1; continue
        st = o
        while o < len(used) and not used[o]:
            o += 1
        spans.append([lo + st, o - st])
    names = sorted(sizes, key=lambda k: -sizes[k])
    assign = {}

    def rec(i):
        if i == len(names):
            return True
        n, tried = names[i], set()
        for sp in spans:
            if sp[1] >= sizes[n] and sp[1] not in tried:
                tried.add(sp[1])
                assign[n] = sp[0]; sp[0] += sizes[n]; sp[1] -= sizes[n]
                if rec(i + 1):
                    return True
                sp[0] -= sizes[n]; sp[1] += sizes[n]; del assign[n]
        return False
    if not rec(0):
        raise RuntimeError('static detector: does not fit ' + str({k: hex(v) for k, v in sizes.items()}))
    A = dict(assign)
    for k, f in srcs.items():
        b = f(A)
        region[A[k] - lo:A[k] - lo + len(b)] = b
    route = {'READ': A['RD'], 'FREAD': A['RD'], 'PW': A['WR'], 'PP': A['WR']}
    for name, a in entries.items():
        if name == 'RDSR':
            code = R.asm('mov r1, #0; strb r1, [r0]; bx lr', a)
        elif name == 'RDID':
            code = R.asm('mov r1, #0x20; strb r1, [r0]; mov r1, #0x40; strb r1, [r0, #1]; bx lr', a)
        elif name in route:
            code = R.asm(f'b {route[name]:#x}', a)
        else:
            code = R.asm('bx lr', a)
        region[a - lo:a - lo + len(code)] = code
    return bytes(region), A, placed, loops, blocks

"""
Diagnostic build: "beep detector".

Launcher hook that, before booting a game, instruments the game's ARM7 tight
hardware wait loops. A loop that keeps spinning for ~10 s makes the console beep
N times (repeating), N = category of the register it waits on:

  1 = cartridge save SPI (AUXSPICNT 0x040001A0..A3)
  2 = cartridge ROM bus  (ROMCTRL 0x040001A4..AF, 0x04100010)
  3 = IPC / FIFO          (0x04000180..8F, 0x04100000)
  4 = other I/O
  5 = DS Wi-Fi            (0x0480xxxx)

NVRAM SPI loops (0x040001C0/C2) are not instrumented. Trampolines live in the
bodies of the game's NVRAM *write* functions (PP/PW/PE/SE), which are stubbed
with `bx lr` (equivalent to the dead chip). NVRAM reads are left untouched.
"""
import struct
from romemu import asm
import romemu as R
import launcherhook as LH

TRAMP_LEN = 0x2C
BXLR = 0xE12FFF1E


def tramp_template():
    t = asm('''
        push {r0, r1}
        add r1, pc, #0x1c
        ldr r0, [r1]
        add r0, r0, #1
        str r0, [r1]
        cmp r0, #0x02000000
        pop {r0, r1}
        blo 0
        mov r0, #0
        b 0
        .word 0
    ''', 0)
    assert len(t) == TRAMP_LEN, hex(len(t))
    return t


def beep_template():
    # r0 = number of beeps (repeats forever)
    return asm('''
        mov r1, #0x04000000
        mov r2, #0
        str r2, [r1, #0x208]
        add r3, r1, #0x500
        ldr r2, k_scv
        strh r2, [r3]
        ldr r2, k_tmr
        strh r2, [r3, #-0x28]
    b_rep:
        mov r5, r0
    b_one:
        ldr r2, k_on
        str r2, [r3, #-0x30]
        mov r6, #0x100000
    d1: subs r6, r6, #1
        bne d1
        str r6, [r3, #-0x30]
        mov r6, #0x100000
    d2: subs r6, r6, #1
        bne d2
        subs r5, r5, #1
        bne b_one
        mov r6, #0x500000
    d3: subs r6, r6, #1
        bne d3
        b b_rep
    k_scv:  .word 0x0000807F
    k_on:   .word 0xE340007F
    k_tmr:  .word 0x0000F7D1
    ''', 0)


def _cl_src(at, FR):
    # classify(r0=cmd, r6=entry): stub NVRAM write functions, record their bodies as free space
    return asm(f'''
        cmp r0, #2
        cmpne r0, #0xa
        cmpne r0, #0xdb
        cmpne r0, #0xd8
        movne r0, #1
        bxne lr
        mov r1, r6
    f:  ldr r2, [r1], #4
        ldr r3, k_bxlr
        cmp r2, r3
        bne f
        sub r1, r1, #4
        ldr r2, k_fr
        ldr r3, [r2, #0xc]
        cmp r3, #4
        bhs c_done
        add r12, r2, #0x10
        add r12, r12, r3, lsl #3
        add r0, r6, #4
        str r0, [r12]
        str r1, [r12, #4]
        add r3, r3, #1
        str r3, [r2, #0xc]
        ldr r0, k_bxlr
        str r0, [r6]
    c_done:
        mov r0, #1
        bx lr
    k_bxlr: .word 0xE12FFF1E
    k_fr:   .word {FR:#x}
    ''', at)


def _det_src(at, DCHK, DINS):
    return asm(f'''
        push {{r4, r5, r6, r7, r8, r9, r10, r11, lr}}
        mov r4, r0
        mov r5, r1
    d_loop:
        cmp r4, r5
        bhs d_done
        ldr r0, [r4]
        and r1, r0, #0x0f000000
        cmp r1, #0x0a000000
        bne d_next
        lsr r1, r0, #28
        cmp r1, #0xe
        bhs d_next
        lsl r2, r0, #8
        asr r2, r2, #6
        add r6, r4, #8
        add r6, r6, r2
        cmp r6, r4
        bhs d_next
        sub r3, r4, r6
        cmp r3, #0x18
        bhi d_next
        bl {DCHK:#x}
        cmp r0, #0
        blne {DINS:#x}
    d_next:
        add r4, r4, #4
        b d_loop
    d_done:
        pop {{r4, r5, r6, r7, r8, r9, r10, r11, lr}}
        bx lr
    ''', at)


def _dchk_src(at, DCAT):
    # r4 = branch, r6 = loop start -> r0 = category (0 = ignore)
    return asm(f'''
        mov r7, r6
        mvn r8, #0
    c_body:
        cmp r7, r4
        bhs c_bd
        ldr r0, [r7]
        tst r0, #0x0c000000
        bne c_ndp
        and r1, r0, #0x01e00000
        cmp r1, #0x00400000
        cmpne r1, #0x00800000
        beq c_no
    c_ndp:
        ldr r1, k_lhm
        and r1, r0, r1
        ldr r2, k_lhv
        cmp r1, r2
        ldrne r1, k_lwm
        andne r1, r0, r1
        ldrne r2, k_lwv
        cmpne r1, r2
        bne c_bn
        cmn r8, #1
        lsreq r8, r0, #16
        andeq r8, r8, #0xf
    c_bn:
        add r7, r7, #4
        b c_body
    c_bd:
        cmn r8, #1
        beq c_no
        mov r7, r6
        mov r10, #16
    c_lit:
        sub r7, r7, #4
        ldr r0, [r7]
        ldr r1, k_ldm
        and r1, r0, r1
        ldr r2, k_ldv
        cmp r1, r2
        bne c_ln
        lsr r1, r0, #12
        and r1, r1, #0xf
        cmp r1, r8
        bne c_ln
        lsl r2, r0, #20
        lsr r2, r2, #20
        tst r0, #0x00800000
        addne r3, r7, r2
        subeq r3, r7, r2
        ldr r1, [r3, #8]
        b {DCAT:#x}
    c_ln:
        subs r10, r10, #1
        bne c_lit
    c_no:
        mov r0, #0
        bx lr
    k_lhm:  .word 0x0F5000F0
    k_lhv:  .word 0x015000B0
    k_lwm:  .word 0x0F500000
    k_lwv:  .word 0x05100000
    k_ldm:  .word 0x0F7F0000
    k_ldv:  .word 0x051F0000
    ''', at)


def _dcat_src(at):
    # r1 = I/O address polled by the loop -> r0 = category
    return asm('''
        lsr r3, r1, #20
        cmp r3, #0x48
        moveq r0, #5
        bxeq lr
        cmp r3, #0x41
        bne c_io
        tst r1, #0x10
        moveq r0, #3
        movne r0, #2
        bx lr
    c_io:
        sub r3, r1, #0x04000000
        sub r3, r3, #0x180
        cmp r3, #0x10
        movlo r0, #3
        bxlo lr
        sub r3, r3, #0x20
        cmp r3, #4
        movlo r0, #1
        bxlo lr
        cmp r3, #0x10
        movlo r0, #2
        bxlo lr
        sub r3, r3, #0x20
        cmp r3, #4
        movlo r0, #0
        movhs r0, #4
        bx lr
    ''', at)


def _falloc_src(at, FRV):
    # falloc(r0=size, r1=src) -> r0 = dst (template copied) or 0.  FRV: +0 beep, +4 idx, +8 ptr, +0xC count, +0x10 ranges
    return asm(f'''
        push {{r4, r5, r6, r7, lr}}
        mov r4, r0
        mov r7, r1
        ldr r5, k_frv
    fa_try:
        ldr r1, [r5, #4]
        ldr r2, [r5, #0xc]
        cmp r1, r2
        movhs r0, #0
        bhs fa_ret
        add r3, r5, #0x10
        add r3, r3, r1, lsl #3
        ldr r2, [r5, #8]
        cmp r2, #0
        ldreq r2, [r3]
        ldr r3, [r3, #4]
        add r0, r2, r4
        cmp r0, r3
        bls fa_ok
        add r1, r1, #1
        str r1, [r5, #4]
        mov r0, #0
        str r0, [r5, #8]
        b fa_try
    fa_ok:
        str r0, [r5, #8]
        mov r0, r2
    fa_cp:
        ldr r3, [r7], #4
        str r3, [r2], #4
        subs r4, r4, #4
        bne fa_cp
    fa_ret:
        pop {{r4, r5, r6, r7, lr}}
        bx lr
    k_frv: .word {FRV:#x}
    ''', at)


def _dins_src(at, FALLOC, FRV, TT, BT, beep_len):
    # dins(r0=category, r4=branch addr, r6=loop start): install trampoline
    return asm(f'''
        push {{r4, r5, r6, r9, lr}}
        mov r9, r0
        ldr r11, k_frv
        ldr r0, [r11]
        cmp r0, #0
        bne di_have
        mov r0, #{beep_len:#x}
        ldr r1, k_bt
        bl {FALLOC:#x}
        cmp r0, #0
        beq di_ret
        str r0, [r11]
    di_have:
        mov r0, #0x2c
        ldr r1, k_tt
        bl {FALLOC:#x}
        cmp r0, #0
        beq di_ret
        mov r8, r0
        add r0, r8, #0x24
        sub r0, r6, r0
        lsr r0, r0, #2
        bic r0, r0, #0xff000000
        orr r0, r0, #0x3a000000
        str r0, [r8, #0x1c]
        orr r0, r9, #0xe3000000
        orr r0, r0, #0x00a00000
        str r0, [r8, #0x20]
        ldr r0, [r11]
        add r1, r8, #0x2c
        sub r0, r0, r1
        lsr r0, r0, #2
        bic r0, r0, #0xff000000
        orr r0, r0, #0xea000000
        str r0, [r8, #0x24]
        ldr r1, [r4]
        and r1, r1, #0xff000000
        add r0, r4, #8
        sub r0, r8, r0
        lsr r0, r0, #2
        bic r0, r0, #0xff000000
        orr r0, r0, r1
        str r0, [r4]
    di_ret:
        pop {{r4, r5, r6, r9, lr}}
        bx lr
    k_frv: .word {FRV:#x}
    k_bt:  .word {BT:#x}
    k_tt:  .word {TT:#x}
    ''', at)


def _hk_src(at, SC, DCHK, DINS, FRV):
    # hook: find the game's NVRAM write functions (free space), then scan its ARM7 for wait loops
    return asm(f'''
        push {{r4, r5, r6, r7, r8, r9, r10, r11, lr}}
        ldr r4, [r9, #0x38]
        ldr r5, [r9, #0x3c]
        lsr r0, r4, #24
        cmp r0, #2
        bne h_done
        cmp r5, #0
        beq h_done
        cmp r5, #0x100000
        bhi h_done
        add r5, r4, r5
        mov r1, #0
        ldr r0, k_frv
        str r1, [r0]
        str r1, [r0, #4]
        str r1, [r0, #8]
        str r1, [r0, #0xc]
        push {{r4, r5}}
        mov r6, #0
        mov r7, #0
        mov r8, #0
        mov r9, #1
        mov r10, #0
        bl {SC:#x}
        pop {{r4, r5}}
    d_loop:
        cmp r4, r5
        bhs h_done
        ldr r0, [r4]
        and r1, r0, #0x0f000000
        cmp r1, #0x0a000000
        bne d_next
        lsr r1, r0, #28
        cmp r1, #0xe
        bhs d_next
        lsl r2, r0, #8
        asr r2, r2, #6
        add r6, r4, #8
        add r6, r6, r2
        cmp r6, r4
        bhs d_next
        sub r3, r4, r6
        cmp r3, #0x18
        bhi d_next
        bl {DCHK:#x}
        cmp r0, #0
        blne {DINS:#x}
    d_next:
        add r4, r4, #4
        b d_loop
    h_done:
        pop {{r4, r5, r6, r7, r8, r9, r10, r11, lr}}
        mov r0, #0
        bx lr
    k_frv: .word {FRV:#x}
    ''', at)


def build_detector_region(d, base, entries, lo, hi):
    region = bytearray(hi - lo)
    used = bytearray(hi - lo)
    stub_len = {'RDSR': 12, 'RDID': 20}
    for name, a in entries.items():
        n = stub_len.get(name, 4)
        used[a - lo:a - lo + n] = b'\x01' * n
    tt, bt = tramp_template(), beep_template()
    srcs = {
        'US':    lambda A: R.user_settings(),
        'HDR':   lambda A: R.header(),
        'MAP':   lambda A: LH._map_src(A),
        'RD':    lambda A: R.asm(LH._RD_ASM.format(MAP=A['MAP']), A['RD']),
        'SC':    lambda A: LH._scan_src(A['SC'], A['CL']),
        'CL':    lambda A: _cl_src(A['CL'], A['FRV']),
        'DCHK':  lambda A: _dchk_src(A['DCHK'], A['DCAT']),
        'DCAT':  lambda A: _dcat_src(A['DCAT']),
        'FALLOC': lambda A: _falloc_src(A['FALLOC'], A['FRV']),
        'DINS':  lambda A: _dins_src(A['DINS'], A['FALLOC'], A['FRV'], A['TT'], A['BT'], len(bt)),
        'HK':    lambda A: _hk_src(A['HK'], A['SC'], A['DCHK'], A['DINS'], A['FRV']),
        'TT':    lambda A: tt,
        'BT':    lambda A: bt,
        'FRV':   lambda A: bytes(0x30),
    }
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
        raise RuntimeError('detector: pieces do not fit ' + str({k: hex(v) for k, v in sizes.items()}))
    A = dict(assign)
    for k, f in srcs.items():
        b = f(A)
        assert len(b) == sizes[k], k
        region[A[k] - lo:A[k] - lo + len(b)] = b
    # diagnostic build: launcher NVRAM writes are ignored (bx lr)
    route = {'READ': A['RD'], 'FREAD': A['RD']}
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
    return bytes(region), A

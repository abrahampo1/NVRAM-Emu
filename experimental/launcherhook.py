"""
Launcher hook: neutralises the NVRAM driver of the game being booted.

The DS launcher (HNAA, ARM7i) prepares the reboot into a cartridge / app in a
routine that already knows where the target ARM7 binary was loaded (ROM header
+0x38 / +0x3C, header pointer in r9). We replace one instruction there
(``mov r0, #0`` at 0x234B8F0) with ``bl hook``.

The hook scans the loaded ARM7 binary with the same algorithm as
``romemu.find_driver`` and, for every NVRAM driver function it recognises:

* RDSR  -> returns status 0x00 (ready)            (fixes the freeze)
* RDID  -> returns 20 40
* READ  -> replaced by a compact reader: firmware header 0x00-0x3F
           (valid Wi-Fi config length/CRC, dummy MAC), 0xFF elsewhere
* FREAD -> branch to READ
* every write/erase/power command -> ``bx lr`` (ignored)

Binaries without an SDK NVRAM driver (homebrew, TWiLight Menu++) are left
untouched.
"""
import struct
from romemu import asm, header

HOOK_SITE = 0x234B8F0
HOOK_SITE_ORIG = 0xE3A00000          # mov r0, #0

BXLR = 0xE12FFF1E


def reader_template():
    """Position-independent compact READ(addr=r0, len=r1, buf=r2)."""
    body = '''
        push {r4, lr}
        add r3, pc, #OFF
    rl: cmp r1, #0
        beq rd
        lsl r12, r0, #15
        lsr r12, r12, #15
        cmp r12, #0x40
        ldrblo r4, [r3, r12]
        movhs r4, #0xff
        strb r4, [r2], #1
        add r0, r0, #1
        sub r1, r1, #1
        b rl
    rd: pop {r4, lr}
        bx lr
    '''
    n = len(asm(body.replace('OFF', '0'), 0))
    # 'add r3, pc, #OFF' sits at offset 4, so pc reads as 0x0C; data follows the code
    code = asm(body.replace('OFF', hex(n - 0x0C)), 0)
    assert len(code) == n
    return code + header()


def _classify_src(at):
    return asm('''
    classify:
        cmp r0, #5
        beq c_rdsr
        cmp r0, #0x9f
        beq c_rdid
        cmp r0, #3
        moveq r7, r6
        beq c_ok
        cmp r0, #0xb
        moveq r8, r6
        beq c_ok
        cmp r0, #2
        cmpne r0, #0xa
        cmpne r0, #0xdb
        cmpne r0, #0xd8
        cmpne r0, #0xc7
        cmpne r0, #6
        cmpne r0, #4
        cmpne r0, #0xb9
        cmpne r0, #0xab
        cmpne r0, #0xff
        movne r0, #0
        bxne lr
        ldr r1, k_bxlr
        str r1, [r6]
        b c_ok
    c_rdsr:
        ldr r1, k_mov0
        str r1, [r6]
        ldr r1, k_strb0
        str r1, [r6, #4]
        ldr r1, k_bxlr
        str r1, [r6, #8]
        b c_ok
    c_rdid:
        ldr r1, k_mov20
        str r1, [r6]
        ldr r1, k_strb0
        str r1, [r6, #4]
        ldr r1, k_mov40
        str r1, [r6, #8]
        ldr r1, k_strb1
        str r1, [r6, #12]
        ldr r1, k_bxlr
        str r1, [r6, #16]
    c_ok:
        mov r0, #1
        bx lr
    k_bxlr:  .word 0xE12FFF1E
    k_mov0:  .word 0xE3A01000
    k_strb0: .word 0xE5C01000
    k_mov20: .word 0xE3A01020
    k_mov40: .word 0xE3A01040
    k_strb1: .word 0xE5C01001
    ''', at)


def _scan_src(at, CL):
    return asm(f'''
    scan:
        push {{lr}}
    s_loop:
        cmp r4, r5
        bhs s_done
        ldr r0, [r4]
        ldr r1, k_bxlr2
        cmp r0, r1
        beq s_term
        lsr r1, r0, #15
        ldr r2, k_popc
        cmp r1, r2
        beq s_term
        cmp r9, #0
        beq s_np
        lsr r1, r0, #28
        cmp r1, #0xe
        bne s_next
        mov r6, r4
        mov r9, #0
        mov r10, #0
    s_np:
        cmp r10, #0
        bne s_next
        cmp r6, #0
        beq s_next
        bic r1, r0, #0xf000
        ldr r2, k_sel1
        cmp r1, r2
        ldrne r2, k_sel2
        cmpne r1, r2
        bne s_next
        mov r11, #1
    s_la:
        ldr r0, [r4, r11, lsl #2]
        bic r1, r0, #0xf000
        bic r1, r1, #0xff
        ldr r2, k_movi
        cmp r1, r2
        bne s_lan
        and r0, r0, #0xff
        bl {CL:#x}
        cmp r0, #0
        movne r10, #1
        bne s_next
    s_lan:
        add r11, r11, #1
        cmp r11, #5
        blo s_la
        b s_next
    s_term:
        mov r9, #1
    s_next:
        add r4, r4, #4
        b s_loop
    s_done:
        pop {{lr}}
        bx lr
    k_bxlr2: .word 0xE12FFF1E
    k_popc:  .word 0x1D17B
    k_sel1:  .word 0xE3A00C89
    k_sel2:  .word 0xE3A00C81
    k_movi:  .word 0xE3A00000
    ''', at)


def _finalize_src(at, T, tlen):
    # r7 = READ entry, r8 = FREAD entry (0 if absent)
    return asm(f'''
    finalize:
        cmp r7, #0
        bxeq lr
        mov r0, r7
        ldr r1, k_bxlr3
    f_find:
        ldr r2, [r0], #4
        cmp r2, r1
        bne f_find
        sub r0, r0, r7
        cmp r0, #{tlen:#x}
        bxlo lr
        ldr r0, k_tmpl
        mov r1, r7
        mov r2, #{tlen:#x}
    f_copy:
        ldr r3, [r0], #4
        str r3, [r1], #4
        subs r2, r2, #4
        bne f_copy
        cmp r8, #0
        bxeq lr
        sub r0, r7, r8
        sub r0, r0, #8
        lsr r0, r0, #2
        bic r0, r0, #0xff000000
        orr r0, r0, #0xea000000
        str r0, [r8]
        bx lr
    k_bxlr3: .word 0xE12FFF1E
    k_tmpl:  .word {T:#x}
    ''', at)


def _hook_src(at, SC, FIN):
    return asm(f'''
    hook:
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
        mov r6, #0
        mov r7, #0
        mov r8, #0
        mov r9, #1
        mov r10, #0
        bl {SC:#x}
        bl {FIN:#x}
    h_done:
        pop {{r4, r5, r6, r7, r8, r9, r10, r11, lr}}
        mov r0, #0
        bx lr
    ''', at)


def build_hook(alloc, put):
    """Place the hook in free space of the launcher's (already emulated) NVRAM driver region.
    Returns (hook_entry, template_addr)."""
    tmpl = reader_template()
    P = 0x2300000  # probe address for size measurement
    SC = alloc(len(_scan_src(P, P)))
    CL = alloc(len(_classify_src(P)))
    put(CL, _classify_src(CL))
    put(SC, _scan_src(SC, CL))
    T = alloc(len(tmpl))
    put(T, tmpl)
    FIN = alloc(len(_finalize_src(P, P, len(tmpl))))
    put(FIN, _finalize_src(FIN, T, len(tmpl)))
    HK = alloc(len(_hook_src(P, P, P)))
    put(HK, _hook_src(HK, SC, FIN))
    return HK, T


# ---------------------------------------------------------------------------
# v1.2: Wi-Fi wait neutraliser + packed layout of the whole launcher region
# ---------------------------------------------------------------------------
def _wifi_src(at, WC):
    """wifi(r0=start, r1=end): find backward conditional branches (loops of up
    to 10 instructions) and let _wcheck decide; neutralise with a nop."""
    return asm(f'''
    wifi:
        push {{r4, r5, r6, r7, r8, r10, lr}}
        mov r4, r0
        mov r5, r1
    w_loop:
        cmp r4, r5
        bhs w_done
        ldr r0, [r4]
        and r1, r0, #0x0f000000
        cmp r1, #0x0a000000
        bne w_next
        lsr r1, r0, #28
        cmp r1, #0xe
        bhs w_next
        lsl r2, r0, #8
        asr r2, r2, #6
        add r6, r4, #8
        add r6, r6, r2
        cmp r6, r4
        bhs w_next
        sub r3, r4, r6
        cmp r3, #0x28
        bhi w_next
        bl {WC:#x}
        cmp r0, #0
        ldrne r1, k_nop
        strne r1, [r4]
    w_next:
        add r4, r4, #4
        b w_loop
    w_done:
        pop {{r4, r5, r6, r7, r8, r10, lr}}
        bx lr
    k_nop: .word 0xE1A00000
    ''', at)


def _wcheck_src(at):
    """r4 = branch, r6 = loop start. Returns r0=1 if the loop body has no
    add/sub counter and polls (ldrh) a register whose base was loaded from a
    0x0480xxxx literal (DS Wi-Fi I/O)."""
    return asm('''
    wcheck:
        mov r7, r6
        mvn r8, #0
    c_body:
        cmp r7, r4
        bhs c_bdone
        ldr r0, [r7]
        tst r0, #0x0c000000
        bne c_notdp
        and r1, r0, #0x01e00000
        cmp r1, #0x00400000
        beq c_no
        cmp r1, #0x00800000
        beq c_no
    c_notdp:
        ldr r1, k_lh_m
        and r1, r0, r1
        ldr r2, k_lh_v
        cmp r1, r2
        bne c_bnext
        cmn r8, #1
        lsreq r8, r0, #16
        andeq r8, r8, #0xf
    c_bnext:
        add r7, r7, #4
        b c_body
    c_bdone:
        cmn r8, #1
        beq c_no
        mov r7, r6
        mov r10, #16
    c_lit:
        sub r7, r7, #4
        ldr r0, [r7]
        ldr r1, k_ld_m
        and r1, r0, r1
        ldr r2, k_ld_v
        cmp r1, r2
        bne c_litn
        lsr r1, r0, #12
        and r1, r1, #0xf
        cmp r1, r8
        bne c_litn
        lsl r2, r0, #20
        lsr r2, r2, #20
        tst r0, #0x00800000
        addne r3, r7, r2
        subeq r3, r7, r2
        ldr r1, [r3, #8]
        lsr r1, r1, #16
        ldr r2, k_wifi
        cmp r1, r2
        moveq r0, #1
        bxeq lr
        b c_no
    c_litn:
        subs r10, r10, #1
        bne c_lit
    c_no:
        mov r0, #0
        bx lr
    k_lh_m: .word 0x0F5000F0
    k_lh_v: .word 0x015000B0
    k_ld_m: .word 0x0F7F0000
    k_ld_v: .word 0x051F0000
    k_wifi: .word 0x0480
    ''', at)


def _hook2_src(at, SC, FIN, WF):
    return asm(f'''
    hook:
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
        mov r0, r4
        mov r1, r5
        bl {WF:#x}
        mov r6, #0
        mov r7, #0
        mov r8, #0
        mov r9, #1
        mov r10, #0
        bl {SC:#x}
        bl {FIN:#x}
    h_done:
        pop {{r4, r5, r6, r7, r8, r9, r10, r11, lr}}
        mov r0, #0
        bx lr
    ''', at)


def build_launcher_region(d, base, entries, lo, hi):
    """Packs the launcher NVRAM emulator + game hook (NVRAM + Wi-Fi) into the
    original driver region. Returns (region_bytes, hook_entry)."""
    import romemu as R
    region = bytearray(hi - lo)
    used = bytearray(hi - lo)
    stub_len = {'RDSR': 12, 'RDID': 20}
    for name, a in entries.items():
        n = stub_len.get(name, 4)
        used[a - lo:a - lo + n] = b'\x01' * n

    def alloc(size):
        run = 0
        for o in range(len(region)):
            if used[o] or ((lo + o) % 4 and run == 0):
                run = 0; continue
            if run == 0:
                start = o
            run += 1
            if run == size:
                for k in range(start, start + size):
                    used[k] = 1
                return lo + start
        raise RuntimeError(f'no space for {size:#x}')

    P = lo
    tmpl = reader_template()
    # (name, size) known up front; assemble later with final addresses
    srcs = {
        'US':  lambda A: R.user_settings(),
        'T':   lambda A: tmpl,
        'SC':  lambda A: _scan_src(A['SC'], A['CL']),
        'CL':  lambda A: _classify_src(A['CL']),
        'FIN': lambda A: _finalize_src(A['FIN'], A['T'], len(tmpl)),
        'WF':  lambda A: _wifi_src(A['WF'], A['WC']),
        'WC':  lambda A: _wcheck_src(A['WC']),
        'HK':  lambda A: _hook2_src(A['HK'], A['SC'], A['FIN'], A['WF']),
        'MAP': lambda A: _map_src(A),
        'RD':  lambda A: R.asm(_RD_ASM.format(MAP=A['MAP']), A['RD']),
        'WR':  lambda A: R.asm(_WR_ASM.format(MAP=A['MAP']), A['WR']),
    }
    dummy = {k: P for k in srcs}
    dummy['HDR'] = P
    sizes = {k: len(f(dummy)) for k, f in srcs.items()}
    # free spans between the entry stubs
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
        raise RuntimeError('launcher region: pieces do not fit')
    A = dict(assign)
    A['HDR'] = A['T'] + len(tmpl) - 0x40   # firmware header shared with the game READ template
    for k, f in srcs.items():
        b = f(A)
        assert len(b) == sizes[k], k
        o = A[k] - lo
        region[o:o + len(b)] = b
    # erases are ignored in the launcher (it always rewrites whole blocks)
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
    return bytes(region), A


_RD_ASM = '''
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
'''
_WR_ASM = '''
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
'''
_ER_ASM = '''
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
'''


def _map_src(A):
    import romemu as R
    MAP = A['MAP']
    src = '''
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
    m = bytearray(R.asm(src, MAP))
    # PC-relative offsets for the two 'add r1, pc, r1' (at +0x10 and +0x34)
    adds = [i for i in range(0, len(m) - 16, 4) if m[i:i + 4] == bytes.fromhex('01108fe0')]
    assert len(adds) == 2, adds
    struct.pack_into('<i', m, len(m) - 12, A['HDR'] - (MAP + adds[0] + 8))
    struct.pack_into('<i', m, len(m) - 4, A['US'] - (MAP + adds[1] + 8))
    return bytes(m)

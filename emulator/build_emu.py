# NVRAM emulator for the SPI flash driver of the HNAA DS launcher (ARM7i) embedded in TwlBg.
# Replaces the real driver (0x23150EC-0x2315904) with one backed by RAM buffers.
#
# Usage: python3 build_emu.py <decrypted_arm7i.bin> <out_arm7i.bin>
# The region is zero-filled first, so the output region only contains code/data generated here.
import struct, sys
from keystone import Ks, KS_ARCH_ARM, KS_MODE_ARM
from capstone import Cs, CS_ARCH_ARM, CS_MODE_ARM

ks = Ks(KS_ARCH_ARM, KS_MODE_ARM)
def asm(code, addr):
    enc, _ = ks.asm(code, addr)
    return bytes(enc)

LO, HI = 0x23150EC, 0x2315904
E = dict(WREN=0x23150EC, WRDI=0x2315150, RDSR=0x2315190, READ=0x2315200, FREAD=0x2315328,
         PW=0x2315448, PP=0x2315554, PE=0x2315660, SE=0x23156E8, DP=0x2315770, RDP=0x23157B0,
         CE=0x23157F0, RDID=0x2315830, FF=0x23158CC)
US  = 0x2315204   # 0x100: user settings (both copies 0x1FE00/0x1FF00 map here)
HDR = 0x231532C   # 0x40: firmware header (0x00-0x3F)
C_MAP  = 0x231536C  # map + emu_read  (hasta 0x2315448)
C_WR   = 0x231544C  # emu_write       (hasta 0x2315554)
C_ER   = 0x2315558  # erase page/sector (hasta 0x2315660)

def crc16(data, init):
    c = init
    for b in data:
        c ^= b
        for _ in range(8):
            c = (c >> 1) ^ 0xA001 if c & 1 else c >> 1
    return c

def user_settings(lang=5):
    u = bytearray(0x100)
    struct.pack_into('<H', u, 0x00, 5)          # version
    u[0x02] = 0                                 # favourite colour
    u[0x03] = 1; u[0x04] = 1                    # birthday 1/1
    nick = 'USER'
    u[0x06:0x06+2*len(nick)] = nick.encode('utf-16le')
    struct.pack_into('<H', u, 0x1A, len(nick))
    struct.pack_into('<H', u, 0x50, 0)          # empty message
    # linear touch calibration (adc = pixel*16)
    struct.pack_into('<HHBBHHBB', u, 0x58, 0x20*16, 0x20*16, 0x20, 0x20, 0xE0*16, 0xA0*16, 0xE0, 0xA0)
    struct.pack_into('<H', u, 0x64, 0xFC00 | 0x30 | (lang & 7))
    u[0x66] = 0x18
    struct.pack_into('<I', u, 0x68, 0)
    struct.pack_into('<H', u, 0x70, 1)          # update counter
    struct.pack_into('<H', u, 0x72, crc16(u[0:0x70], 0xFFFF))
    # extended settings (DS lite / DSi)
    u[0x74] = 1; u[0x75] = lang
    struct.pack_into('<H', u, 0x76, 0x3E)
    for i in range(0x80, 0xFE): u[i] = 0xFF
    struct.pack_into('<H', u, 0xFE, crc16(u[0x74:0xFE], 0xFFFF))
    return bytes(u)

def header():
    h = bytearray(0x40)
    h[0x1D] = 0x57                              # console type: DSi
    h[0x1E] = h[0x1F] = 0xFF
    struct.pack_into('<H', h, 0x20, 0x1FE00 // 8)
    struct.pack_into('<H', h, 0x2C, 0x138)      # wifi config length
    h[0x2F] = 5
    h[0x36:0x3C] = bytes([0x00, 0x09, 0xBF, 0x12, 0x34, 0x56])  # dummy MAC address
    struct.pack_into('<H', h, 0x3C, 0x3FFE)
    h[0x3E] = h[0x3F] = 0xFF
    wifi = bytes(h[0x2C:0x40]) + b'\xFF' * (0x138 - (0x40 - 0x2C))
    struct.pack_into('<H', h, 0x2A, crc16(wifi, 0x0000))
    return bytes(h)

def build(region_orig):
    r = bytearray(region_orig)
    def put(addr, data):
        o = addr - LO
        assert LO <= addr and addr + len(data) <= HI, hex(addr)
        r[o:o+len(data)] = data
    # clear the whole region (unused gaps are never executed)
    for a in range(LO, HI): r[a-LO] = 0
    # stubs at the original entry points
    for k in ('WREN', 'WRDI', 'DP', 'RDP', 'CE', 'FF'):
        put(E[k], asm('bx lr', E[k]))
    put(E['RDSR'], asm('mov r1, #0; strb r1, [r0]; bx lr', E['RDSR']))   # always "ready"
    put(E['RDID'], asm('mov r1, #0x20; strb r1, [r0]; mov r1, #0x40; strb r1, [r0, #1]; bx lr', E['RDID']))
    EMU_READ = C_MAP + 0x50
    put(E['READ'],  asm(f'b {EMU_READ:#x}', E['READ']))
    put(E['FREAD'], asm(f'b {EMU_READ:#x}', E['FREAD']))
    put(E['PW'], asm(f'b {C_WR:#x}', E['PW']))
    put(E['PP'], asm(f'b {C_WR:#x}', E['PP']))
    EMU_EP, EMU_ES = C_ER, C_ER + 0x60
    put(E['PE'], asm(f'b {EMU_EP:#x}', E['PE']))
    put(E['SE'], asm(f'b {EMU_ES:#x}', E['SE']))
    # data
    put(US, user_settings())
    put(HDR, header())
    MAP = C_MAP
    map_code = f'''
        ldr r1, k_mask
        and r0, r0, r1
        cmp r0, #0x40
        bhs m1
        ldr r1, k_hdr
        add r0, r1, r0
        bx lr
    m1: ldr r1, k_us0
        subs r0, r0, r1
        movlo r0, #0
        bxlo lr
        and r0, r0, #0xff
        ldr r1, k_us
        add r0, r1, r0
        bx lr
    k_mask: .word 0x1ffff
    k_hdr:  .word {HDR:#x}
    k_us0:  .word 0x1fe00
    k_us:   .word {US:#x}
    '''
    m = asm(map_code, MAP); assert len(m) <= 0x50, len(m); put(MAP, m)
    rd = asm(f'''
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
    ''', EMU_READ)
    assert EMU_READ + len(rd) <= 0x2315448; put(EMU_READ, rd)
    wr = asm(f'''
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
    ''', C_WR)
    assert C_WR + len(wr) <= 0x2315554; put(C_WR, wr)
    def eraser(addr, clear, count):
        return asm(f'''
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
        ''', addr)
    ep = eraser(EMU_EP, 'bic r4, r0, #0xff', 0x100)
    es = eraser(EMU_ES, 'bic r4, r0, #0xff00\n        bic r4, r4, #0xff', 0x10000)
    assert len(ep) <= 0x60 and EMU_ES + len(es) <= 0x2315660
    put(EMU_EP, ep); put(EMU_ES, es)
    return bytes(r)

if __name__ == '__main__':
    arm7i = open(sys.argv[1], 'rb').read()
    ram = 0x2300000
    new = build(arm7i[LO-ram:HI-ram])
    out = bytearray(arm7i); out[LO-ram:HI-ram] = new
    open(sys.argv[2], 'wb').write(out)
    md = Cs(CS_ARCH_ARM, CS_MODE_ARM)
    for name, a in sorted(E.items(), key=lambda x: x[1]):
        i = next(md.disasm(out[a-ram:a-ram+4], a))
        print(f'{name:5s} {a:#x}: {i.mnemonic} {i.op_str}')

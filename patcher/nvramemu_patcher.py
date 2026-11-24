#!/usr/bin/env python3
"""
NVRAM-Emu patcher
=================

Builds a patched ``TwlBg.cxi`` from *your own* TWL_FIRM dump so that DS mode
(TWL_FIRM) boots on a console whose NVRAM (the SPI flash that stores the DS-mode
user settings) is dead or unreadable.

Nintendo code is never distributed: this script only applies NVRAM-Emu's own
patches to a firmware dumped from your console.

Accepted inputs (dump them with GodMode9):
  * the decrypted TWL_FIRM title content  (``0004013820000102.<id>_*.cxi``)
  * a TWL_FIRM ``.firm`` image             (decrypted or not; section 0 is used)
  * an unmodified ``TwlBg.cxi``

Output (copy the ``nvramemu`` folder to the root of your SD card):
  out/nvramemu/TwlBg_nvramemu.cxi
  out/nvramemu/TwlBg_nvramemu.cxi.sha      (SHA-256, used by the GodMode9 script)
  out/nvramemu/mset_code.ips               (copied from ../patches if present)

Requires: Python 3.8+, pycryptodome  (pip install pycryptodome)
"""
import argparse, base64, hashlib, os, shutil, struct, sys, zlib

try:
    from Crypto.Cipher import AES
except ImportError:  # pragma: no cover
    sys.exit("pycryptodome is required:  pip install pycryptodome")

VERSION = "1.1.0"
MU = 0x200

# ---------------------------------------------------------------------------
# Reference data (New 3DS TWL_FIRM shipped with system 11.17.0)
# ---------------------------------------------------------------------------
KNOWN_TWLBG_CODE_SHA256 = "5ae86470a4f00ca102c829928493a94bfae3119bd53c7e1679747ba69dbb958c"
KNOWN_OUTPUT_SHA256 = "3952b2c3fc7319aff538ff8fb7d401cb799ab15e82cdd5eb990a23dc9764b427"

# TwlBg patches: (offset in decompressed .code, original bytes, new bytes, description)
TWLBG_PATCHES = [
    (0x00ABC, "12f600ff", "c046c046", "skip result check: cfg touch-panel block read"),
    (0x00AD2, "12f6f5fe", "c046c046", "skip result check: GetLgyTouchPanelCal"),
    (0x00AE0, "12f6eefe", "c046c046", "skip result check: SetTouchPanelCal (NVRAM write)"),
    (0x00AFE, "12f6dffe", "c046c046", "skip result check: RTC offset read"),
    (0x00B16, "12f6d3fe", "c046c046", "skip result check: SetRtcOffset (NVRAM write)"),
    (0x32980, "0460",     "c046",     "never latch init failures -> no DsFatalError screen"),
]
MARKER_FROM = "An error has occurred.".encode("utf-16le")
MARKER_TO   = "An error has occurred!".encode("utf-16le")

# Embedded DS launcher (HNAA) inside TwlBg, ARM7i NVRAM SPI driver
HNAA_ARM7I_RAM = 0x2300000
EMU_LO, EMU_HI = 0x23150EC, 0x2315904
EMU_REGION_ORIG_SHA256 = "5c2966db36eccfd031d0ac717454d3975106513cf6b9fcba9fd37dbd2d025bb4"
# Assembled NVRAM emulator (source: emulator/build_emu.py), zlib+base64
EMU_BLOB = (
    "eNrNVT1LA0EQfXNeQFPIYQiISDiIhYjiBSNYmQVJZ3EmRNuAaCfkH6hBBH9F9ieIjY0fV4i1lVjehwGNrWAjGTdHErRQIvl8zTI7u/Pemx3YBC976DMS3XIYMoDhVBMD0NrAAVCLAEQoII8scj+yenfFNWimiUlEXbn6Od3eJpztUWS9HfNQcfPUiZWk6tOfB3aYnUwr8M/XCJFmMHE7ld6uZ5jTRqVKgCtgBxqwMK9i4NhtvLUZ5mwXkCsqTrEqYnzLMxMW8ykNdYKeU6tCSSy9QkiPbOlpRanmpRCMA1Ed0guY36B4gIc4Q44R7p9JnPhkZ/135lpJXL/0csY4rKn0YCuIKQ1kHblkbfjJtPRMPe+xhTLN7pZ/03vZ0ms8xtX8x6l46vdTbz9xpfRaqhcsnGDOrlQb/g6b/tiQsdBf6K3gfzDPWC1v1DlHWH/TCVjctTn2O+H4D0mPejEKb3IxIjq6neFh3zeb/5NQKw3wn+qnty+7s1Jv"
)


def log(msg):
    print(msg, flush=True)


# ---------------------------------------------------------------------------
# BLZ (backwards LZ, used by 3DS .code)
# ---------------------------------------------------------------------------
def blz_decompress(c):
    top_bot, inc = struct.unpack_from("<II", c, len(c) - 8)
    top, bottom = top_bot & 0xFFFFFF, top_bot >> 24
    out = bytearray(c) + bytearray(inc)
    src, dst, end = len(c) - bottom, len(out), len(c) - top
    while src > end:
        src -= 1
        flags = out[src]
        for _ in range(8):
            if src <= end:
                break
            if flags & 0x80:
                src -= 2
                v = out[src] | (out[src + 1] << 8)
                size, disp = ((v >> 12) & 0xF) + 3, (v & 0xFFF) + 3
                for _ in range(size):
                    dst -= 1
                    out[dst] = out[dst + disp]
            else:
                src -= 1
                dst -= 1
                out[dst] = out[src]
            flags = (flags << 1) & 0xFF
            if dst <= end:
                break
    return bytes(out)


def _blz_body(data):
    r = data[::-1]
    n = len(r)
    out = bytearray()
    head = {}
    i = 0

    def add(p):
        if p + 3 <= n:
            head.setdefault(r[p:p + 3], []).append(p)

    while i < n:
        fpos = len(out)
        out.append(0)
        flags = 0
        for bit in range(8):
            if i >= n:
                break
            best_len = best_d = 0
            if i + 3 <= n:
                for p in reversed(head.get(r[i:i + 3], [])):
                    d = i - p
                    if d > 0x1002:
                        break
                    if d < 3:
                        continue
                    l = 3
                    while l < 18 and i + l < n and r[p + l] == r[i + l]:
                        l += 1
                    if l > best_len:
                        best_len, best_d = l, d
                        if l == 18:
                            break
            if best_len >= 3:
                v = ((best_len - 3) << 12) | (best_d - 3)
                out += bytes((v >> 8, v & 0xFF))
                flags |= 0x80 >> bit
                for k in range(best_len):
                    add(i + k)
                i += best_len
            else:
                out.append(r[i])
                add(i)
                i += 1
        out[fpos] = flags
    return bytes(out)


def blz_compress(data):
    for prefix in range(0, 0x100000, 0x100):
        comp = _blz_body(data[prefix:])[::-1]
        pad = (-(prefix + len(comp))) % 4
        bottom = 8 + pad
        total = prefix + len(comp) + pad + 8
        f = data[:prefix] + comp + b"\xFF" * pad + struct.pack(
            "<II", (len(comp) + bottom) | (bottom << 24), len(data) - total)
        try:
            if blz_decompress(f) == data:  # verifies in-place decompression too
                return f
        except Exception:
            pass
    raise RuntimeError("BLZ compression failed")


# ---------------------------------------------------------------------------
# DSi modcrypt (AES-CTR, DSi byte order)
# ---------------------------------------------------------------------------
def modcrypt(data, key, iv):
    k = AES.new(key[::-1], AES.MODE_ECB)
    ctr = int.from_bytes(iv, "little")
    out = bytearray(len(data))
    for i in range(0, len(data), 16):
        ks = k.encrypt(((ctr + i // 16) % (1 << 128)).to_bytes(16, "big"))[::-1]
        blk = data[i:i + 16]
        out[i:i + len(blk)] = bytes(a ^ b for a, b in zip(blk, ks))
    return bytes(out)


# ---------------------------------------------------------------------------
# Container helpers
# ---------------------------------------------------------------------------
def u32(b, o):
    return struct.unpack_from("<I", b, o)[0]


def exefs_file(ncch, name):
    eo = u32(ncch, 0x1A0) * MU
    for i in range(10):
        n = ncch[eo + i * 16: eo + i * 16 + 8].rstrip(b"\0")
        off, size = struct.unpack_from("<2I", ncch, eo + i * 16 + 8)
        if n == name:
            return ncch[eo + 0x200 + off: eo + 0x200 + off + size]
    return None


def get_twlbg(data):
    if data[:4] == b"FIRM":
        off, _, size = struct.unpack_from("<3I", data, 0x40)
        log(f"[input] FIRM image, section 0 at {off:#x} ({size:#x} bytes)")
        return get_twlbg(data[off:off + size])
    if data[0x100:0x104] == b"NCCH":
        name = data[0x200:0x208].rstrip(b"\0")
        if name == b"TwlBg":
            log("[input] TwlBg NCCH found")
            return bytearray(data)
        firm = exefs_file(data, b".firm")
        if firm is not None:
            log("[input] TWL_FIRM title content (.cxi), extracting exefs/.firm")
            return get_twlbg(firm)
    raise SystemExit("ERROR: input is not a TWL_FIRM .cxi/.firm or a TwlBg.cxi")


def patch_twlbg_code(code):
    code = bytearray(code)
    for off, old, new, desc in TWLBG_PATCHES:
        old, new = bytes.fromhex(old), bytes.fromhex(new)
        cur = bytes(code[off:off + len(old)])
        if cur != old:
            raise SystemExit(f"ERROR: unexpected bytes at {off:#x} ({cur.hex()} != {old.hex()}).\n"
                             "This TWL_FIRM version is not supported.")
        code[off:off + len(new)] = new
        log(f"[twlbg] {0x300000 + off:#09x}  {desc}")
    n = bytes(code).count(MARKER_FROM)
    code = bytearray(bytes(code).replace(MARKER_FROM, MARKER_TO))
    log(f"[twlbg] error-screen marker '!' applied ({n} copies)")
    return code


# ---------------------------------------------------------------- touch calibration
# The emulated user profile ships a generic touch calibration. With --touch-config
# the calibration is computed from the console's own 3DS calibration (config block
# 0x00040000), exactly like TwlBg does for scaled DS mode (raw points kept, screen
# points scaled by 0.8). --touch-y-offset moves the touch point up by N DS pixels.
US_OFFSET_IN_BLOB = 0x118          # user settings (0x100 bytes) inside EMU_BLOB
TOUCH_CAL = None                   # (adc_x1, adc_y1, scr_x1, scr_y1, adc_x2, adc_y2, scr_x2, scr_y2)


def crc16(data, crc=0xFFFF):
    for b in data:
        crc ^= b
        for _ in range(8):
            crc = (crc >> 1) ^ 0xA001 if crc & 1 else crc >> 1
    return crc


def read_3ds_touch_block(save):
    """Find config block 0x00040000 in a GodMode9 copy of sysdata/00010017/00000000."""
    pos = 0
    while True:
        e = save.find(struct.pack("<I", 0x40000), pos)
        if e < 0:
            raise SystemExit("ERROR: touch calibration block not found in the config save")
        pos = e + 1
        off, size, flags = struct.unpack_from("<IHH", save, e + 4)
        if size != 0x10:
            continue
        for k in range(0x200):
            base = e - 4 - 12 * k
            if base < 0:
                break
            n, doff = struct.unpack_from("<HH", save, base)
            if n > k and n < 0x400 and off + 0x10 <= 0x8000 and base + off + 0x10 <= len(save):
                blk = struct.unpack_from("<8H", save, base + off)
                if 0 < blk[2] < 320 and 0 < blk[3] < 240 and blk[2] < blk[6] < 320 and blk[3] < blk[7] < 240:
                    return blk


def touch_cal_from_config(path, y_offset=0):
    rx1, ry1, sx1, sy1, rx2, ry2, sx2, sy2 = read_3ds_touch_block(open(path, "rb").read())
    cal = [rx1, ry1, int(sx1 * 0.8), int(sy1 * 0.8), rx2, ry2, int(sx2 * 0.8), int(sy2 * 0.8)]
    if y_offset:
        k = (cal[5] - cal[1]) / (cal[7] - cal[3])
        cal[1] = round(cal[1] + y_offset * k)
        cal[7] -= y_offset
    return tuple(cal)


def patch_hnaa(code):
    logo = bytes.fromhex("24ffae51699aa221")
    p = bytes(code).find(logo)
    if p < 0:
        raise SystemExit("ERROR: embedded DS launcher not found in TwlBg")
    s = p - 0xC0
    hdr = bytes(code[s:s + 0x1000])
    if hdr[0x0C:0x10] != b"HNAA":
        raise SystemExit("ERROR: embedded launcher is not HNAA")
    log(f"[hnaa]  DS launcher HNAA found at TwlBg+{s:#x}")
    off, size = struct.unpack_from("<2I", hdr, 0x228)          # modcrypt area 2 = ARM7i
    key, iv = hdr[0:16], hdr[0x314:0x324]
    arm7i = bytearray(modcrypt(bytes(code[s + off:s + off + size]), key, iv))
    lo, hi = EMU_LO - HNAA_ARM7I_RAM, EMU_HI - HNAA_ARM7I_RAM
    if hashlib.sha256(arm7i[lo:hi]).hexdigest() != EMU_REGION_ORIG_SHA256:
        raise SystemExit("ERROR: ARM7i NVRAM driver does not match the supported version")
    log(f"[hnaa]  ARM7i decrypted, NVRAM SPI driver verified ({EMU_LO:#x}-{EMU_HI:#x})")
    region = bytearray(zlib.decompress(base64.b64decode(EMU_BLOB)))
    if TOUCH_CAL:
        us = US_OFFSET_IN_BLOB
        struct.pack_into("<HHBBHHBB", region, us + 0x58, *TOUCH_CAL)
        struct.pack_into("<H", region, us + 0x72, crc16(region[us:us + 0x70]))
        log(f"[hnaa]  touch calibration set to {TOUCH_CAL}")
    arm7i[lo:hi] = region
    log("[hnaa]  NVRAM driver replaced by RAM-backed emulator")
    code[s + off:s + off + size] = modcrypt(bytes(arm7i), key, iv)
    log("[hnaa]  ARM7i re-encrypted")
    return code


def build(twlbg):
    eo, es, hr = (u32(twlbg, 0x1A0) * MU, u32(twlbg, 0x1A4) * MU, u32(twlbg, 0x1A8) * MU)
    hdr = twlbg[eo:eo + 0x200]
    if hdr[0:8].rstrip(b"\0") != b".code":
        raise SystemExit("ERROR: TwlBg exefs has no .code")
    csize = u32(hdr, 0xC)
    log("[build] decompressing TwlBg .code ...")
    code = blz_decompress(bytes(twlbg[eo + 0x200:eo + 0x200 + csize]))
    sha = hashlib.sha256(code).hexdigest()
    log(f"[build] .code {len(code):#x} bytes, sha256 {sha[:16]}..."
        + ("  (known 11.17 TWL_FIRM)" if sha == KNOWN_TWLBG_CODE_SHA256 else "  (unknown version, checking patch sites)"))
    code = patch_hnaa(patch_twlbg_code(code))
    log("[build] recompressing (BLZ), this takes about a minute ...")
    comp = blz_compress(bytes(code))
    if len(comp) > es - 0x200:
        raise SystemExit("ERROR: compressed code does not fit in exefs")
    out = bytearray(twlbg)
    region = bytearray(es - 0x200)
    region[:len(comp)] = comp
    out[eo + 0x200:eo + es] = region
    struct.pack_into("<I", out, eo + 0xC, len(comp))
    out[eo + 0x1E0:eo + 0x200] = hashlib.sha256(comp).digest()
    out[0x1C0:0x1E0] = hashlib.sha256(bytes(out[eo:eo + hr])).digest()
    if blz_decompress(comp) != bytes(code):
        raise SystemExit("ERROR: round-trip verification failed")
    log("[build] round-trip verification OK")
    return bytes(out)


def main():
    ap = argparse.ArgumentParser(description=f"NVRAM-Emu patcher v{VERSION}")
    ap.add_argument("input", help="TWL_FIRM .cxi / .firm dump, or TwlBg.cxi")
    ap.add_argument("-o", "--out", default="out", help="output folder (default: out)")
    ap.add_argument("--touch-config", metavar="CONFIG_SAVE",
                    help="(experimental) GodMode9 copy of 1:/data/<id>/sysdata/00010017/00000000; "
                         "the touch calibration is taken from it")
    ap.add_argument("--touch-y-offset", type=int, default=0, metavar="N",
                    help="(experimental) with --touch-config, move the touch point N DS pixels up")
    a = ap.parse_args()
    log(f"NVRAM-Emu patcher v{VERSION}")
    global TOUCH_CAL
    if a.touch_config:
        TOUCH_CAL = touch_cal_from_config(a.touch_config, a.touch_y_offset)
    twlbg = get_twlbg(open(a.input, "rb").read())
    result = build(twlbg)
    dst = os.path.join(a.out, "nvramemu")
    os.makedirs(dst, exist_ok=True)
    cxi = os.path.join(dst, "TwlBg_nvramemu.cxi")
    open(cxi, "wb").write(result)
    digest = hashlib.sha256(result).digest()
    open(cxi + ".sha", "wb").write(digest)
    ips = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "patches",
                       "mset_0004001000021000_code.ips")
    if os.path.exists(ips):
        shutil.copyfile(ips, os.path.join(dst, "mset_code.ips"))
    log(f"[done]  {cxi}\n        sha256 {digest.hex()}"
        + ("  (matches reference build)" if digest.hex() == KNOWN_OUTPUT_SHA256 else ""))
    log(f"Copy the folder '{dst}' to the root of your SD card, together with gm9/scripts/NVRAM-Emu.gm9.")


if __name__ == "__main__":
    main()

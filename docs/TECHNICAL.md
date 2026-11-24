# Technical notes

Analysis of a New 2DS XL (USA, 11.17.0-50U, Luma3DS v13.5) whose 3DS mode
works but DS mode never boots. All addresses refer to that firmware.

## 1. The `mset` crash

Luma3DS exception dump: ARM11 core 0, data abort, process `mset`
(`0004001000021000`), `PC 0x100068`, `DFSR 0x5`, `FAR 0x0`.

* `0x100048` is the `%s` handler of the `printf` engine. It walks the string
  passed in `r1`, which is `NULL`.
* Caller chain: `0x210E18` (DS profile screen: `ds_info_comm_u`,
  `ds_birthday_u`) → `0x19717C` (date formatter) → `0x1BD028`/`0x1BCD7C`
  (`snprintf("%s_jan", name)`).
* The date formatter indexes `month_N` labels with `table[month - 1]`. The DS
  profile is read through `cfg:nor` and arrives with **month = 0**, so it reads
  `table[-1] == NULL`.
* The DS profile layout (`+0x02` colour, `+0x03` month, `+0x04` day, `+0x06`
  nickname, `+0x1C` message) is the classic NDS firmware user-settings block,
  stored in the NVRAM.

**Patch** (`patches/mset_0004001000021000_code.ips`, offset `0x110F18`): the
screen always uses 1 January instead of the bytes read from the NVRAM.

GodMode9 cannot read `M:/nvram.mem` on the affected console, which points to
the NVRAM chip as the root cause.

## 2. TwlBg `DsFatalError`

TWL_FIRM (`0004013820000102`) section 0 is **TwlBg**, the ARM11 process
running during DS mode. It contains the `DsFatalError.bclyt` layout and the
text *"An error has occurred…"*.

* `0x300B1C` initialisation: reads the touch calibration config block
  (`0x40000`), converts it (`GetLgyTouchPanelCal`) and **writes it to the
  NVRAM** (`SetTouchPanelCal`), then does the same for the RTC offset
  (`SetRtcOffset`).
* Each step is followed by `0x1138C0` (`0x332900` in file layout), a
  "log if failed" helper. On failure it stores the first failing result in a
  global (`str r4,[r0]` at `0x332980`).
* `0x3200E0` later checks that global and calls `0x300EE8` with the result. A
  negative result selects `0x302640` (`DsFatalError`) instead of the normal
  screen.

**Patches**: the five checks in `0x300AA8`/`0x300AE8` become `mov r8,r8`, and
the global store at `0x332980` is disabled. The error string's final `.`
becomes `!` as a load marker.

With these patches DS mode starts (TwlBg draws the 4:3 frame) but both screens
stay white.

## 3. The DS launcher hang

TwlBg embeds a DSi SRL at file offset `0xCDE88`: **HNAA**, the DSi launcher
(title `0003001748 4E4141`, a development build). Its header flags (`0x1C = 7`)
select the *debug* modcrypt key, which is simply the first 16 header bytes.
ARM9 and ARM7i are modcrypted (AES-CTR, DSi byte order, IVs at `0x300`/`0x314`).

The ARM7i (RAM `0x2300000`) holds the NVRAM SPI driver (`SPICNT 0x8900/0x8100`):

| Address | Command |
|---|---|
| `0x23150EC` | WREN (06) |
| `0x2315150` | WRDI (04) |
| `0x2315190` | RDSR (05) |
| `0x2315200` | READ (03) |
| `0x2315328` | FAST READ (0B) |
| `0x2315448` | PAGE WRITE (0A) |
| `0x2315554` | PAGE PROGRAM (02) |
| `0x2315660` | PAGE ERASE (DB) |
| `0x23156E8` | SECTOR ERASE (D8) |
| `0x2315770` | DEEP POWER DOWN (B9) |
| `0x23157B0` | RELEASE (AB) |
| `0x23157F0` | CHIP ERASE (C7) |
| `0x2315830` | RDID (9F) |
| `0x23158CC` | FF |

`0x23401A0` loops on RDSR while bit 5 or bit 0 (WIP) is set. A dead chip
returns `0xFF`, so the loop never ends: that is the white screen.

## 4. The emulator

`emulator/build_emu.py` rewrites the whole `0x23150EC–0x2315904` region,
keeping every entry point:

* RDSR → `0x00`; RDID → `20 40`; WREN/WRDI/DP/RDP/CE/FF → no-op.
* READ / FAST READ → `emu_read`; PW / PP → `emu_write` (same page clipping as
  the original); PE / SE → erase emulated bytes to `0xFF`.
* Address map (`addr & 0x1FFFF`):
  * `0x00000–0x0003F` → 64-byte firmware header (console type `0x57`, user
    settings offset `0x1FE00`, dummy MAC, channels `0x3FFE`, Wi-Fi config CRC)
  * `0x1FE00–0x1FFFF` → one 256-byte user-settings block (both copies alias
    it): version 5, name `USER`, 1/1, linear touch calibration, language 5,
    valid CRC16 for `0x00–0x6F` and for the extended block `0x74–0xFD`
  * everything else reads `0xFF`, writes are ignored

The region was unit-tested under Unicorn (reads, writes with read-back, page
and sector erase, and the `0x23401A0` wait loop returning).

## 5. Rebuilding `TwlBg.cxi`

`.code` is BLZ-compressed. The patcher decompresses it, applies the patches,
re-encrypts the ARM7i with modcrypt, recompresses it with an in-place-safe BLZ
encoder (verified by round trip) and fixes the ExeFS file hash and superblock
hash. Size and exheader are unchanged. Luma3DS loads the result from
`/luma/sysmodules/TwlBg.cxi` when *Enable loading external FIRMs and modules*
is on.

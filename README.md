# NVRAM-Emu

**Boot DS mode on a New 3DS / New 2DS XL whose NVRAM chip is dead.**

NVRAM-Emu is a set of Luma3DS patches that replace the console's DS-mode NVRAM
(the small SPI flash that stores the DS user profile, touch calibration and
DS Wi-Fi settings) with a RAM-backed emulation. With it, DS cartridges and
TWiLight Menu++ boot again on consoles where 3DS mode works fine but every
attempt to enter DS mode fails.

> Tested on a New 2DS XL (USA, system 11.17.0-50U, Luma3DS v13.5).
> DS mode boots. ROMs from a DS flashcart (R4) run, including saving and
> loading. Original cartridges boot, but games freeze when they access the
> cartridge's save memory (see *Known issues*).

## Symptoms this fixes

* Opening *Nintendo DS Connections* in System Settings crashes with a Luma3DS
  exception in `mset` (data abort, `PC 0x100068`, `FAR 0x0`).
* Launching a DS cartridge or TWiLight Menu++ shows
  *"An error has occurred. Press and hold the POWER Button…"* on the bottom
  screen (TwlBg's `DsFatalError`), or hangs on white screens.
* GodMode9 fails to copy `M:/nvram.mem` ("Failed copying item").

If GodMode9 *can* read `nvram.mem`, your NVRAM is probably fine and this
project is not for you.

## How it works

| Component | Patch | Effect |
|---|---|---|
| System Settings (`0004001000021000`) | `code.ips`, 24 bytes | The DS profile screen no longer formats a birthday with month 0 (`month_0` → NULL → crash). |
| TwlBg (TWL_FIRM ARM11) | 6 small patches | Init failures caused by NVRAM writes (`SetTouchPanelCal`, `SetRtcOffset`) are no longer latched, so `DsFatalError` is not shown. The error text gets a `!` marker so you can tell the patched TwlBg is loaded. |
| HNAA DS launcher embedded in TwlBg (ARM7i) | NVRAM SPI driver replaced | The driver's busy-wait on the status register spun forever on a dead chip (`0xFF` = busy). It is replaced by an emulator: status always *ready*, valid firmware header and user profile (with correct CRCs), reads/writes/erases served from RAM. |

See [docs/TECHNICAL.md](docs/TECHNICAL.md) for the full analysis.

## Requirements

* New 3DS / New 2DS XL with Luma3DS 13.x and GodMode9
* TWL_FIRM from system 11.17 (other versions are rejected by the patcher)
* PC with Python 3.8+ and `pycryptodome`

## Installation

NVRAM-Emu does **not** ship Nintendo code. You build the patched `TwlBg.cxi`
from your own console's firmware.

1. **Dump TWL_FIRM** with GodMode9: go to
   `[1:]/title/00040138/20000102/content/`, press A on the `.app` and choose
   *Decrypt file (SD output)*. You get
   `0:/gm9/out/0004013820000102.<id>_….cxi`.
2. **Build the patch** on your PC:
   ```sh
   pip install pycryptodome
   python3 patcher/nvramemu_patcher.py 0004013820000102.xxxxxxxx_CTR-P-CTAP.cxi
   ```
   This creates `out/nvramemu/` with `TwlBg_nvramemu.cxi`, its `.sha` and
   `mset_code.ips`. The output SHA-256 for 11.17 is
   `3952b2c3fc7319aff538ff8fb7d401cb799ab15e82cdd5eb990a23dc9764b427`.
3. **Copy to the SD card root**:
   * `out/nvramemu/` → `SD:/nvramemu/`
   * `gm9/scripts/NVRAM-Emu.gm9` → `SD:/gm9/scripts/`
4. In GodMode9: **HOME → Scripts… → NVRAM-Emu → Enable patch**.
   Every step is shown on screen, any existing `TwlBg.cxi` (e.g. TWPatch) is
   backed up, and copies are verified with SHA-256.
5. *(Optional, experimental)* use your console's own touch calibration
   instead of the generic one. Copy
   `[1:]/data/<id>/sysdata/00010017/00000000` with GodMode9
   (*Copy to 0:/gm9/out*) and add it to step 2:
   ```sh
   python3 patcher/nvramemu_patcher.py <TWL_FIRM>.cxi --touch-config 00000000
   ```
   If the touch point is still too low, add `--touch-y-offset N` to move it up
   by N DS pixels (30 ≈ 1 cm on a New 2DS XL).
6. Reboot holding **SELECT** and enable in Luma:
   * `Enable loading external FIRMs and modules`
   * `Enable game patching`

## The GodMode9 manager

`NVRAM-Emu.gm9` offers:

* **Show status**: whether the emulated TwlBg and the System Settings patch
  are installed and verified, or whether another `TwlBg.cxi` is present.
* **Enable patch** / **Disable patch**: install or remove, with backup and
  restore of a previous `TwlBg.cxi`.
* **View log**: every action is recorded in `SD:/nvramemu/log.txt`.

To disable quickly without GodMode9, turn off
`Enable loading external FIRMs and modules` in Luma's menu.

## Limitations

* DS-mode Wi-Fi and local multiplayer do not work. The real chip holds the
  Wi-Fi calibration.
* Touch calibration in DS mode is generic and may be off. `--touch-config`
  computes it from the console's 3DS calibration, but in testing the vertical
  axis was still about 1 cm too low (hence `--touch-y-offset`); the cause is
  being investigated with `experimental/touchcal`.
* The emulated DS profile is fixed: name `USER`, birthday 1/1, language
  Spanish. Changes made in DS mode are lost on power-off.
* Only the New 3DS TWL_FIRM from 11.17 has been analysed. Other versions are
  refused instead of being patched blindly.
* Not compatible with other `TwlBg.cxi` mods (TWPatch filters/widescreen) at
  the same time. The manager backs them up and restores them.

## Known issues

* **Original cartridges freeze when a game reads or writes its save**
  (Harvest Moon DS stays on a white screen at boot, Wario: Master of Disguise
  and Bomberman freeze when starting a game). The same games run and save
  from a flashcart, which redirects saves to its microSD. The game code that
  talks to the cartridge save chip does not touch the NVRAM, so the cartridge
  save bus is the current suspect.
* TWiLight Menu++ may stop at *"Allocating space for RAM dump"*.

## Experimental tools

[`experimental/`](experimental/README.md) holds the research tools used to
debug the issues above (launcher hook, beep detector, ROM patcher, diagnostic
homebrew). They are not part of the release and some of them break flashcarts.

## Building the emulator from source

The ARM7i emulator is written in ARM assembly inside
[`emulator/build_emu.py`](emulator/build_emu.py) (needs `keystone-engine` and
`capstone`). The patcher embeds its assembled output.

## Disclaimer

This project modifies system software of your console. Use it at your own
risk and keep a NAND backup. It is not affiliated with or endorsed by
Nintendo. No Nintendo code or keys are included in this repository.

## License

[MIT](LICENSE)

# Experimental tools

Research code used while debugging games that freeze in DS mode. None of this
is needed to use NVRAM-Emu, and some of it has side effects described below.

| File | What it does | Status |
|---|---|---|
| `nvramemu_patcher_hook.py` | Patcher variant that also installs a hook in the DS launcher's reboot routine. Before a game boots, the hook emulates the game's own NVRAM driver and neutralises DS Wi-Fi hardware waits. | Broke Wario: Master of Disguise and every flashcart (R4, TWiLight). Not recommended. |
| `launcherhook.py`, `romemu.py` | Building blocks of the hook: NVRAM driver finder, position-independent emulator, Wi-Fi wait scanner. | Used by the files above. |
| `detector_generic.py` | "Beep detector": the hook instruments every tight hardware wait loop of the game's ARM7; a loop that spins for ~10 s makes the console beep N times (1 cartridge save, 2 cartridge ROM, 3 IPC, 4 other I/O, 5 Wi-Fi). | Works with any cartridge, but breaks flashcart loaders. ARM code only (Thumb loops are not seen). |
| `detector.py`, `detector_static.py` | Earlier versions of the detector (the static one is tied to a single game). | Superseded. |
| `nvramemu_rompatch.py` | Patches a `.nds` ROM's ARM7 instead of the launcher. | Experimental. |
| `tools/build_launcher_blob.py` | Rebuilds the hook region. | |
| `diag/` | DS homebrew that probes NVRAM, DS Wi-Fi and RTC. Built with `zig cc` (`pip install ziglang`), no devkitPro needed. | Never displayed on hardware. |
| `touchcal/` | DS homebrew that reads the raw touch ADC values at two known points, to measure the real DS-mode touch calibration. Built the same way. | Not yet tested on hardware. |

The Python modules import each other from this folder; run them from here or
add it to `PYTHONPATH`.

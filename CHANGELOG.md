# Changelog

## 1.1.0

* Patcher: new `--touch-config` option. It takes a GodMode9 copy of the console
  config save (`sysdata/00010017/00000000`) and computes the DS touch
  calibration from the console's own 3DS calibration (the same conversion
  TwlBg uses in scaled DS mode). This option is experimental.
* Patcher: new `--touch-y-offset N` option to move the touch point up by N DS pixels.
* The default build is byte-identical to 1.0.0.
* Documented known issues: original cartridges freeze on save access; flashcarts work.
* Added `experimental/` with the research tools: launcher hook, beep
  detector, ROM patcher, `diag` and `touchcal` homebrew.

## 1.0.0

* First release. RAM-backed NVRAM emulator in the DS launcher, TwlBg error
  latch patches, and the System Settings crash fix. Includes the GodMode9 manager.

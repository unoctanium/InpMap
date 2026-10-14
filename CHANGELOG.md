# Changelog

All notable changes to InpMap. Versions follow [semantic versioning](https://semver.org/);
before 1.0, minor versions may change the configuration language (the
`version` line in configuration files guards against incompatible changes).

## 0.2.0 (first public release)

InpMap is a configuration-driven input remapper for Linux: one key or
button can drive keys, buttons and sticks on several virtual devices at
once.

- **Configuration language** (`.inpmap` files, version 1), with errors
  reported as `FILE:LINE:COLUMN` before any device is touched.
- **Virtual keyboard and gamepad** outputs (buttons, D-pad, sticks,
  triggers); unmapped input passes through unchanged; LEDs keep working;
  devices that are unplugged are picked up again.
- **Mappings:** hold, tap, chords, sequences with waits and random waits,
  loops, autofire, toggles, parallel branches, stick movements with ramps,
  variables, conditions (tap vs. hold, double tap, long press, "pressed
  alone", lock LEDs), modifiers (`modifiers(ctrl, shift)`), mappings for one
  device or for every input, `disable`.
- **Sticks, analog triggers and the D-pad as triggers**
  (`map pad.ABS_RZ above 0.5`), including two-stage triggers.
- **Layers** (`layer NAME { … }`, `hold layer`, `layer NAME toggle`) and
  **reusable blocks** (`block` / `call`).
- **Profiles** in `~/.config/inpmap/`; a systemd **user service**
  (`inpmap@NAME`); an **emergency stop** (Backspace + Escape + Enter).
- **Tools:** `input-config` (pick devices, also by pressing a key; starts
  from the built-in example for the profile `example`), `detect` (presses
  shown as triggers), `axes`, `codes`, `check`, `macro-trace`, `fmt`,
  `devices`, `udev-rules`, `service-unit`, `syntax-file`, `test-outputs`.

Tested on CachyOS with KDE Plasma (Wayland); other distributions and
desktops are not tested yet.

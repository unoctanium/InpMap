# Changelog

All notable changes to InpMap. Versions follow [semantic versioning](https://semver.org/);
before 1.0, minor versions may change the configuration language (the
`version` line in configuration files guards against incompatible changes).

## 0.4.0 (2026-10-20)

- **Emulated DualSense Edge** (configuration.md §3.5): `emulate =
  "dualsense-edge"` on a gamepad output makes it a Sony DualSense Edge,
  created through `/dev/uhid`. Windows games under Proton then read it with
  their own PlayStation driver and get the back paddles (`BTN_GRIPL`,
  `BTN_GRIPR`) and Fn buttons (`BTN_GRIPL2`, `BTN_GRIPR2`) as paddles 1 to 4,
  which a normal virtual gamepad cannot deliver there. Opt-in; needs access
  to `/dev/uhid` (`inpmap udev-rules` adds it for such profiles) and Steam
  Input turned off for the game.
- `tools/dualsense_edge_uhid.py` presses the emulated controller's buttons
  in turn, for checking a game without a physical controller.

## 0.3.0 (2026-10-15)

- **Unmapped input goes to the outputs** (configuration.md §3.4): keys to
  the keyboard output, gamepad buttons, sticks and D-pad to the gamepad
  output. Applications see exactly the configured virtual devices instead
  of a copy of each physical device, so a gamepad plus its extra buttons is
  one controller and several keyboards are one keyboard. A pad's D-pad
  arrives as the D-pad buttons (which SDL and Steam use). Mouse parts and
  other things no output carries go to a small pass-through device of that
  input. New `to = OUTPUT` chooses the output (e.g. a second player's
  gamepad), `to = own` keeps the previous behaviour for a device. A device
  whose unmapped input would have nowhere to go is never grabbed: an error
  at start (exit status 1), only logged when it appears later. Keyboard
  LEDs follow the virtual keyboard. **Changed behaviour:** per-device
  desktop settings of configured keyboards now apply to "InpMap keyboard";
  use `to = own` to keep them; a keyboard input needs a keyboard output.
- The virtual gamepad can send the back paddles `BTN_GRIPL`, `BTN_GRIPR`,
  `BTN_GRIPL2`, `BTN_GRIPR2` (shown by Steam as L4, R4, L5, R5); they are
  declared only when a mapping uses them.

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

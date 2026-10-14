# InpMap

[![CI](https://github.com/unoctanium/InpMap/actions/workflows/ci.yml/badge.svg)](https://github.com/unoctanium/InpMap/actions/workflows/ci.yml)

InpMap is an input remapper for Linux. It takes over your physical keyboard
or gamepad and turns its keys and buttons into whatever you describe in a
small configuration file: other keys, gamepad buttons, stick movements, or
whole timed sequences ("macros"). One key can act on **several virtual
devices at once**, for example press a keyboard key and a gamepad button
together.

```inpmap
version 1
input kbd { path = "/dev/input/by-id/usb-4348_2.4G_Dongle-event-kbd" }
output keyboard { type = keyboard }
output gamepad { type = gamepad }

map KEY_X {  # X = keyboard Y + gamepad A
    hold KEY_Y
    hold BTN_SOUTH
}

map KEY_F10 {  # tap, double tap, long press
    on tap { tap KEY_1 }
    on double_tap { tap KEY_2 }
    on long_press { tap KEY_3 }
}

map KEY_CAPSLOCK {  # Caps Lock alone = Esc, with another key = Ctrl
    if single { tap KEY_ESC } else { hold KEY_LEFTCTRL }
}
```

## Why InpMap?

[Input Remapper](https://github.com/sezanzeb/input-remapper) is the
established remapper for Linux and served as the functional reference.
InpMap was started for needs it covers less well:

- **Several virtual output devices per mapping.** A key can drive a
  virtual keyboard and a virtual gamepad (or two gamepads) at the same time
  — e.g. for games that expect a gamepad.
- **Configuration as a readable text file** instead of a GUI: easy to write
  in any editor, to compare, to keep in git and to copy to other PCs.
  Errors are reported with file, line and column before any device is
  touched.
- **Predictable behaviour**: exact rules for modifiers (Shift+A stays a
  capital A unless you map it), reference-counted outputs, and a guarantee
  that no key is ever left stuck — on release, on errors, on unplugging and
  on shutdown.
- **A portable core.** The mapping engine is independent of Linux; a
  Windows version is planned.

## Features

- Keyboard keys and gamepad buttons as triggers, optionally with modifiers
  (`modifiers(ctrl, shift)`), from any number of physical devices. A
  mapping applies to every configured device that has the key, or to one
  device only (`pad.BTN_EAST`). Keys can be disabled.
- Sticks, analog triggers and the D-pad as buttons (`map pad.ABS_RZ above
  0.5`), also two-stage triggers; `inpmap axes` shows their live values.
- Virtual keyboards and gamepads (buttons, D-pad, sticks, triggers).
- Hold, tap, chords (`ctrl + KEY_C`), sequences with waits and random
  waits, loops, autofire, toggles, parallel branches, stick movements with
  ramps.
- Conditions: tap vs. hold, double tap, long press, "pressed alone",
  Caps/Num/Scroll Lock state, variables.
- Layers: groups of mappings switched on while a key is held or toggled,
  e.g. Caps Lock + WASD as arrow keys, or a flight-sim layer on the gamepad.
- Reusable blocks: write a sequence once (`block close_dialog { … }`) and
  `call` it from several mappings.
- Unmapped keys pass through unchanged; LEDs keep working; devices that
  are unplugged and plugged in again are picked up automatically.
- `inpmap input-config` finds your devices for you: press a key on the
  keyboard or gamepad you want, and it is added to the configuration.
- `inpmap fmt` lays out configuration files consistently, without ever
  changing what they mean.
- `inpmap macro-trace` shows the exact timeline of a mapping without
  touching any device.
- Runs in the foreground or as a systemd user service that starts at
  login, with one configuration or with profiles (e.g. one per game,
  switched with `systemctl --user`). Holding Backspace + Escape + Enter always stops it (emergency
  stop).

Not yet: mouse output, a GUI, Windows, a system-wide service.

## Documentation

| Document | Contents |
|---|---|
| [docs/installation.md](https://github.com/unoctanium/InpMap/blob/main/docs/installation.md) | requirements, installation, device permissions, user service, uninstall |
| [docs/usage.md](https://github.com/unoctanium/InpMap/blob/main/docs/usage.md) | first configuration step by step, all commands and options, troubleshooting |
| [docs/configuration.md](https://github.com/unoctanium/InpMap/blob/main/docs/configuration.md) | **reference** of the configuration language: every feature with examples |
| [docs/development.md](https://github.com/unoctanium/InpMap/blob/main/docs/development.md) | for contributors: tests, architecture |

## Quick start

```sh
sudo pacman -S --needed python python-evdev python-pipx   # Arch; other distributions: see installation.md
pipx install --system-site-packages inpmap

inpmap input-config example          # the example with your keyboard (press i, then a key)
inpmap run example --timeout 60      # try F1-F8, Caps Lock, Insert
inpmap input-config                  # your own profile: ~/.config/inpmap/default.inpmap
inpmap detect                        # press keys: see how to write them in a mapping
```

Device permissions may be needed first: see
[installation.md §3](https://github.com/unoctanium/InpMap/blob/main/docs/installation.md#3-device-permissions).
To work on InpMap itself, install it from the source code (installation.md §2b).

## Status

Version 0.2, Linux only. Verified on CachyOS / KDE Plasma (Wayland) with a
real keyboard and gamepad: remapping, suppression of the original keys,
passthrough, macros, modifiers, axes as triggers, the configuration
language and the user service. Later: Windows, then GUIs.

## License

MIT, see [LICENSE](https://github.com/unoctanium/InpMap/blob/main/LICENSE). Input Remapper (GPL-3.0) served as a
functional reference only; InpMap contains no code from it.

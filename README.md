# InpMap

[![CI](https://github.com/unoctanium/InpMap/actions/workflows/ci.yml/badge.svg)](https://github.com/unoctanium/InpMap/actions/workflows/ci.yml)

InpMap is an input remapper for Linux. It takes over your physical keyboard
or gamepad and turns its keys and buttons into whatever you describe in a
small configuration file: other keys, gamepad buttons, stick movements, or
whole timed sequences ("macros"). One key can act on **several virtual
devices at once**, for example press a keyboard key and a gamepad button
together.

## What you can do with it

- 🎹 **Remap any key** — to another key, to a combination like
  Ctrl+Shift+[, or to a whole sequence of keys with exact timing.
- 🎮 **Play controller-only games with the keyboard** — WASD on the left
  stick, Space on A, Shift on the trigger. The game sees a real gamepad.
- ⌨️ **Use the gamepad as a keyboard** — buttons as shortcuts, the D-pad as
  arrow keys, a half-pressed trigger as Space. Great for the couch.
- 🔁 **Remap the controller itself** — swap A and B, turn a stick or a
  two-stage trigger into buttons, add autofire.
- 🕹️ **Unlock hidden buttons** — extra buttons that a controller only sends
  as keyboard keys become real **back paddles** that Steam shows as L4, R4,
  L5 and R5 and lets you bind ([see how](#example-back-paddles-for-the-razer-raiju)).
- 🎯 **Paddles in Windows games under Proton** — an output can emulate a
  DualSense Edge, so games that only read paddles from real controllers
  get them ([configuration.md §3.5](docs/configuration.md#35-emulating-a-dualsense-edge-emulate)).
- 🧩 **Merge devices** — a gamepad and its extra buttons become **one**
  controller, several keyboards become one keyboard, two pads become two
  separate players.
- ⚡ **Smart keys and macros** — different actions on tap, hold, double tap
  and long press; toggles; loops; random delays; "Caps Lock alone = Esc,
  with another key = Ctrl".
- 🗂️ **Layers** — hold Caps Lock and WASD become arrow keys; a whole
  flight-sim layer on the gamepad, switched with one button.
- 🎯 **Profiles per game** — one file per game, started at login as a
  background service and switched with a single command.
- 🛡️ **Safe by design** — no key ever stays stuck, an emergency stop
  (Backspace + Escape + Enter) always works, and a device that does not fit
  your configuration is never taken over. No root needed while it runs.
- 📝 **Readable configuration** — a small text file instead of clicking
  through a GUI, with error messages that point to line and column, syntax
  highlighting for Kate and nano, and a `detect` command that tells you
  what each key is called.

### Example: back paddles for the Razer Raiju

The Razer Raiju V3 Pro has extra buttons, but on Linux they are not part of
the controller: programmed in the pad, they send **keyboard keys** (F13 to
F18) on a separate keyboard interface. Games and Steam never see them as
gamepad buttons.

InpMap takes over both parts of the pad, turns those keys into the Linux
back-paddle buttons, and presents everything as **one** virtual
controller. Steam then shows four working back paddles:

```inpmap
version 1
input pad { path = "/dev/input/by-id/usb-Razer_Razer_Raiju_V3_Pro_Wireless_-event-joystick" }
input padkeys { path = "/dev/input/by-id/usb-Razer_Razer_Raiju_V3_Pro_Wireless_-if01-event-kbd" }
output keyboard { type = keyboard }
output gamepad { type = gamepad }

map padkeys.KEY_F15 { hold BTN_GRIPL }   # upper left paddle  (Steam: L4)
map padkeys.KEY_F16 { hold BTN_GRIPR }   # upper right paddle (Steam: R4)
map padkeys.KEY_F17 { hold BTN_GRIPL2 }  # lower left paddle  (Steam: L5)
map padkeys.KEY_F18 { hold BTN_GRIPR2 }  # lower right paddle (Steam: R5)
```

The sticks, triggers, D-pad and buttons of the pad go unchanged to the same
virtual controller. The same works for any controller whose extra buttons
send keys.

### A first look at the configuration

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
- Unmapped keys, buttons and sticks go unchanged to the virtual device of
  their kind, so applications see exactly your configured devices: a
  gamepad plus its extra buttons becomes **one** controller. LEDs keep
  working; mice keep working; devices that are unplugged and plugged in
  again are picked up automatically.
- `inpmap input-config` finds your devices for you: press a key on the
  keyboard or gamepad you want, and it is added to the configuration.
- `inpmap fmt` lays out configuration files consistently, without ever
  changing what they mean.
- `inpmap macro-trace` shows the exact timeline of a mapping without
  touching any device.
- Runs in the foreground or as a systemd user service that starts at
  login. Profiles (e.g. one per game) are switched with `systemctl --user`.
  Holding Backspace + Escape + Enter always stops it (emergency stop).

Not yet: mouse output, a GUI, Windows, a system-wide service.

## Documentation

| Document | Contents |
|---|---|
| [docs/installation.md](https://github.com/unoctanium/InpMap/blob/main/docs/installation.md) | requirements, installation, device permissions, user service, uninstall |
| [docs/usage.md](https://github.com/unoctanium/InpMap/blob/main/docs/usage.md) | first configuration step by step, all commands and options, troubleshooting |
| [docs/configuration.md](https://github.com/unoctanium/InpMap/blob/main/docs/configuration.md) | **reference** of the configuration language: every feature with examples |
| [docs/wow-dualsense.md](https://github.com/unoctanium/InpMap/blob/main/docs/wow-dualsense.md) | World of Warcraft with the emulated DualSense Edge: the settings to make by hand |
| [docs/development.md](https://github.com/unoctanium/InpMap/blob/main/docs/development.md) | for contributors: tests, architecture, releases |
| [docs/roadmap.md](https://github.com/unoctanium/InpMap/blob/main/docs/roadmap.md) | goals, requirements, milestones and what comes next |
| [CHANGELOG.md](https://github.com/unoctanium/InpMap/blob/main/CHANGELOG.md) | changes per version |
| [CONTRIBUTING.md](https://github.com/unoctanium/InpMap/blob/main/CONTRIBUTING.md) | reporting problems, test reports, changing the code |

## Quick start

```sh
# Arch, CachyOS, Manjaro: build and install the package (until it is in the AUR)
sudo pacman -S --needed base-devel git
git clone https://github.com/unoctanium/InpMap.git ~/InpMap && cd ~/InpMap/packaging/aur && makepkg -sri

# other distributions: from PyPI (see installation.md for the system packages)
pipx install --system-site-packages inpmap

inpmap input-config example          # the example with your keyboard (press i, then a key)
inpmap run example --timeout 60      # try F1-F8, Caps Lock, Insert
inpmap input-config                  # your own profile: ~/.config/inpmap/default.inpmap
inpmap detect                        # press keys: see how to write them in a mapping
```

Device permissions may be needed first: see
[installation.md §3](https://github.com/unoctanium/InpMap/blob/main/docs/installation.md#3-device-permissions).
To work on InpMap itself, install it from the source code
([installation.md §2c](https://github.com/unoctanium/InpMap/blob/main/docs/installation.md#2c-from-the-source-code-for-development)).

## Status

Version 0.3, Linux only. Verified on CachyOS / KDE Plasma (Wayland) with a
real keyboard and a Razer Raiju V3 Pro: remapping, suppression of the
original keys, unmapped input on the virtual devices (one controller in
KDE and Steam, back paddles in Steam), macros, modifiers, axes as triggers,
the configuration language and the user service. Later: Windows, then
GUIs.

## License

MIT, see [LICENSE](https://github.com/unoctanium/InpMap/blob/main/LICENSE). Input Remapper (GPL-3.0) served as a
functional reference only; InpMap contains no code from it.

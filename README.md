# InpMap

[![CI](https://github.com/unoctanium/InpMap/actions/workflows/ci.yml/badge.svg)](https://github.com/unoctanium/InpMap/actions/workflows/ci.yml)

InpMap is an input remapper for Linux. It takes over your physical
keyboards and gamepads and turns their keys, buttons, sticks and triggers
into whatever you describe in a small configuration file: other keys,
gamepad buttons, stick movements, or whole timed sequences ("macros"). One
key can act on **several virtual devices at once**, for example press a
keyboard key and a gamepad button together. And it brings a **DualSense
Edge emulator**: your controller, whatever brand it is, can appear to
games and Steam as a Sony DualSense Edge, with back paddles and a working
touchpad ([see below](#the-dualsense-edge-emulator)).

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
- 🎯 **Turn any controller into a DualSense Edge** — back paddles, Fn
  buttons and a touchpad that Steam Input and games understand: trackpad
  mouse, radial menus, paddles in Windows games under Proton
  ([see below](#the-dualsense-edge-emulator)).
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

## The DualSense Edge emulator

Many controllers have more to offer than Linux lets through: back paddles
that only arrive as keyboard keys, a touchpad that only moves the desktop
pointer. Steam and most games do not know what to do with them.

The Sony DualSense Edge is different. Steam Input knows it inside out, and
games built on SDL read all of its controls directly. So InpMap lets your
controller **become one**. One line in an output does it:

```
output gamepad {
    type    = gamepad
    name    = "InpMap Gamepad"
    emulate = "dualsense-edge"
}
```

What you get:

- 🕹️ **Four back buttons Steam recognises.** Map your controller's extra
  buttons to the Edge's back paddles and Fn buttons. Steam shows them in
  its controller settings, ready to bind to anything: gamepad buttons,
  keys, mouse clicks, macros.
- 🖐️ **A touchpad that works like a Steam trackpad.** Your controller's
  touchpad becomes the Edge's touchpad. In Steam Input, use it whole or
  **split it into two trackpads**: one half as a mouse, the other as a
  radial menu, a touch menu, a scroll wheel or a set of buttons.
- 🎮 **Paddles in Windows games.** Proton hands a DualSense straight to
  the game, so games with PlayStation support (World of Warcraft, for
  example) see the paddles themselves, even with Steam Input switched off
  ([wow-dualsense.md](https://github.com/unoctanium/InpMap/blob/main/docs/wow-dualsense.md)).
- 🎛️ **Everything else stays yours.** Sticks, triggers, D-pad and buttons
  arrive unchanged, and all of InpMap's mappings, macros and layers keep
  working on top.

### Why it was built: a Razer Raiju V3 Pro

The Razer Raiju V3 Pro is a great controller with four back paddles, two
front paddles and a touchpad. On Linux, most of that was out of reach: the
paddles only send keyboard keys, and the touchpad only moves the desktop
pointer. Steam saw an ordinary Xbox-style pad.

The setup that unlocks all of it:

1. In Razer Synapse (once, stored in the pad), the back paddles send F13
   and up.
2. InpMap emulates a DualSense Edge and turns those keys into its paddles,
   and passes on the touchpad:

```inpmap
version 1
input pad { path = "/dev/input/by-id/usb-Razer_Razer_Raiju_V3_Pro_Wireless_-event-joystick" }
input padkeys { path = "/dev/input/by-id/usb-Razer_Razer_Raiju_V3_Pro_Wireless_-if01-event-kbd" }
input touch { path = "/dev/input/by-id/usb-Razer_Razer_Raiju_V3_Pro_Wireless_-if05-event-mouse" }
output keyboard { type = keyboard }
output gamepad {
    type    = gamepad
    name    = "InpMap Gamepad"
    emulate = "dualsense-edge"
}

map padkeys.KEY_F15 { hold BTN_GRIPL }  # back buttons of the Edge
map padkeys.KEY_F16 { hold BTN_GRIPR }
map padkeys.KEY_F17 { hold BTN_GRIPL2 }
map padkeys.KEY_F18 { hold BTN_GRIPR2 }
```

3. In KDE's touchpad settings, both the Razer touchpad and "InpMap Gamepad
   Touchpad" are switched off, so the desktop pointer stays out of the way.
4. In Steam (Steam Input on), the controller shows up as a DualSense Edge:
   - the four back buttons are bound to F9 to F12, which World of Warcraft
     uses as ordinary key bindings;
   - the right trackpad is a mouse, a click is a left click;
   - the left trackpad is a radial menu that opens on touch and selects on
     click, with a right click in its centre.

Now the right thumb moves and clicks the mouse on the touchpad while the
left thumb picks actions from a radial menu — on a controller that
Linux used to treat as a plain gamepad. Details:
[configuration.md §3.5](https://github.com/unoctanium/InpMap/blob/main/docs/configuration.md#35-emulating-a-dualsense-edge-emulate).

### A first look at the configuration

```inpmap
version 1
input kbd { path = "/dev/input/by-id/usb-4348_2.4G_Dongle-event-kbd" }
output keyboard { type = keyboard }
output gamepad { type = gamepad }

map KEY_X {  # X = keyboard Y + gamepad A
    hold KEY_Y
    hold BTN_FACE_DOWN
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
  device only (`pad.BTN_FACE_RIGHT`). Keys can be disabled.
- Sticks, analog triggers and the D-pad as buttons (`map pad.ABS_RZ above
  0.5`), also two-stage triggers; `inpmap axes` shows their live values.
- Virtual keyboards and gamepads (buttons, D-pad, sticks, triggers), and
  an emulated DualSense Edge with back paddles, Fn buttons and touchpad.
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

Version 0.5, Linux only. Verified on CachyOS / KDE Plasma (Wayland) with a
real keyboard and a Razer Raiju V3 Pro: remapping, suppression of the
original keys, unmapped input on the virtual devices (one controller in
KDE and Steam, back paddles in Steam), macros, modifiers, axes as triggers,
the configuration language, the user service, and the emulated DualSense
Edge (paddles in Steam and in World of Warcraft under Proton; the touchpad
as a split trackpad in Steam Input). Later: Windows, then GUIs.

## License

MIT, see [LICENSE](https://github.com/unoctanium/InpMap/blob/main/LICENSE). Input Remapper (GPL-3.0) served as a
functional reference only; InpMap contains no code from it.

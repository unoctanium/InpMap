# InpMap

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
output gamepad  { type = gamepad }

map KEY_X { hold KEY_Y; hold BTN_SOUTH }      # X = keyboard Y + gamepad A

map KEY_F10 {                                 # tap, double tap, long press
    on tap        { tap KEY_1 }
    on double_tap { tap KEY_2 }
    on long_press { tap KEY_3 }
}

map KEY_CAPSLOCK {                            # Caps Lock alone = Esc, with another key = Ctrl
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
- Virtual keyboards and gamepads (buttons, D-pad, sticks, triggers).
- Hold, tap, chords (`ctrl + KEY_C`), sequences with waits and random
  waits, loops, autofire, toggles, parallel branches, stick movements with
  ramps.
- Conditions: tap vs. hold, double tap, long press, "pressed alone",
  Caps/Num/Scroll Lock state, variables.
- Unmapped keys pass through unchanged; LEDs keep working; devices that
  are unplugged and plugged in again are picked up automatically.
- `inpmap input-config` finds your devices for you: press a key on the
  keyboard or gamepad you want, and it is added to the configuration.
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
| [docs/installation.md](docs/installation.md) | requirements, installation, device permissions, user service, uninstall |
| [docs/usage.md](docs/usage.md) | first configuration step by step, all commands and options, troubleshooting |
| [docs/configuration.md](docs/configuration.md) | **reference** of the configuration language: every feature with examples |
| [docs/development.md](docs/development.md) | for contributors: tests, architecture |

## Quick start

```sh
sudo pacman -S --needed python python-evdev     # Arch; other distributions: see installation.md
git clone <repository-url> InpMap && cd InpMap
python3 -m venv --system-site-packages .venv && .venv/bin/pip install -e .
.venv/bin/inpmap input-config config/local.inpmap   # pick your keyboard/gamepad, creates the file
$EDITOR config/local.inpmap                         # write your mappings
.venv/bin/inpmap check config/local.inpmap
.venv/bin/inpmap run config/local.inpmap --timeout 30
```

Device permissions may be needed first: see
[installation.md §3](docs/installation.md#3-device-permissions).

## Status

Version 0.1, Linux only. Verified on CachyOS / KDE Plasma (Wayland) with a
real keyboard and gamepad: remapping, suppression of the original keys,
passthrough, macros, modifiers and the configuration language. The user
service is new and not yet tested on real hardware. Later: Windows, then
GUIs.

## Working with Claude Code

This project is developed with Claude Code. Project state and next steps
live in `docs/STATUS.md` (rules: `CLAUDE.md` §17). Start a session in the
repository root:

```sh
cd ~/Projects/InpMap
claude
```

Then type `/session-start`. "Continue" also works, because `CLAUDE.md` is
loaded automatically and tells Claude to do the same steps:

1. Read `docs/STATUS.md`, plus the spec and `CLAUDE.md`.
2. Compare it with `git status` and `git log`. If they disagree, for example
   uncommitted changes or a step left "in progress", Claude treats the last
   session as crashed. It then checks those changes, runs the tests and
   corrects the status file.
3. Tell you in a few lines where we are, what was last done, what has been
   verified, what's next, and whether a decision or a manual test is waiting
   on you.

At the end of a session, run `/handoff`. Claude updates the status file, runs
the tests and commits completed, test-passing work (Claude also commits
automatically at each completed step; it never pushes).

## License

Not decided yet.

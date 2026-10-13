# InpMap

A configuration-driven input remapper. Mappings are written in a small
configuration language (`.inpmap` files); one physical input can drive
outputs on several virtual devices at once (e.g. a keyboard key and a gamepad
button). See `project_spec.md` for goals and roadmap.

## Status

| Area | State |
|---|---|
| Configuration loading and validation (`.inpmap`) | implemented, unit-tested |
| `inpmap check` CLI | implemented |
| Virtual keyboard / gamepad (uinput), `inpmap test-outputs` | implemented, verified on hardware |
| Mapping engine, reference-counted press/release state | implemented, unit-tested |
| Physical input, grab, passthrough, `inpmap run`, `inpmap devices` | implemented, verified on a real keyboard (spec §7 acceptance test passed) |
| Reconnect after device loss, `SYN_DROPPED` resync, LED mirroring | implemented, tested with synthetic devices |
| `inpmap udev-rules` (permission setup) | implemented; rules syntax-checked with `udevadm verify`, installation not yet tested |
| Macros (V1.1), gamepad axis outputs, `inpmap macro-trace` | implemented, verified on a real keyboard |
| Configuration language (`.inpmap`), modifiers, editor syntax files | implemented, verified on a real keyboard and gamepad (nano syntax file untested) |

## Installation (clean machine)

Requirements: Linux, Python ≥ 3.11 (so far tested on 3.14 only), and for the
recommended permission setup systemd-logind (standard on most desktops).
InpMap installs nothing system-wide except an optional udev rules file.

### 1. System packages

| Distribution | Command | Tested |
|---|---|---|
| Arch, CachyOS, Manjaro | `sudo pacman -S --needed python python-evdev git evtest` | yes (CachyOS) |
| Debian, Ubuntu | `sudo apt install python3 python3-venv python3-evdev git evtest` | not yet |
| Fedora | `sudo dnf install python3 python3-evdev git evtest` | not yet |

`evtest` is only needed for checking events. Without a distribution evdev
package, pip builds `evdev` itself; that needs a C compiler, Python headers and
kernel headers (e.g. Debian: `build-essential python3-dev linux-libc-dev`),
and the venv below is then created without `--system-site-packages`.

### 2. InpMap in a virtual environment

```sh
git clone <repository-url> InpMap      # or copy the directory
cd InpMap
python3 -m venv --system-site-packages .venv   # lets the venv use the distro's evdev
.venv/bin/pip install -e .                     # developers: -e '.[dev]' adds pytest and ruff
```

### 3. Device permissions

See [Device permissions](#device-permissions) below (one-time, needs sudo).

### 4. Configuration

```sh
cp config/example.inpmap config/local.inpmap  # git-ignored
.venv/bin/inpmap devices                      # find your device's name or /dev/input/by-id path
$EDITOR config/local.inpmap
.venv/bin/inpmap check config/local.inpmap
```

Optionally install syntax highlighting for your editor (see
[Editor support](#editor-support)).

### 5. Verify

```sh
.venv/bin/inpmap test-outputs config/local.inpmap --only gamepad   # watch with evtest
.venv/bin/inpmap run config/local.inpmap --timeout 30              # stops by itself after 30 s
```

### Uninstall

1. If you installed the udev rules: `sudo rm /etc/udev/rules.d/70-inpmap.rules`,
   then `sudo udevadm control --reload` and
   `sudo udevadm trigger --subsystem-match=input --subsystem-match=misc`.
2. If you joined the `input` group only for InpMap:
   `sudo gpasswd -d "$USER" input` (takes effect at next login).
3. Delete the InpMap directory (including `.venv`).

## Usage

```sh
.venv/bin/inpmap devices                                     # list physical devices and their /dev/input/by-id links
.venv/bin/inpmap udev-rules config/local.inpmap              # print permission rules (see Device permissions)
.venv/bin/inpmap check config/example.inpmap                 # validate, print a summary and warnings
.venv/bin/inpmap run config/local.inpmap --timeout 30        # remap; stops after 30 s, or Ctrl+C
.venv/bin/inpmap macro-trace config/example.inpmap KEY_F10 --press-at 0 --press-at 150 --hold-ms 50
                                                             # simulate a mapping, print its timeline (no devices)
.venv/bin/inpmap test-outputs config/example.inpmap          # create devices, press/release each output
.venv/bin/inpmap test-outputs config/example.inpmap --no-emit --delay 30   # only create, for inspection
```

Machine-specific configurations (`config/local*`) are git-ignored. Copy
`config/example.inpmap` and set the input device from `inpmap devices`.

### What `run` does

1. Creates the virtual output devices.
2. Opens the configured physical devices (by exact `name`, or by `path` such as
   `/dev/input/by-id/...`; ambiguous names are rejected) and checks that they
   report every mapped code.
3. Waits until no key is held on a device, then grabs it exclusively
   (`EVIOCGRAB`). From then on the desktop receives nothing from it directly.
4. Mapped inputs drive the virtual outputs; **every other event is passed
   through** a forwarding device named `InpMap forward: <device name>`, so
   the rest of the keyboard keeps working.
5. On Ctrl+C, SIGTERM, SIGHUP (terminal closed) or `--timeout`: releases held
   outputs and forwarded keys, ungrabs, removes all virtual devices.

Notes and limitations:

- Use `--timeout` for first tests. If something goes wrong, the device is
  released automatically when it expires.
- A device grabbed by another program (e.g. input-remapper) cannot be grabbed
  ("already grabbed by another program").
- Keyboard LEDs (Caps/Num/Scroll Lock): the desktop sets them on the
  forwarding device; InpMap copies the changes to the physical keyboard.
- If the kernel drops events under heavy load (`SYN_DROPPED`), key state is
  resynchronized so no key stays stuck.
- Force feedback (rumble) is not supported: virtual and forwarding devices
  declare no `EV_FF`. (With it declared but unanswered, the kernel would block
  a game's rumble request for up to 30 s.)
- If an input device disappears (unplugged, wireless sleep), its held outputs
  are released immediately and the remapper keeps running: other devices
  keep working, and the device is reopened (checked every second) and
  grabbed again once it is back with no key held. A device missing at
  startup is an error (exit code 3), since that usually means a wrong
  `name`/`path`.
- Per-device settings in the desktop (e.g. keyboard layout per device) apply
  to the forwarding device, which copies the original's vendor/product IDs.

### `test-outputs`

`test-outputs` creates the configured virtual devices, waits `--delay`
seconds (default 3), then presses and releases every mapped output code
(`--hold` seconds each; `--only DEVICE` limits it to one output device). Keyboard
output goes to the focused window like real typing, and `KEY_Y` is a key
position: on a German (QWERTZ) layout it types `z`. Watch the events with
`evtest`, e.g. `evtest` → choose "InpMap Virtual Gamepad". Ctrl+C or SIGTERM
releases all outputs and removes the devices.

Exit codes: `0` success, `1` invalid configuration, `2` command-line usage
error, `3` device error, `130` interrupted.

## Virtual devices

- **Keyboard**: declares all `KEY_*` codes and no buttons, so udev tags it
  `ID_INPUT_KEYBOARD` and libinput (KDE Wayland) uses it as a keyboard.
- **Gamepad**: standard buttons (`BTN_SOUTH/EAST/NORTH/WEST`, shoulders,
  triggers, select/start/mode, stick clicks, D-pad) plus two sticks and two
  triggers at rest, and no `KEY_*` codes. This lets udev tag it
  `ID_INPUT_JOYSTICK`, libinput ignore it, and SDL map it as a gamepad.
- Identity: bus USB, vendor `0x0001`, product `0x0001` (keyboard) / `0x0002`
  (gamepad), phys `inpmap`; no real hardware is impersonated.

## Device permissions

InpMap runs as a normal user and needs:

- **write access to `/dev/uinput`** to create the virtual and forwarding
  devices;
- **read/write access to the configured input devices** (`/dev/input/eventN`)
  to read and grab them and to set their LEDs.

Do not run InpMap as root and do not make device nodes world-writable.
Check the current state with `getfacl /dev/uinput` (look for
`user:<you>:rw-`) and `.venv/bin/inpmap devices` (reports unreadable nodes).

**Option A, recommended: per-device rules (systemd-logind `uaccess`).**
Plug in the configured devices, then:

```sh
.venv/bin/inpmap udev-rules config/local.inpmap > 70-inpmap.rules
cat 70-inpmap.rules                            # review: one rule for /dev/uinput, one per input
sudo install -m 644 70-inpmap.rules /etc/udev/rules.d/70-inpmap.rules
sudo udevadm control --reload
sudo udevadm trigger --subsystem-match=input --subsystem-match=misc
```

The rules give an ACL to the user of the active local session only, and only
for `/dev/uinput` and the configured devices (matched by kernel name plus
vendor/product ID, so other keyboards stay inaccessible). Regenerate and
reinstall them after adding input devices to the configuration. The
generated file contains the removal commands. (A future system-wide service
without a login session will need a different setup.)

**Option B: the `input` group.** `sudo usermod -aG input "$USER"`, then log in
again. Simpler, but every program you run can then read every input device,
including all keystrokes. `/dev/uinput` access is still needed separately
(Option A's first rule, or a distribution rule, e.g. Arch's `steam-devices`).

On the development machine, `/dev/uinput` access comes from rules shipped by
`steam-devices` and `kdeconnect` (same `uaccess` mechanism), and input access
from the `input` group.

## Configuration

Configurations are written in InpMap's configuration language, in files
ending in `.inpmap`. The complete reference is `docs/dsl.md`; the example
below is `config/example.inpmap`.

```
# InpMap example configuration
version 1

settings {
    key_pause = 10ms
}

let presses = 0

input kbd {
    name = "AT Translated Set 2 keyboard"     # or: path = "/dev/input/by-id/…"
}

output keyboard {
    type = keyboard
    name = "InpMap Virtual Keyboard"
}

output gamepad {
    type = gamepad
    name = "InpMap Virtual Gamepad"
}

# X holds KEY_Y and the gamepad's south button (A) at the same time
map KEY_X {
    hold KEY_Y
    hold BTN_SOUTH
}

# F9: tap Q, wait 40-60 ms, tap the gamepad's east button (B)
map KEY_F9 as combo {
    tap KEY_Q
    wait random(40ms, 60ms)
    tap BTN_EAST
    presses += 1
}

# F10: tap types 1, double tap types 2, long press types 3
map KEY_F10 {
    on tap        { tap KEY_1 }
    on double_tap { tap KEY_2 }
    on long_press { tap KEY_3 }
}

# F11: fire the gamepad's south button while held, stop at once on release
map KEY_F11 as autofire {
    cancel on release
    while held {
        tap BTN_SOUTH (pause 30ms)
    }
}

# F12: push the left stick up within 150 ms, return within 50 ms
map KEY_F12 {
    axis ABS_Y {
        target  = -1.0
        attack  = 150ms
        release = 50ms
    }
}

# Caps Lock alone is Escape; held together with another key it is Ctrl
map KEY_CAPSLOCK {
    if single {
        tap KEY_ESC
    } else {
        hold KEY_LEFTCTRL
    }
}
```

The essentials:

- **Devices**: `input` blocks select physical devices (by kernel `name` or
  `path`); `output` blocks declare virtual devices (`keyboard` or
  `gamepad`). With one input device, `map KEY_X` uses it; with several,
  write `map kbd.KEY_X`. In outputs, `keyboard.KEY_Q` names the device;
  `KEY_Q` alone is enough when only one output device can emit it.
- **Codes** are Linux names (`KEY_*`, `BTN_*`, `ABS_*`). `KEY_Y` is a key
  position, not a character; the result depends on the keyboard layout.
  Gamepad buttons are named by position: `BTN_SOUTH` (A on Xbox, Cross on
  PlayStation), `BTN_EAST`, `BTN_NORTH`, `BTN_WEST`. `BTN_X`/`BTN_Y` get a
  warning, because Linux's `BTN_X` is the top button (Y on Xbox).
- **Modifiers**: `map KEY_LEFTBRACE modifiers(ctrl, shift) { … }` fires
  only while exactly Ctrl and Shift are held (`ctrl` = either side,
  `left_ctrl`/`right_ctrl` = that side; also `shift`, `alt`, `meta`). A
  `map` without `modifiers(…)` fires only when **no** modifier is held, so
  e.g. Shift+X still types a capital X. `modifiers(ignore)` fires
  regardless. Modifiers may come from any configured device (e.g. Ctrl on
  the keyboard + a gamepad button). While such a mapping runs, the held
  modifiers are hidden from the desktop, so its output is not modified by
  them (`keep modifiers` turns this off). `settings { modifiers = ctrl, alt }`
  makes the others (here Shift and Meta) normal, mappable keys.
- **Holding**: `hold KEY_Y` keeps an output pressed while the input is held;
  in text fields the desktop's key repeat then types `yyyy`, as for a real
  held key, while games see one continuous press. `axis` holds a gamepad
  stick or trigger (sticks −1.0 … 1.0, triggers 0.0 … 1.0), optionally
  ramping in and out.
- **Sequences**: `tap`, `press`, `release`, `with KEYS { … }`, chords with
  `+` (`tap ctrl + KEY_C`), `wait 40ms` / `wait random(40ms, 60ms)`,
  `repeat`, `while held`, `toggle`, `parallel`, `move ABS_X to 1.0 over 1s`.
- **Conditions**: `if … else if … else` with `tap`, `single`, variable
  comparisons, bool variables, `capslock`/`numlock`/`scrolllock`, `not`;
  gestures `on tap` / `on double_tap` / `on long_press`; `on release { … }`.
- **Options** at the start of a mapping: `cancel on release`,
  `restart on press`, `keep modifiers`, `key_pause 5ms`,
  `max_run 60s` / `max_run none`.

Guarantees: everything a mapping presses or moves is released or re-centred
when it ends, is cancelled, loses its input device, or the remapper stops;
outputs shared by several mappings are reference-counted. Errors are
reported as `FILE:LINE:COLUMN: message`, all of a file at once, before any
device is touched. Try mappings safely with `inpmap macro-trace`; it holds
the modifiers a mapping requires (`--modifiers` to choose others) and shows
when they are hidden from the desktop.

Not supported yet: mouse movement, dual-role keys that hold back other keys
(`mod_tap`), conditions on other held inputs, named reusable blocks, the
Gaussian "humanizer", layout-aware text typing.

### Editor support

- **Kate / KWrite**: copy `editors/inpmap.xml` to
  `~/.local/share/org.kde.syntax-highlighting/syntax/` and restart the
  editor; `.inpmap` files are then highlighted (mode "InpMap").
- **nano**: add `include "/path/to/InpMap/editors/inpmap.nanorc"` to
  `~/.config/nano/nanorc` (or `~/.nanorc`). Not tested yet.

To remove: delete the copied file or the `include` line.

**Version policy:** `version` is required. Incompatible changes increase
it; older versions are then migrated explicitly or
rejected with a clear message.

## Tests

```sh
.venv/bin/python -m pytest        # unit tests; no devices or root needed
.venv/bin/ruff check . && .venv/bin/ruff format --check .
```

Tests marked `hardware` need access to `/dev/uinput` and `/dev/input` and are
excluded by default; run them with `.venv/bin/python -m pytest -m hardware`.
They only use synthetic devices they create themselves and grab every device
they emit on, so no event reaches the desktop and real hardware is not touched.

## Working with Claude Code

Project state and next steps live in `docs/STATUS.md` (rules: `CLAUDE.md`
§17). Start a session in the repository root:

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

## Event code table

`src/inpmap/_linux_codes.py` is generated from the kernel header so the core
does not depend on evdev. A test cross-checks it against the installed
`evdev.ecodes`. Regenerate after kernel header updates:

```sh
.venv/bin/python tools/gen_codes.py
```

# InpMap

A configuration-driven input remapper. Rules are defined in JSON; one physical
input can drive outputs on several virtual devices at once (e.g. a keyboard key
and a gamepad button). See `project_spec.md` for goals and roadmap.

## Status

| Area | State |
|---|---|
| JSON configuration loading and validation | implemented, unit-tested |
| `inpmap check` CLI | implemented |
| Virtual keyboard / gamepad (uinput), `inpmap test-outputs` | implemented, verified on hardware |
| Mapping engine, reference-counted press/release state | implemented, unit-tested |
| Physical input, grab, passthrough, `inpmap run`, `inpmap devices` | implemented, verified on a real keyboard (spec §7 acceptance test passed) |
| Reconnect after device loss, `SYN_DROPPED` resync, LED mirroring | implemented, tested with synthetic devices |
| `inpmap udev-rules` (permission setup) | implemented; rules syntax-checked with `udevadm verify`, installation not yet tested |

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
cp config/example.json config/local.json      # git-ignored
.venv/bin/inpmap devices                      # find your device's name or /dev/input/by-id path
$EDITOR config/local.json
.venv/bin/inpmap check config/local.json
```

### 5. Verify

```sh
.venv/bin/inpmap test-outputs config/local.json --only gamepad   # watch with evtest
.venv/bin/inpmap run config/local.json --timeout 30              # stops by itself after 30 s
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
.venv/bin/inpmap udev-rules config/local.json                # print permission rules (see Device permissions)
.venv/bin/inpmap check config/example.json
.venv/bin/inpmap run config/local.json --timeout 30          # remap; stops after 30 s, or Ctrl+C
.venv/bin/inpmap test-outputs config/example.json            # create devices, press/release each output
.venv/bin/inpmap test-outputs config/example.json --no-emit --delay 30   # only create, for inspection
```

Machine-specific configurations (`config/local*.json`) are git-ignored. Copy
`config/example.json` and set the input device from `inpmap devices`.

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
.venv/bin/inpmap udev-rules config/local.json > 70-inpmap.rules
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

## Configuration (version 1)

```json
{
  "version": 1,
  "inputs":  { "physical-keyboard": { "name": "AT Translated Set 2 keyboard" } },
  "outputs": {
    "keyboard": { "type": "keyboard", "name": "InpMap Virtual Keyboard" },
    "gamepad":  { "type": "gamepad",  "name": "InpMap Virtual Gamepad" }
  },
  "mappings": [
    {
      "id": "keyboard-x-to-y-and-gamepad-a",
      "description": "optional free text",
      "input":   { "device": "physical-keyboard", "type": "key", "code": "KEY_X" },
      "consume": true,
      "outputs": [
        { "device": "keyboard", "type": "key",    "code": "KEY_Y" },
        { "device": "gamepad",  "type": "button", "code": "BTN_SOUTH" }
      ]
    }
  ]
}
```

- **inputs**: physical devices, selected by exactly one of `name` (kernel
  device name) or `path` (absolute, e.g. `/dev/input/by-id/...-event-kbd`).
- **outputs**: virtual devices to create. `type` is `keyboard` or `gamepad`;
  `name` is optional (default `InpMap <id>`, max 79 bytes, must be unique).
- **mappings**: each maps one input to one or more outputs held while the input
  is held.
  - `type: "key"` takes `KEY_*` codes, `type: "button"` takes `BTN_*` codes.
  - Keyboard outputs accept `key`, gamepad outputs accept gamepad/joystick
    `button` codes only.
  - Codes are Linux names from `linux/input-event-codes.h`. Aliases such as
    `BTN_A` = `BTN_SOUTH` are accepted. `KEY_Y` is a key position, not a
    character; the result depends on the active keyboard layout.
  - `BTN_SOUTH` is the bottom face button (A on Xbox layouts, Cross on
    PlayStation); label mapping is convention-dependent.
  - `consume` defaults to `true`; `false` is rejected until passthrough is
    implemented.

Validation rejects unknown keys, unknown device references, unknown or
mismatched codes, duplicate ids, the same input in two mappings, and devices not
used by any mapping. All problems are reported together.

**Version policy:** `version` is required. Incompatible format changes bump it;
older versions are then migrated explicitly or rejected with a clear message.

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

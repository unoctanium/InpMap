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
| Physical input, grab, passthrough, `inpmap run`, `inpmap devices` | implemented; verified with a synthetic keyboard, real-keyboard test pending |

## Requirements

- Linux (V1 scope), Python ≥ 3.11 (developed on 3.14)
- `python-evdev` — used by the upcoming Linux backend
- For later hardware tests: read access to `/dev/input/event*` and read/write
  access to `/dev/uinput` (setup will be documented with the backend)

## Development setup

On Arch/CachyOS, `python-evdev` is available as a system package. The dev venv
reuses it instead of compiling it:

```sh
sudo pacman -S --needed python python-evdev evtest   # system packages (Arch-based)
python3 -m venv --system-site-packages .venv
.venv/bin/pip install -e '.[dev]'                     # installs inpmap, pytest, ruff
```

On other distributions, either install your distribution's evdev package the
same way, or use a plain venv and let pip build `evdev` (needs a C compiler and
kernel headers).

## Usage

```sh
.venv/bin/inpmap devices                                     # list physical devices and their /dev/input/by-id links
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
- Keyboard LEDs (Caps/Num Lock) of a grabbed keyboard do not change; the
  desktop sets them on the forwarding device.
- If an input device disappears, the remapper releases everything and exits
  (exit code 3); reconnect handling is future work.
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

- Creating virtual devices needs write access to `/dev/uinput`.
  - Check with `getfacl /dev/uinput`; look for a `user:<you>:rw-` line. On the
    development machine (CachyOS) this ACL comes from udev rules shipped by the
    `steam-devices` and `kdeconnect` packages
    (`KERNEL=="uinput", SUBSYSTEM=="misc", TAG+="uaccess"`), which grant it to
    the user of the active local session only. Other systems may lack it.
  - If missing, make sure the `uinput` module is loaded (`ls /dev/uinput`).
    Setup instructions for a narrowly scoped udev rule will follow with the
    installation script; do **not** make the node world-writable.
- Reading and grabbing physical devices (later step) needs read access to
  `/dev/input/event*`, typically via the `input` group. Membership lets every
  program of that user read all keyboards, so grant it deliberately.

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

Tests marked `hardware` (none yet) need real device access and are excluded by
default; run them with `pytest -m hardware`.

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

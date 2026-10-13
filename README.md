# InpMap

A configuration-driven input remapper. Rules are defined in JSON; one physical
input can drive outputs on several virtual devices at once (e.g. a keyboard key
and a gamepad button). See `project_spec.md` for goals and roadmap.

## Status

| Area | State |
|---|---|
| JSON configuration loading and validation | implemented, unit-tested |
| `inpmap check` CLI | implemented |
| Virtual keyboard / gamepad (uinput) | not yet |
| Reading and grabbing physical devices (evdev) | not yet |
| Mapping engine, press/release state | not yet |

Nothing in the current version opens, grabs or creates input devices.

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
.venv/bin/inpmap check config/example.json
```

Exit codes: `0` valid, `1` invalid configuration, `2` command-line usage error.

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
§17). Start a session with `claude` in the repo root and run
`/session-start`; end one with `/handoff`.

## Event code table

`src/inpmap/_linux_codes.py` is generated from the kernel header so the core
does not depend on evdev. A test cross-checks it against the installed
`evdev.ecodes`. Regenerate after kernel header updates:

```sh
.venv/bin/python tools/gen_codes.py
```

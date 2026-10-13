# Project status and session handoff

This file is the single source of truth for **where the project stands**.
A new Claude Code session must be able to continue from this file plus the
repository alone, without any earlier conversation. Keep it current (see
`CLAUDE.md`, section 17).

Last updated: 2026-10-13

## Current position

- Milestone: **V1** (Linux, no GUI)
- Spec steps (`project_spec.md` §11): 1 ✅ environment · 2 ✅ skeleton + JSON
  validation · **3 🔧 virtual devices (in progress)** · 4 mapping engine ·
  5 physical input + grab · 6 end-to-end test · 7 robustness
- Work in progress: step 3.
  - ✅ 3a: backend-independent output layer `src/inpmap/output.py`
    (`OutputBackend`/`OutputDevice` protocols, `OutputManager` that tracks held
    codes, ignores redundant transitions, releases everything on close/error,
    cleans up partially created devices). Fakes in `tests/fakes.py`.
  - ✅ 3b (code + unit tests): Linux uinput backend
    `src/inpmap/backends/linux.py` (capabilities per research below).
  - ✅ 3c (code + unit tests): `inpmap test-outputs CONFIG [--delay] [--hold]
    [--only DEV] [--no-emit]`; `hardware`-marked tests in
    `tests/test_linux_backend.py` (they grab the virtual device's own node,
    so no event reaches the desktop).
  - ⏳ 3d: hardware verification — **waiting for the user's OK** to let Claude
    run: `pytest -m hardware`; `inpmap test-outputs config/example.json
    --no-emit --delay 20` in the background plus `udevadm info` on both nodes
    (expect gamepad `ID_INPUT_JOYSTICK=1` without `ID_INPUT_KEY`, keyboard
    `ID_INPUT_KEYBOARD=1`). Then the user's manual `evtest` check of
    `inpmap test-outputs config/example.json --only gamepad` (and keyboard).
    Not installed, optional: `libinput list-devices` (package
    `libinput-tools`?) and SDL tools (`sdl2-jstest`/`testcontroller`).

## Next steps (in order)

1. **Step 3 – virtual devices** (`src/inpmap/backends/linux.py` or similar):
   - Output backend interface in the core (press/release/close), with a fake
     implementation for unit tests.
   - Linux implementation via `evdev.UInput`: one device per configured
     output, declaring only needed `EV_KEY` codes (`Config.output_codes`).
     Research first whether SDL/Steam/games need additional gamepad
     capabilities (axes, standard buttons) to recognise the virtual gamepad;
     document the result before deciding.
   - Verify the evdev 2.0.0 `UInput` API against the installed library, do not
     assume it.
   - CLI subcommand to create the devices and emit a test press/release
     (safe: grabs nothing). Running it needs user approval (not allowlisted).
   - Manual check by the user with `evtest`.
2. Step 4 – mapping engine + reference-counted state manager (pure unit tests).
3. Step 5 – physical input reading, device selection, `EVIOCGRAB`. Before the
   user's first real grab test: auto-exit timeout option, grab only the
   configured device, release on every exit path.

## Decisions (and why)

| Decision | Reason |
|---|---|
| Package name `inpmap` (spec suggested `remapper`) | matches repo, avoids generic name |
| venv with `--system-site-packages` | reuse pacman `python-evdev` 2.0.0, no C build |
| Linux code names (`KEY_X`, `BTN_SOUTH`) as canonical vocabulary; table generated into `src/inpmap/_linux_codes.py` by `tools/gen_codes.py` | core stays free of evdev (Windows later); test cross-checks against `evdev.ecodes` |
| Codes stored as ints in models | aliases (`BTN_A` = `BTN_SOUTH`) compare equal |
| JSON: `inputs` / `outputs` split instead of draft's single `devices` | draft referenced an undefined input device; inputs selected by `name` or absolute `path` |
| Event `type` `key` (`KEY_*`) / `button` (`BTN_*`); keyboard outputs take `key`, gamepad outputs take gamepad-range `button` | catches mix-ups early |
| Rejected for now: same input in two mappings, unused devices, `consume: false` | keep semantics unambiguous until passthrough/overlap design exists; may be relaxed later |
| Validator collects all problems, location + mapping id in each message | CLAUDE.md §7 diagnostics |
| Exit codes: 0 ok, 1 config invalid, 2 usage | |
| ruff (lint + format), pytest; `hardware` marker excluded by default | small toolchain |
| Auto-commit at each completed, test-passing step; never push | user decision 2026-10-13 (CLAUDE.md §13, §17) |
| `OutputManager` tracks held codes per device; reference counting of overlapping mappings belongs to the (future) state manager | separation: output layer guarantees release on close, state manager owns semantics |
| Virtual keyboard: all `KEY_*`, no `BTN_*`, no `EV_REP` | udev `input_id` sets `ID_INPUT_KEYBOARD` only if codes 1–31 are all present; libinput accepts `ID_INPUT_KEY`/`KEYBOARD` as keyboard; full set also enables later passthrough; compositors do repeat themselves |
| Virtual gamepad: BTN_SOUTH/EAST/NORTH/WEST, TL/TR/TL2/TR2, SELECT/START/MODE, THUMBL/THUMBR, DPAD_*; ABS_X/Y/RX/RY (−32768..32767, fuzz 16, flat 128), ABS_Z/RZ (0..255); no `KEY_*`; plus any mapped gamepad code | udev: joystick buttons suffice for `ID_INPUT_JOYSTICK`, but ≥4 "well-known" keys or <2 joystick buttons/axes un-detect it; libinput ignores joysticks (good: no stray input); SDL without udev (containers/Flatpak) needs ABS_X+ABS_Y; SDL auto gamepad mapping needs BTN_SOUTH and uses the standard layout. Input Remapper uses a similar set (BTN_SOUTH..BTN_THUMBR + ABS 0x00–0x05 + HAT0X/Y) |
| Device identity: BUS_USB, vendor 0x0001, product 0x0001 kbd / 0x0002 pad, phys `inpmap` | stable, no impersonation (SDL special-cases known VID/PIDs and ignores Steam's virtual pad VID/PID); SDL ignores names starting `uinput-` or containing ` Keyboard` for gamepads, so don't name a gamepad like that |
| Sources for the above (read 2026-10-13): systemd `src/udev/udev-builtin-input_id.c` (main), libinput `src/evdev.c` (main), SDL `src/joystick/linux/SDL_sysjoystick.c`, `src/core/linux/SDL_evdev_capabilities.c`, `SDL_gamepad.c` (main + SDL2), input-remapper `inputremapper/injection/global_uinputs.py` | unverified: Steam client behaviour (closed source) |
| `open()`/`close()` treat failures at cleanup boundaries: partial creation is rolled back (also on Ctrl+C), close attempts every release and every device before raising | no stuck keys, no orphan virtual devices |

## Environment facts (dev machine, verified 2026-10-13)

- CachyOS, KDE Plasma (Wayland), shell fish. Python 3.14.7.
- `python-evdev` 2.0.0 (pacman), `evtest` 1.36 installed.
- User `odo` is in group `input` → can read/grab `/dev/input/event*` without root.
- `/dev/uinput` has ACL `user:odo:rw` → virtual devices without root. Source:
  `TAG+="uaccess"` rules in `/usr/lib/udev/rules.d/60-steam-input.rules`
  (package `steam-devices`) and `40-kdeconnect-uinput.rules` (`kdeconnect`).
  Other machines will need a documented udev rule.
- No git remote configured.

## Verification status

- Unit tests: 86 passed, 3 `hardware` deselected (`.venv/bin/python -m
  pytest`), ruff clean — after step 3c.
- Hardware/integration tests: **none run yet**. evdev 2.0.0 `UInput` API
  (signature, `AbsInfo`, `write`/`syn`/`close`, `.device`) verified by
  inspecting the installed library, not by creating devices.

## Uncommitted work

- None.

## Open questions for the user

- OK to run the hardware checks of step 3d (see above)?

## Session log

- **2026-10-13** – Read spec; inspected environment; created
  `.claude/settings.json` permissions (allow/ask/deny); created venv;
  implemented skeleton, code table, models, config validator, `inpmap check`,
  example config, README, tests (commit `6df3577`). Added this handoff file,
  session-continuity rule (CLAUDE.md §17) and `/session-start` + `/handoff`
  commands (commit `c9cafef`). User authorized auto-commits at completed
  steps; README got the session start/handoff procedure. Step 3: output
  manager (3a), research on device recognition, Linux uinput backend,
  `test-outputs` CLI, hardware tests written but not yet run (3b/3c).

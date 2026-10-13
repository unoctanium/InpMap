# Project status and session handoff

This file is the single source of truth for **where the project stands**.
A new Claude Code session must be able to continue from this file plus the
repository alone, without any earlier conversation. Keep it current (see
`CLAUDE.md`, section 17).

Last updated: 2026-10-13

## Current position

- Milestone: **V1** (Linux, no GUI)
- Spec steps (`project_spec.md` §11): 1 ✅ environment · 2 ✅ skeleton + JSON
  validation · 3 ✅ virtual devices · **4 🔧 mapping engine (in progress)** ·
  5 physical input + grab · 6 end-to-end test · 7 robustness
- Work in progress: step 4 (see Next steps). Nothing half-finished on disk
  unless listed under "Uncommitted work".
- Step 3 record (complete):
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
  - ✅ 3d (automated part, run by Claude 2026-10-13, user approved):
    `pytest -m hardware` 3/3 passed; `udevadm info` while running
    `test-outputs --no-emit`: keyboard `ID_INPUT_KEY=1 ID_INPUT_KEYBOARD=1`,
    gamepad `ID_INPUT_JOYSTICK=1` (no `ID_INPUT_KEY`) — as predicted. SIGTERM
    → "outputs released and devices removed", exit 130; nodes gone afterwards.
  - ✅ 3e (user, 2026-10-13): `evtest` on the virtual gamepad showed
    `BTN_SOUTH` (304) value 1, SYN, value 0 after 0.2 s, SYN; then "No such
    device" when test-outputs removed it (expected). The virtual keyboard's
    KEY_Y arrived in the focused terminal as `y` via KDE/libinput (no
    repeat → release delivered). User layout maps KEY_Y → `y`.
  - Still unverified (optional, not blocking): KDE Game Controller page /
    SDL recognition of the gamepad, Steam behaviour.
## Next steps (in order)

1. **Step 4 – mapping engine + state manager** (pure, no hardware):
   - Neutral input event model (device id, code, press/release/repeat).
   - `state.py`: reference counts per (output device, code); output pressed on
     0→1, released on 1→0.
   - `engine.py`: rules indexed by (input device, code); press activates the
     rule's outputs, release deactivates; duplicate presses / releases
     without press ignored; repeat events of mapped inputs consumed without
     action; unmapped events reported as not handled (passthrough decided in
     step 5); `release_device(id)` for device loss; `release_all()`.
     Output errors: process all outputs, keep state coherent, then raise.
   - Unit tests per spec §9: match/no-match, multi-output, press/release,
     repeat, shared outputs (two inputs → KEY_Y), device loss, errors.
2. Step 5 – physical input reading, device selection, `EVIOCGRAB`, passthrough
   of unmapped events. Before the user's first real grab test: auto-exit
   timeout option, grab only the configured device, release on every exit
   path.
3. Step 6 – end-to-end test with physical `X` (user).

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
- Hardware tests (`pytest -m hardware`): 3 passed on the dev machine
  (device creation/identity/capabilities, press/release delivery,
  release_all delivery + device removal). Note: events queued when a device
  is destroyed cannot be read (evdev returns ENODEV), so release-on-close is
  verified as release_all (hardware) + close ordering (fake-backend tests).
- udev classification of both virtual devices verified (see 3d).
- Not yet verified: user-side `evtest` observation, SDL/KDE game controller
  recognition, Steam behaviour.

## Uncommitted work

- None.

## Open questions for the user

- None pending.

## Session log

- **2026-10-13** – Read spec; inspected environment; created
  `.claude/settings.json` permissions (allow/ask/deny); created venv;
  implemented skeleton, code table, models, config validator, `inpmap check`,
  example config, README, tests (commit `6df3577`). Added this handoff file,
  session-continuity rule (CLAUDE.md §17) and `/session-start` + `/handoff`
  commands (commit `c9cafef`). User authorized auto-commits at completed
  steps; README got the session start/handoff procedure. Step 3: output
  manager (3a), research on device recognition, Linux uinput backend,
  `test-outputs` CLI (3b/3c); hardware tests + udev classification passed
  (3d, one test fixed: cannot read events after device destruction).
  User's evtest check passed (3e) → step 3 complete. Started step 4.

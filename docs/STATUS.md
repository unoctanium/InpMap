# Project status and session handoff

This file is the single source of truth for **where the project stands**.
A new Claude Code session must be able to continue from this file plus the
repository alone, without any earlier conversation. Keep it current (see
`CLAUDE.md`, section 17).

Last updated: 2026-10-13

## Current position

- Milestone: **V1** (Linux, no GUI)
- Spec steps (`project_spec.md` §11): 1 ✅ environment · 2 ✅ skeleton + JSON
  validation · 3 ✅ virtual devices · 4 ✅ mapping engine ·
  **5 ✅ code / ⏳ real-device test** · 6 end-to-end test · 7 robustness
- **Now: waiting for the user's real-keyboard test (step 5/6)**, see Next
  steps 1. Instructions were given in chat on 2026-10-13.
- Step 5 done (code + tests): `src/inpmap/input.py` (InputSource/
  InputBackend protocols, InputError, InputDeviceLost),
  `src/inpmap/runtime.py` (Runtime: outputs → open inputs → wait for
  released keys → drain → grab → loop; cleanup on every path; StopReason;
  CleanupError), `src/inpmap/backends/linux_input.py` (selector resolution,
  own-device exclusion, code check, forwarding uinput via
  `UInput.from_device` without EV_SYN/EV_FF/EV_REP and with the original's
  vendor/product, EBUSY → "already grabbed", ENODEV → InputDeviceLost,
  forwarded held keys released on close, `list_input_devices()`), CLI
  `inpmap devices [--all]`, `inpmap run CONFIG [--timeout S]` (SIGINT,
  SIGTERM, SIGHUP → orderly stop). Tests: `tests/test_runtime.py`,
  `tests/test_linux_input.py`, `tests/test_cli.py`.
- Step 4 record: `models.InputEvent`/`KeyAction` (neutral events),
  `state.OutputRefCounts` (reference counts), `engine.MappingEngine`
  (`handle()` returns True if the original must be suppressed; ignores
  duplicate presses / releases of inactive inputs; consumes repeats;
  `release_device()`, `release_all()`; output errors raised after all outputs
  were processed, counts stay balanced). Tests: `tests/test_state.py`,
  `tests/test_engine.py`.
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

1. **User's real-keyboard test** (spec §7 acceptance test):
   - Identify which node of the user's wireless keyboard sends letter keys:
     candidates from `inpmap devices` are `2.4G Dongle` (event7,
     `/dev/input/by-id/usb-4348_2.4G_Dongle-event-kbd`) and
     `2.4G Dongle Keyboard` (event8,
     `/dev/input/by-id/usb-4348_2.4G_Dongle-if01-event-kbd`); user checks with
     `evtest` which one reports `KEY_X` (code 45).
   - Create git-ignored `config/local.json` from `config/example.json` with
     that `path`.
   - `inpmap run config/local.json --timeout 30` with `evtest` on the virtual
     gamepad; expected: pressing X types `y`, gamepad shows BTN_SOUTH 1/0,
     no `x` appears, other keys work normally, everything released after
     timeout/Ctrl+C.
   - Record actual results here.
2. Step 7 – robustness: SYN_DROPPED resync, hotplug/reconnect, LED
   forwarding to the physical keyboard, startup diagnostics.
3. Later: macro spec (V1.1), systemd service.
- Also known on this machine: the user's controller is a Razer Raiju V3 Pro
  (`Generic X-Box pad`, event11; it also exposes Keyboard/Mouse/Touchpad
  interfaces).

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
| Exit codes: 0 ok, 1 config invalid, 2 usage, 3 device error, 130 interrupted (test-outputs) | |
| Runtime startup order: outputs → open inputs (verify mapped codes) → wait until no key held → discard queued events → grab | never leave a grab behind on failure; avoid stuck keys in the desktop; tiny window between drain and grab accepted |
| Device loss: release that device's outputs, clean up everything, exit with error (no reconnect in V1) | controlled and visible; hotplug is step 7 |
| Forwarding device copies the original's vendor/product/version/bustype, omits EV_REP | per-device desktop settings and SDL mappings keep working; no double key repeat |
| SIGHUP handled like SIGINT/SIGTERM in `run` | closing the terminal must still clean up |
| Machine-specific configs as git-ignored `config/local*.json` | keep personal device paths out of the repo |
| ruff (lint + format), pytest; `hardware` marker excluded by default | small toolchain |
| Auto-commit at each completed, test-passing step; never push | user decision 2026-10-13 (CLAUDE.md §13, §17) |
| `OutputManager` tracks held codes per device; reference counting of overlapping mappings belongs to the (future) state manager | separation: output layer guarantees release on close, state manager owns semantics |
| Engine semantics: press→activate, release→deactivate, repeat consumed w/o action, duplicate press and release-of-inactive ignored, shared outputs reference-counted per (output device, code) | spec §6 (no premature release), robust to missed/duplicated events |
| Passthrough: one forwarding uinput device per grabbed input, mirroring its capabilities; every event the engine does not consume is forwarded unchanged | user decision 2026-10-13 (option 1); keeps media keys, combo-device parts, EV_MSC etc.; same approach as Input Remapper |
| Same input in two mappings is rejected by config, so the engine keeps one rule per (input device, code) | simple, unambiguous |
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

- Unit tests: 136 passed, 4 `hardware` deselected (`.venv/bin/python -m
  pytest`), ruff clean — after step 5.
- Hardware tests (`.venv/bin/python -m pytest -m hardware`): 4 passed on the
  dev machine (2026-10-13): virtual device creation/identity/capabilities,
  press/release delivery, release_all delivery + device removal, and
  `test_runtime_remaps_suppresses_and_forwards` (real runtime vs. a
  *synthetic* uinput "physical" keyboard: X → KEY_Y + BTN_SOUTH
  press/release, KEY_A forwarded, X not forwarded). No leftover devices.
- Lesson (twice): events on a destroyed uinput device cannot be read
  (ENODEV) — test cleanup ordering with stubs/fakes instead.
- udev classification of both virtual devices verified (see 3d); user saw
  virtual gamepad BTN_SOUTH in evtest and virtual KEY_Y in KDE (3e).
- Not yet verified: grab of the user's **real** keyboard and suppression of
  the original X (step 5/6 test), SDL/KDE game controller recognition, Steam.

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
  User's evtest check passed (3e) → step 3 complete. Step 4 (engine, ref
  counts, 22 new tests) complete. User chose passthrough option 1. Step 5
  implemented (runtime, Linux input backend, forwarding, `devices`/`run`
  CLI) and verified with a synthetic keyboard; real-keyboard test handed to
  the user.

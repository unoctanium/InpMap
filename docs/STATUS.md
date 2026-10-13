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
  5 ✅ physical input + grab · **6 ✅ end-to-end test passed** · 7 robustness
  (next)
- **Spec §7 acceptance test PASSED on the user's real keyboard
  (2026-10-13)**: physical X (event7 '2.4G Dongle') → `y` typed, original
  `x` suppressed; evtest on "InpMap Virtual Gamepad" (bus 0x3 vendor 0x1
  product 0x2) showed BTN_SOUTH 1/0 with SYN_REPORTs; releases paired.
- Fixed after the test: evtest showed `EV_FF` on the virtual gamepad
  (python-evdev default max_effects=96). Kernel blocks a game's rumble upload
  up to 30 s waiting for the uinput owner (uinput.c,
  `wait_for_completion_timeout(..., 30 * HZ)`), so all virtual and
  forwarding devices now use `max_effects=0`; hardware test asserts no EV_FF.
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
   - ✅ User identified the letter-key node with evtest: **event7, '2.4G
     Dongle'**, `/dev/input/by-id/usb-4348_2.4G_Dongle-event-kbd` (declares
     KEY_X). (event8 '2.4G Dongle Keyboard' is the other interface.)
   - ✅ `config/local.json` (git-ignored, exists only on the dev machine)
     created with that `path` and the example mapping; `inpmap check` OK.
     Recreate it from `config/example.json` if missing.
   - First real run (user, 2026-10-13): X typed `y` (mapping fired, X
     suppressed). Findings:
     1. Holding X gives `yyyy` in text fields: KDE's own autorepeat of a held
        key (we hold KEY_Y; physical repeats are swallowed; virtual keyboard
        has no EV_REP). Correct for "hold" semantics; games see one press.
        User wondered about a "one y only" case → that is a different mode
        ("tap": press+release on input press). Proposed for V1.1 macro work.
     2. User saw no BTN_SOUTH in evtest and suggested BTN_A (same code 304,
        alias, would change nothing). Diagnosis by Claude: virtual gamepad is
        NOT grabbed by anyone (EVIOCGRAB test), Steam not running; only
        `systemsettings` had it open. Runtime path X→BTN_SOUTH is covered by
        the passing hardware E2E test. Likely evtest was attached to another
        device (or started before the gamepad existed). ✅ Retest (run first,
        then evtest on event26 "InpMap Virtual Gamepad") showed BTN_SOUTH
        correctly — confirmed.
   - ✅ Acceptance test passed (see Current position).
   User's order (2026-10-13): **robustness → installation → tap mode**.
2. ✅ **Step 7 – robustness**:
   - ✅ 7a reconnect: `runtime.py` is a per-device state machine (`_Slot`:
     opened → waiting for no key held → grabbed; lost → release its outputs,
     close, retry `open` every `reconnect_interval` (1 s) → re-grab). Events
     of not-yet-grabbed devices are read and discarded. Startup with a
     missing device stays a hard error. Other devices keep working.
     Linux `wait()` sleeps when no source is open. Tests: fake-based
     reconnect/shared-output/lost-while-waiting tests; hardware test
     `test_runtime_survives_unplug_and_reconnects` (synthetic keyboard
     destroyed while X held → KEY_Y and BTN_SOUTH released; recreated → X
     remaps again) passed 2026-10-13.
   - ✅ 7b SYN_DROPPED (`LinuxInputSource.read`): tracks key state seen in
     the stream (`_down`, initialized from EVIOCGKEY at open); on
     SYN_DROPPED ignores events up to and including the next SYN_REPORT,
     then compares with `active_keys()` and synthesizes missed
     releases/presses (+ SYN_REPORT) as normal events, so the engine and
     the forwarder stay consistent. Only keys are resynced, not axes.
     Stub-based tests in `tests/test_linux_input.py` (can't provoke a real
     overflow reliably).
   - ✅ 7c LED feedback: verified by probe that EV_LED written to a uinput
     device's event node arrives on the owner's (non-blocking) uinput fd.
     `LinuxInputBackend.wait()` also selects on each forwarder's fd and calls
     `pump_feedback()`, which applies EV_LED to the physical device
     (`set_led`; failure logged once). Hardware test
     `test_led_state_set_on_forwarder_reaches_physical_keyboard` passed.
     Not yet checked with the user's real keyboard (may have no LEDs).
   - **Step 7 complete.**
3. ✅ Installation for other PCs (2026-10-13):
   - `inpmap udev-rules CONFIG` (`src/inpmap/backends/linux_setup.py`, no
     evdev needed): reads world-readable sysfs, prints a `uaccess` rule for
     /dev/uinput (same as steam-devices/kdeconnect) and one rule per
     configured input matching `ATTRS{name}` + `ATTRS{id/vendor}` +
     `ATTRS{id/product}` (attribute names verified with `udevadm info -a`),
     file `70-inpmap.rules` (must sort before 73-seat-late.rules where
     uaccess is applied). Output for `config/local.json` passed
     `udevadm verify` (systemd 262). **Not tested: actually installing it**
     (needs sudo; on the dev machine access already exists via `input`
     group and steam/kdeconnect rules, so the effect isn't observable here).
   - README: clean-machine installation (packages per distro: Arch tested,
     Debian/Fedora names untested), venv, permissions Option A (rules,
     recommended) / Option B (`input` group), configuration, verification,
     uninstall.
   - Decided against an install shell script: steps are few and
     transparent; the generator + documented commands cover it.
   - Python ≥ 3.11 baseline only statically checked (ruff target py311);
     only 3.14 available on the dev machine.
4. ✅ Tap output mode (user's idea, 2026-10-13): optional per-output
   `"mode": "hold" | "tap"` (`models.OutputMode`). Tap = output pressed on
   input press, released by a timer after `engine.TAP_DURATION` (20 ms),
   independent of the input; shares reference counts with hold outputs
   (never releases a key another mapping holds). Engine got a non-blocking
   timer queue (`tick()`, `next_deadline()`), driven by the runtime loop —
   reusable for V1.1 macros. `release_all()` finishes pending taps;
   `release_device()` lets them finish. Tests: config, engine (fake clock),
   runtime, hardware `test_tap_output_released_while_input_still_held`.
   ⏳ Optional user check: `config/local-tap.json` (git-ignored) = X taps Y
   + holds BTN_SOUTH; expected one `y` per press however long X is held.
5. 🔧 **V1.1 macro engine** (user decision 2026-10-13), in this order:
   a. ✅ Research done (agent read IR main @ 1f770e5c: docs, macros/**,
      macro/combination handlers, event reader, global uinputs, keyboard
      layout, shared dict, all macro tests).
   b. ✅ `docs/macros-research.md` written: IR behaviour summary, design
      principles, format options, groups A (inspired), B (not
      implemented/deferred), C (new), questions Q1–Q10.
   c. ✅ Discussion complete; all decisions in macros-research.md §5.
   d. ✅ Spec `docs/macros.md` approved by the user (max_run_ms 1 min). 🔧 Implementation in progress (config stays version 1, all
      additions optional). Implement with
      tests (suggested order: settings/variables/axis outputs in config →
      macro step model + validation → executor on the engine timer queue →
      runtime integration incl. if_single/LEDs → `macro-trace` → hardware
      tests → README).
      - ✅ A (2026-10-13): model `src/inpmap/macros.py` (steps, KeyRef,
        durations, axes table ABS_X..ABS_RZ), `MappingRule.axes/.macros`,
        `Config.settings/.variables`, parser `src/inpmap/config_macros.py`
        (all spec validation rules, JSON paths in errors), axis outputs in
        `config.py`; macro keys included in `Config.output_codes`. Tests:
        `tests/test_config_macros.py` (67, incl. all spec §10 examples
        parsed from docs/macros.md). **Temporary guard** in `cli._cmd_run`
        rejects configs with macros/axes until the executor exists — remove
        in step C.
      - ✅ B (2026-10-13): `OutputDevice.set_axis(code, fraction)`,
        `OutputManager.set_axis/axis()` (skips unchanged values, resets
        moved axes to rest in `release_all`/`close`), Linux `axis_raw`
        scaling (sticks −32768..32767 per side, triggers 0..255),
        hardware test `test_axis_values_reach_virtual_gamepad_and_reset_on_close`.
      - ✅ C (2026-10-13): `src/inpmap/axes.py` (holder stacks, most recent
        wins, `batch()` defers writes so a restart doesn't jump to rest),
        `src/inpmap/macro_runtime.py` (MacroRun with generator fibers
        yielding Sleep/WaitRelease/WaitPress/WaitSingle/Join; ownership of
        keys and axes; finish/cancel/restart/toggle/release_steps/max_run),
        engine rewritten as MacroHost (callback timer queue next to tap
        queue, `_offer_other_press` before processing a key so if_single
        acts first, plain axis outputs = internal HoldAxis macros with
        restart). Tests: `tests/test_macro_runtime.py` (35, fake clock).
        Bug found+fixed: float error at ramp end caused an endless
        near-zero sleep loop → ramp snaps to target when ≤1e-9 s remain.
      - ✅ D (2026-10-13): `InputSource.leds()` (Linux: EVIOCG LED bits →
        `Led`), runtime passes the trigger device's LEDs to the engine;
        temporary guard in `cli._cmd_run` **removed** — `inpmap run`
        executes macros and axis outputs. Runtime tests: timed macro +
        if_led through the loop; if_single on another device acts before
        that key is forwarded.
      - ✅ E (2026-10-13): `inpmap macro-trace CONFIG MAPPING [--hold-ms]
        [--press-at MS]... [--other-key-at MS]... [--until-ms] [--seed]
        [--led NAME]...` (`src/inpmap/trace.py`): real engine on a fake
        clock with a recording sink; inputs marked `>>`. Tests:
        `tests/test_trace.py`.
      - ✅ F (2026-10-13): hardware test
        `test_macro_and_axis_output_through_runtime` (real runtime,
        synthetic keyboard: X → macro taps KEY_A on keyboard + BTN_EAST on
        gamepad; W → ABS_Y ramps monotonically to −32768 and back to 0).
        Hardware suite 9/9 passed.
      - ✅ G (2026-10-13): README sections "Gamepad axes" and "Macros"
        (+ status row, macro-trace usage, not-yet-supported list);
        `config/example-macros.json` (tested as valid);
        `inpmap check` summary lists axes, macros and variables.
        `config/local-macros.json` (git-ignored) = example with the user's
        keyboard path.
      - ✅ **User test on the real keyboard passed (2026-10-13, "all
        works")** with
        `inpmap run config/local-macros.json --timeout 60`: F9 combo (q +
        gamepad B), F10 tap/double/long → 1/2/3, F11 autofire gamepad A while
        held, F12 left stick up (evtest), CapsLock alone → Esc / with another
        key → Ctrl; X → y + gamepad A as before.
   **V1.1 macro engine complete.**
   License note: Input Remapper is GPL-3.0; we implement independently and
   do not copy code.
6. After macros: systemd service (step 9; runtime already separate from CLI
   with signal handling, no unit file yet).
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
| Device loss: release that device's outputs, close it, keep running and reopen it every second (by the same name/path selector); missing at startup = error | step 7a; daemon-friendly (wireless sleep, replug), while config mistakes still fail fast |
| Forwarding device copies the original's vendor/product/version/bustype, omits EV_REP | per-device desktop settings and SDL mappings keep working; no double key repeat |
| SIGHUP handled like SIGINT/SIGTERM in `run` | closing the terminal must still clean up |
| Machine-specific configs as git-ignored `config/local*.json` | keep personal device paths out of the repo |
| Tap duration fixed at 20 ms (not configurable yet) | games sampling once per frame (16.7 ms at 60 fps) must see it; Input Remapper uses a similar keystroke delay (10 ms default); timing configuration belongs to the V1.1 macro design |
| Timed actions via engine timer queue + runtime loop, never sleeping in the event path | CLAUDE.md §8 (no blocking the input loop); foundation for macros |
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

- Unit tests: 398 passed, 10 `hardware` deselected (`.venv/bin/python -m
  pytest`), ruff clean — after DSL step S4. Hardware: 10 passed (S3).
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
- Real keyboard (user, 2026-10-13): grab, suppression of X, KEY_Y output,
  BTN_SOUTH output, passthrough of other keys all confirmed.
- Not yet verified: SDL/KDE game controller recognition (systemsettings had
  the virtual gamepad open, result not reported), Steam, behaviour of the
  remapper on device unplug with real hardware.

## Uncommitted work

- None.

## Open questions for the user

- Config format (user decision 2026-10-13): **custom DSL** becomes the
  user-facing format (see `docs/config-usability.md` "Decision",
  `docs/format-comparison.md`). **Agreed order:** (1) write complete DSL
  spec `docs/dsl.md` (✅ draft written, commit 9ceee44) → (2) ✅ **spec approved by the user 2026-10-13** (published for review at https://claude.ai/artifact/QNvunSJmmSuaDfq3TcdqNZ). Review history: user replaced combination triggers by **one key + modifier state** (`modifiers(ctrl, shift)`, §4.0; exact match + `modifiers(ignore)`, re-press after the run, `meta` as default modifier — all confirmed), bool conditions and ctrl/shift/alt/meta aliases now specified; complete spec approved.
  (3) 🔧 Implementing the DSL, sub-steps (commit after each):
  ✅ S1 parser (`src/inpmap/dsl/parser.py`: lark LALR grammar, basic
  lexer + post-lexer allowing `else` on its own line, syntax errors as
  FILE:LINE:COLUMN; `lark` added to dependencies; tests
  `tests/test_dsl_parser.py` incl. all complete spec examples);
  ✅ S2 compiler (2026-10-13, commit d9d72d2): `src/inpmap/dsl/compiler.py`
  (`compile_text`, `load`) → existing config data → `parse_config`, every
  validator message mapped to FILE:LINE:COLUMN; model fields
  `InputTrigger.modifiers/any_modifiers`, `MappingRule.keep_modifiers`,
  `Settings.modifiers` + validation; ids may contain '+'; BTN_X/BTN_Y
  warning; spec "More examples" fixed (device prefixes with two inputs);
  tests `tests/test_dsl_compiler.py` incl. 24 trace-equivalence checks of
  the DSL example vs. `config/example-macros.json`. **TEMPORARY guards** in
  `engine.MappingEngine.__init__` and `cli._cmd_run` reject modifier
  triggers — remove them in S3.
  ✅ S3 (2026-10-13): `src/inpmap/modifiers.py` (ModifierState, exact
  matching, sides, `ignore`, specificity, ties → first defined), engine
  keeps several rules per key and chooses at press time; masking: the
  engine asks the runtime (`InputControl`) to `mask` held modifiers before
  the outputs and `unmask` once the trigger is released and all its runs
  finished; `InputSource.mask/unmask` (Linux: release/re-press on the
  forwarder, hide physical events meanwhile). Behaviour changes, all
  deliberate and tested: a trigger without `modifiers(…)` fires only with no
  modifier held; releases/repeats of keys whose press was passed through
  are passed through; the forwarder never gets a release/repeat for a key
  it does not have down; when any mapping requires modifiers, every input
  device counts as used (keyboard configured only for Ctrl). Temporary
  guards removed. Tests: `tests/test_modifiers.py`, runtime + Linux source
  masking tests, hardware test
  `test_modifiers_hidden_on_forwarder_before_output_and_restored` (kernel
  timestamps: modifiers released on the forwarder before the virtual
  Enter). ⏳ Real-desktop check of case 1 (KDE sees a plain Enter) pending
  with the user after S4.
  ✅ S4 (2026-10-13): `src/inpmap/loading.py` (format by extension:
  `.inpmap` → DSL, else JSON); all CLI commands use it and print warnings
  to stderr; `check` shows trigger modifiers; `config/example.inpmap`
  (= spec §11, tested identical); `config/local.inpmap` (git-ignored; the
  user's mappings + case 1 `bracket_combo` + case 2 `alternate` on the
  Razer pad); `.gitignore` now `config/local*`; editor files
  `editors/inpmap.xml` (Kate; verified with `ksyntaxhighlighter6` via a
  temporary XDG_DATA_HOME — loads and highlights) and
  `editors/inpmap.nanorc` (**not verified**: nano offers no batch check).
  ✅ S5 (2026-10-13): README rewritten language-first (intro, status,
  install step 4, usage, "Configuration" with the example, modifiers,
  guarantees, "Editor support", short "JSON (machine format)");
  `docs/macros.md` points to `docs/dsl.md`.
  **DSL implementation complete.** Next: (a) user's real-keyboard test of
  `config/local.inpmap` (case 1 bracket_combo: KDE must see a plain Enter;
  case 2 alternate on the Razer pad; modifiers); (b) user decides whether
  to drop JSON completely (then remove JSON loading/docs, update
  `project_spec.md` + `CLAUDE.md` §7); (c) systemd service.
  (previous plan text:) S3 engine/runtime: modifier
  matching (exact, sides, ignore, specificity) and temporary release /
  re-press of modifiers on the forwarding devices, hardware test; S4 CLI
  loads `.inpmap`, example configs + local configs in the DSL, Kate and
  nano syntax files; S5 README/docs. → (3) implement
  the DSL → (4) user decides whether to drop JSON completely; if so, remove
  JSON support and update CLAUDE.md and all documentation → (5) systemd
  service. `project_spec.md`/`CLAUDE.md` still say "JSON only" until step 4.

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
  CLI) and verified with a synthetic keyboard. User identified event7,
  `config/local.json` created; first real run: hold → KDE repeat explained,
  missing BTN_SOUTH turned out to be evtest on the wrong device; retest
  passed → **spec §7 acceptance test passed**. Removed EV_FF from all
  virtual devices (30 s rumble block risk).

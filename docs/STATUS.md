# Project status and session handoff

This file is the single source of truth for **where the project stands**.
A new Claude Code session must be able to continue from this file plus the
repository alone, without any earlier conversation. Keep it current (see
`CLAUDE.md`, section 17).

Last updated: 2026-10-13

## Current position

- Milestone: **V1** (Linux, no GUI)
- Spec steps (`project_spec.md` §11): 1 ✅ environment · 2 ✅ skeleton + JSON
  validation · **3 ⏭ virtual devices (next)** · 4 mapping engine · 5 physical
  input + grab · 6 end-to-end test · 7 robustness
- Work in progress: none. Working tree is clean except for uncommitted items
  listed below.

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

## Environment facts (dev machine, verified 2026-10-13)

- CachyOS, KDE Plasma (Wayland), shell fish. Python 3.14.7.
- `python-evdev` 2.0.0 (pacman), `evtest` 1.36 installed.
- User `odo` is in group `input` → can read/grab `/dev/input/event*` without root.
- `/dev/uinput` has ACL `user:odo:rw` → virtual devices without root.
  Other machines will need a documented udev rule.
- No git remote configured.

## Verification status

- Unit tests: 65 passed (`.venv/bin/python -m pytest`), ruff clean — at commit
  `6df3577`.
- Hardware/integration tests: **none run yet** (nothing touches devices).

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
  commands.

# Macro semantics (V1.1)

Status: implemented and verified on real hardware (2026-10-13). Based on
the decisions in `docs/macros-research.md` §5; Input Remapper served as
functional reference, this is our own design.

This document defines **what macros do**. How they are **written** is part
of the configuration language: `docs/dsl.md` §4–§5 (statements, options,
conditions, gestures). Until 2026-10-13 macros were also written as JSON;
that format was removed (see git history before the JSON removal commit).

## 1. Overview

A mapping whose body contains statements other than `hold`/`axis` runs as a
macro when its input is pressed. Statements can press keys and buttons and
move gamepad axes on **any configured output device**, wait, loop, branch
and use variables. Everything is validated when the configuration is
loaded.

Guarantees:

1. Everything a macro presses or moves is **owned** by that run and is
   released / re-centred when the run ends, is cancelled, when its input
   device disappears, and on shutdown. No stuck keys.
2. Outputs shared with other mappings or runs are reference-counted (keys)
   or stacked (axes, §3), so one run never releases what another holds.
3. Macros never block input processing; all waiting uses the engine's timer
   queue.

## 2. Execution model

- A trigger **press** starts a run of the mapping. A press while the run
  is still going goes first to a statement waiting for it (`if tap`,
  gestures), then to `toggle`; otherwise `restart on press` cancels and
  restarts the run, or the press is ignored (default).
- A trigger **release** is delivered to the run: `hold`, `axis`,
  `while held`, `if tap`, `if single` and `on release` react to it. With
  `cancel on release`, the remaining statements are cancelled at once.
- Autorepeat events of the trigger are ignored.
- Statements that take no time run immediately one after another within
  the same input event; anything that waits is scheduled on the timer
  queue. Input processing never waits for a macro.
- `on release { … }` runs after the main statements have finished (or were
  cancelled) and the trigger has been released.
- A run ends when its statements (and `on release`) are done; then it
  releases everything it still owns. Cancelled runs (`cancel on release`,
  `restart on press`, `max_run`, device loss, shutdown) stop immediately
  and release everything they own; `max_run` (default 60 s) logs a warning.
- When the trigger's input device disappears, its runs are cancelled.
- While a mapping with `modifiers(…)` runs, its modifiers are hidden from
  the desktop (`docs/dsl.md` §4.0 rule 7).

## 3. Ownership of outputs

- **Keys/buttons**: every press by a run adds a holder in the engine's
  reference counts; the key goes down on the first holder and up when the
  last holder releases, together with plain `hold` outputs.
- **Axes**: each axis has a stack of holders (plain `axis` mappings and
  macro runs). The most recent holder's value is written; when it lets go,
  the next one's value applies again (ramping over the leaving holder's
  release time if any), or the axis returns to rest. A restart does not
  make the axis jump to rest in between.

## 4. Timing

- **Key pause** (`settings { key_pause }`, per mapping `key_pause`, per
  statement `(pause …)`, default 10 ms): after every press and every
  release made by `tap`, `press`, `release`, `hold`, `with`.
- **Random waits** `random(a, b)`: uniformly distributed, a ≤ b.
- **Axis ramps** update every 10 ms, linearly, and end exactly on target.
- **Loops** (`while held`, `toggle`) take at least 1 ms per pass, even if
  their statements take no time; the current pass always completes.
- Each key event is written as its own SYN frame. Timer precision is a few
  milliseconds; durations are lower bounds.

## 5. Validation

All rules of `docs/dsl.md` §7, reported as `FILE:LINE:COLUMN: message`
before any device is touched.

## 6. Tools

`inpmap macro-trace FILE MAPPING [--hold-ms N] [--press-at MS …]
[--other-key-at MS …] [--modifiers NAMES|none] [--led NAME …]
[--until-ms N] [--seed N]` runs one mapping against a simulated clock and
recording outputs and prints the timeline, e.g.

```
      0.0 ms  >> input pressed
      0.0 ms  keyboard   KEY_Q            down
     10.0 ms  keyboard   KEY_Q            up
     76.9 ms  gamepad    BTN_EAST         down
```

No devices are created. By default it holds the modifiers the mapping
requires and shows when they are hidden from the desktop.

## 7. Not in this version

Mouse movement and wheel (needs a mouse output device), `mod_tap`
(dual-role keys holding back other input), conditions on other held inputs,
named reusable blocks, the humanizer (Gaussian durations), curves other
than linear, and layout-aware text typing.

## 8. For developers

The compiler (`src/inpmap/dsl/compiler.py`) translates statements into the
step model in `src/inpmap/macros.py` (e.g. gestures into nested `IfTap`,
a non-blocking `hold` followed by more statements into `Parallel`); the
executor is `src/inpmap/macro_runtime.py`. The correspondence is listed in
`docs/dsl.md` §8.

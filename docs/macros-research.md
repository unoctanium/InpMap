# Macros: research and proposal (V1.1)

Status: **for discussion**, nothing decided yet. After agreement this becomes
the basis for the specification `docs/macros.md`.

Source studied: Input Remapper, main branch at commit `1f770e5c`
(2026-10-13): `readme/macros.md`, `readme/usage.md`, `readme/examples.md`,
`inputremapper/injection/macros/**`, `mapping_handlers/macro_handler.py`,
`combination_handler.py`, `event_reader.py`, `global_uinputs.py`,
`keyboard_layout.py`, `ipc/shared_dict.py` and all of
`tests/unit/test_macros/`. Input Remapper is GPL-3.0-or-later: we describe
behaviour only and implement independently; no code is copied.

## 1. How Input Remapper macros work

### Language and attachment

- A macro is a text string of chained function calls in the mapping's
  output field, e.g. `key(1).hold(key(2)).key(3)`. Child macros are passed
  unevaluated (`repeat(3, key(a))`). Keyword arguments, `#` comments,
  `$variable` reads, quoted strings. Hand-written parser, no `eval`.
- Whether the field is a macro or a plain key is guessed heuristically
  (contains `+`, or `(` and `)`); `a + b` is shorthand for `hold_keys(a, b)`.
- Each mapping has **one** `target_uinput` (`keyboard`, `gamepad`, `mouse`,
  `keyboard + mouse`). A macro cannot write to two devices; the combined
  `keyboard + mouse` device is upstream's workaround.
- Invalid mappings are logged and **skipped**; the rest of the preset loads.
  Variable values are type-checked only at runtime; an error there aborts
  the rest of the macro and is only logged.

### Execution model

- Python asyncio. Trigger press starts the macro if it is not running; a
  press while running is not a restart, but is passed on to tasks that
  watch the trigger (double tap, toggle).
- Trigger release does **not** cancel anything. Only `hold`, `hold_keys`,
  `if_tap`, `if_single`, `mod_tap`, `mouse`, `wheel` react to it.
  Sequences (`key`, `wait`, `repeat`, `modify`) always run to completion.
- Key autorepeat events never reach macros.
- Cleanup: the handler remembers the last value written per code and
  releases pressed ones only when the **whole injection stops**. A
  `key_down` without `key_up`, or a crashed macro, leaves the key pressed
  until then (their troubleshooting advice: unplug the device). No
  coordination with other mappings pressing the same key.
- Pause between key events: `macro_key_sleep_ms` per mapping, default 0
  (docs still claim 10 ms). Each event is its own SYN frame.

### Functions (complete list in the current code)

| Function | What it does |
|---|---|
| `key(sym)` | press, pause, release, pause |
| `key_down(sym)`, `key_up(sym)` | press only / release only |
| `wait(ms[, max_ms])` | sleep; random between `ms` and `max_ms` if given |
| `repeat(n, macro)` | run `macro` n times |
| `modify(mod, macro)` | press `mod`, run `macro`, release `mod` |
| `hold()` / `hold(sym)` / `hold(macro)` | wait for release / hold key until release / loop macro while held |
| `hold_keys(a, b, ...)` | press all, wait for release, release in reverse (`a + b`) |
| `toggle(macro)` | first press starts looping `macro`, second press stops it |
| `parallel(m1, m2, ...)` | run macros concurrently, continue when all finished |
| `event(type, code, value)` | write one raw event (not checked against the device) |
| `mouse(dir, speed[, accel])`, `mouse_xy(x, y[, accel])` | move pointer while held (60 Hz) |
| `wheel(dir, speed)` | scroll while held (incl. hi-res events) |
| `set(var, value)`, `add(var, n)` | write / increment a variable |
| `if_eq(a, b, then, else)` | compare values (Python `==`, `"1" != 1`) |
| `if_capslock(then, else)`, `if_numlock(...)` | check LED state of the source devices |
| `if_tap(then, else, timeout=300)` | `then` if released within timeout, else `else` at the timeout |
| `if_single(then, else[, timeout])` | `then` if released before any other key is pressed |
| `mod_tap(default, modifier, term=200)` | dual-role key; **holds back other keys** until decided, then replays them in order |
| deprecated: `k m r e w h`, `ifeq` | legacy aliases |

### Variables

- One global store for the whole daemon (all devices, all presets), kept in
  a separate process; each access goes through a pipe with a 20 ms timeout
  that **silently returns "unset"** on timeout. Not persistent.
- Values: str, int, float, None; types decided by how the literal was
  written; checked only when used.

### Keys and layout

`key(a)` is resolved through `xmodmap -pke` of the user session (saved to a
file for the service): it means "the keycode the current layout puts `a`
on", not "type the character a". No Unicode or text typing.

### Other lessons from their tests and docs

- Their `hold(macro)` finishes the current iteration after release to
  avoid half-pressed keys; `if_single` ignores releases and joystick
  movement of other inputs; `mod_tap` tests follow QMK's tap-hold cases.
- Gamepad axes are only reachable through raw `event(EV_ABS, ...)`;
  nothing re-centres an axis when a macro stops.
- Docs warn that anti-cheat software may detect macros.

## 2. Our starting point

- A mapping already has one input and **several outputs on several
  devices** (`hold` / `tap` modes), with reference counting so overlapping
  mappings never release each other's keys.
- The engine has a non-blocking timer queue driven by the runtime loop and
  a fake clock in tests. Macros can build on this instead of asyncio, which
  keeps them deterministic and testable without sleeping.
- Codes are Linux names (`KEY_Y`, `BTN_SOUTH`) validated at load; the whole
  configuration is rejected on any error.

## 3. Proposal for discussion

### 3.1 Design principles (proposed)

1. **Every key a macro presses is owned and always released**: when the
   step sequence ends, when the macro is cancelled, on device loss, on
   shutdown. Shared keys use the existing reference counts. (Fixes
   upstream's stuck-key problem.)
2. **Every step names its output device** (with a default per macro), so
   one macro can drive keyboard and gamepad together.
3. **Everything is validated at load**: codes against the device kind,
   step structure, variable names and types. No runtime type errors.
4. **Explicit trigger semantics**: what happens on release (finish or
   cancel) and on a new press while running (ignore, restart, ...) is part
   of the macro definition, with safe defaults.
5. **Deterministic execution** on the engine's timer queue; never blocking
   the input loop; testable with a fake clock.

### 3.2 Format question: structured JSON or text language?

| | A: structured JSON steps (proposed) | B: text language like upstream |
|---|---|---|
| Example | `{"steps": [{"tap": "KEY_A"}, {"wait_ms": 100}]}` | `"macro": "key(KEY_A).wait(100)"` |
| Validation | same validator as the rest; exact error paths | needs its own parser and error messages |
| Readability | verbose for long macros | compact |
| Future GUI | maps directly to a form/tree editor | GUI must parse and re-print text |
| Multi-device | `"device": "gamepad"` per step | needs new syntax |

Recommendation: **A**, possibly with a compact shorthand for the most common
step (`{"tap": "KEY_A"}`) to keep it readable.

### 3.3 Group A: inspired by Input Remapper (adapted)

| # | Function (working name) | Adaptation |
|---|---|---|
| A1 | `tap` (upstream `key`) | press + release with the macro's key pause; device per step |
| A2 | `press` / `release` (upstream `key_down`/`key_up`) | owned keys, guaranteed release at macro end (no stuck keys) |
| A3 | `wait` (fixed or random range) | timer queue, not sleep |
| A4 | `repeat(n, steps)` | static `n`, or from a variable |
| A5 | `while_held(steps)` (upstream `hold(macro)`) | loop while the trigger is held; finish current iteration |
| A6 | `hold_keys(keys)` (upstream `hold_keys`, `hold(sym)`) | hold keys on any devices until trigger release |
| A7 | `with_keys(keys, steps)` (upstream `modify`) | keys held around a step sequence, e.g. Ctrl around taps |
| A8 | `parallel(branches)` | run branches together, continue when all done |
| A9 | `toggle(steps)` | second press stops the loop |
| A10 | `if_tap(then, else, timeout)` | tap vs. long press on the trigger |
| A11 | `if_single(then, else, timeout)` | released before any other input is pressed; across **all** our input devices |
| A12 | variables: `set`, `add`, `if_eq` | runtime-local store (no IPC); see N6 |
| A13 | `if_led(capslock/numlock/scrolllock)` | generalises `if_capslock`/`if_numlock` |
| A14 | per-macro key pause (`key_pause_ms`) | default to discuss (upstream 0; our tap uses 20 ms) |

### 3.4 Group B: intentionally not implemented (or deferred)

| # | Upstream feature | Reason |
|---|---|---|
| B1 | text language, `a + b` shorthand, heuristic macro detection | replaced by structured JSON (if A is chosen) |
| B2 | deprecated aliases (`k`, `m`, `r`, `e`, `w`, `h`, `ifeq`) | legacy only |
| B3 | global cross-process variable store with 20 ms timeout | one in-process store per runtime; no silent failures |
| B4 | raw `event(type, code, value)` | unchecked against devices; replaced by typed steps |
| B5 | keysym names via `xmodmap` (`key(a)`) | depends on X11 tools and the session layout; we keep Linux key codes. Layout-aware text typing would be a separate feature |
| B6 | skipping invalid mappings and loading the rest | we reject the whole configuration (fail fast, clear errors) |
| B7 | `mouse`, `mouse_xy`, `wheel` | no mouse output device yet (V1 excluded mouse movement); add together with a mouse device, see question Q3 |
| B8 | `mod_tap` with holding back and replaying other keys | needs input buffering and reordering across mappings; complex and latency-relevant; candidate for a later version |

### 3.5 Group C: new, not in Input Remapper

| # | Feature | Why |
|---|---|---|
| N1 | steps on **several devices** in one macro | our core idea: keyboard + gamepad from one trigger |
| N2 | `on_release` behaviour: `finish` (default?) or `cancel` (stop at once and release all owned keys) | upstream can't cancel; useful for "fire while held" sequences |
| N3 | re-trigger policy: `ignore` / `restart` / `queue` | upstream only ignores; restart is useful for combos |
| N4 | separate `on_press` and `on_release` step lists | e.g. a sequence on press and a different one on release |
| N5 | gamepad axis steps: `axis(ABS_X, -32768)`, held while the trigger is held and **re-centred automatically** (e.g. WASD → left stick) | upstream only has raw events and no re-centring |
| N6 | variables declared in the config with type and initial value; shared by all macros in the runtime | static validation, predictable start state |
| N7 | `if_held(input)`: condition on another physical input being held | chords and simple "layers" without full layer support |
| N8 | safety limits: maximum run time / iteration count for loops (default on) | a mistaken macro can't run forever |
| N9 | `inpmap macro-trace CONFIG MAPPING [--hold MS]`: prints the timeline of output events without devices | test and debug macros safely |
| N10 | macro library: named macros defined once, referenced from several mappings | reuse, shorter configs |

## 4. Questions to decide

- **Q1** Format: structured JSON (A) or text language (B)?
- **Q2** Which of A1–A14 go into V1.1? Which are later?
- **Q3** Mouse output device (B7) in V1.1, or later?
- **Q4** Gamepad axis output (N5) in V1.1? (V1 excluded analog *inputs*.)
- **Q5** Default on trigger release: `finish` or `cancel`?
- **Q6** Default on a new press while running: `ignore`, `restart` or `queue`?
- **Q7** `if_single` and `mod_tap`: include, defer, or drop?
- **Q8** Variables (A12/N6) in V1.1 or later?
- **Q9** Which of N2–N10 do you want, and anything missing?
- **Q10** Default key pause between macro key events (0, 10 or 20 ms)?

## 5. Decisions (discussion with the user, 2026-10-13)

- **Q1** structured JSON steps — agreed.
- **Q2** A1–A14 in V1.1 (variables per Q8) — agreed.
- **Q3** mouse output later, together with a mouse device — agreed.
- **Q4** gamepad axis output in V1.1 — agreed. User asked for gradients.
  Proposed (awaiting confirmation): values as fractions (−1..1 sticks,
  0..1 triggers), ramps with `over_ms` (linear first, curves later),
  `hold_axis` with `attack_ms` / `release_ms`, automatic re-centring on
  release/cancel/device loss; two holders of one axis: most recent wins,
  previous value restored when it lets go.
- **Q5** explained (finish vs cancel); proposed `finish` default with
  `"on_release": "cancel"` per macro — awaiting confirmation.
- **Q6** `ignore` default, `restart` optional — agreed.
- **Q7** explained; proposed `if_single` in V1.1 (no holding back needed in
  our single-threaded engine), `mod_tap` later — awaiting confirmation.
- **Q8** variables in V1.1, declared in the config — agreed.
- **Q9** N1–N6, N8, N9 now; N7, N10 later — agreed.
- **Q10** user disagrees with a fixed pause: 10 ms default is fine for now,
  but pauses must become configurable globally and per key/step, and
  durations must later support Gaussian randomization (humanizer).
  Proposed: `key_pause_ms` global → per macro → per step now; every
  duration accepts a number or an object
  `{"mean_ms", "stddev_ms", "min_ms", "max_ms"}`; humanizer implementation
  now or later — awaiting the user's choice.

# Macro specification (V1.1)

> This document specifies macro **semantics** and their **JSON** structure.
> For writing configurations by hand, use the configuration language
> (`docs/dsl.md`); it compiles into exactly this model (coverage table in
> `docs/dsl.md` §8).

Status: **approved by the user (2026-10-13)**; implementation in progress. Based on the decisions in
`docs/macros-research.md` §5. Input Remapper served as functional reference;
this is our own design.

## 1. Overview

A macro is a sequence of steps that runs when a mapping's input is pressed.
Steps can press keys and buttons and move gamepad axes on **any configured
output device**, wait, loop, branch and use variables. Macros are written as
structured JSON and are fully validated when the configuration is loaded.

Guarantees:

1. Everything a macro presses or moves is **owned** by that macro run and is
   released / re-centred when the run ends, is cancelled, when its input
   device disappears, and on shutdown. No stuck keys.
2. Outputs shared with other mappings or macros are reference-counted (keys)
   or stacked (axes, §6), so one run never releases what another holds.
3. Macros never block input processing; all waiting uses the engine's timer
   queue.

## 2. Configuration changes

All additions are optional, so existing version 1 configurations stay valid
and `version` stays `1`.

### 2.1 Top-level `settings`

```json
"settings": { "key_pause_ms": 10 }
```

| Field | Type | Default | Meaning |
|---|---|---|---|
| `key_pause_ms` | number ≥ 0 | 10 | pause after each key press and each key release made by a macro |

### 2.2 Top-level `variables`

```json
"variables": { "mode": 0, "speed": 1.5, "layer": "game", "armed": false }
```

Each variable is declared with its initial value; the JSON type of that value
fixes the variable's type: `int`, `float`, `string` or `bool`. Variables are
shared by all macros of the running remapper and reset to their initial
values when it starts. They are not persisted.

### 2.3 Gamepad axis outputs (plain mappings)

Besides keys and buttons, a mapping output can hold a gamepad axis:

```json
{ "device": "gamepad", "type": "axis", "code": "ABS_X", "value": -1.0,
  "attack_ms": 0, "release_ms": 0 }
```

| Field | Meaning |
|---|---|
| `code` | `ABS_X`, `ABS_Y`, `ABS_RX`, `ABS_RY` (sticks) or `ABS_Z`, `ABS_RZ` (triggers) |
| `value` | sticks −1.0 … 1.0, triggers 0.0 … 1.0 |
| `attack_ms` | ramp time from the current value to `value` after the input is pressed (default 0) |
| `release_ms` | ramp time back after the input is released (default 0) |

Axis outputs are always `hold` (no `mode` field). Values are fractions of the
device's range and converted to raw values by the backend.

### 2.4 Macro outputs

A macro is an entry in a mapping's `outputs` list:

```json
{
  "id": "combo",
  "input": { "device": "physical-keyboard", "type": "key", "code": "KEY_F1" },
  "outputs": [
    { "macro": {
        "device": "keyboard",
        "on_release": "finish",
        "on_retrigger": "ignore",
        "key_pause_ms": 10,
        "max_run_ms": 60000,
        "steps": [ { "tap": "KEY_A" }, { "wait_ms": 100 }, { "tap": "KEY_B" } ],
        "release_steps": [ ]
    } }
  ]
}
```

| Field | Default | Meaning |
|---|---|---|
| `steps` | required | steps run when the input is pressed |
| `device` | none | default output device for key references without `device` |
| `on_release` | `"finish"` | input released while `steps` still run: `finish` lets them run to the end; `cancel` stops at once and releases everything the run owns |
| `on_retrigger` | `"ignore"` | input pressed again while the macro runs: `ignore` (unless a step waits for it, §4.4) or `restart` (cancel, then start again) |
| `key_pause_ms` | `settings.key_pause_ms` | default pause for key steps of this macro |
| `max_run_ms` | 60000 (1 min) | the run is cancelled (with a warning) when it lasts longer; `null` = no limit |
| `release_steps` | none | steps run when the input is released (§4.3) |

A mapping may combine plain outputs and macros; all start on the same press.

## 3. Values and references

**Key reference**: `"KEY_A"` (uses the macro's `device`) or
`{ "code": "BTN_SOUTH", "device": "gamepad" }`. The code must suit the
device kind exactly as for plain outputs (keyboards: `KEY_*`; gamepads:
gamepad buttons). A key reference without `device` in a macro without
`device` is an error.

**Key list**: one key reference or a list of them; may mix devices.

**Duration** (milliseconds): a number ≥ 0, `{ "min": 50, "max": 150 }`
(uniformly random in the range, inclusive), or `{ "var": "name" }` (an int
or float variable). Reserved for later (humanizer):
`{ "mean": 80, "stddev": 15, "min": 50, "max": 150 }`.

**Count**: an integer 0 … 10000, or `{ "var": "name" }` (int variable,
clamped to 0 … 10000 at runtime).

## 4. Steps

Every step is a JSON object with exactly one **step key**, plus the optional
fields listed for it. Unknown fields are errors.

### 4.1 Keys

| Step | Optional fields | Behaviour |
|---|---|---|
| `{"tap": KEYS}` | `device`, `pause_ms` | press all keys in order, then release them in reverse order, with a pause after every press and every release. A list taps a chord (e.g. Ctrl+C) |
| `{"press": KEYS}` | `device`, `pause_ms` | press and keep pressed (owned); pause after each press |
| `{"release": KEYS}` | `device`, `pause_ms` | release keys this run pressed; releasing a key the run does not own is an error at load if statically visible, ignored at runtime otherwise |
| `{"hold_keys": KEYS}` | `device` | press, wait until the input is released, release in reverse order. If the input is already released, press and release immediately |
| `{"with_keys": KEYS, "steps": [...]}` | `device` | press keys, run `steps`, release keys in reverse order (e.g. Shift around taps) |

`pause_ms` (a duration) overrides the macro's `key_pause_ms` for that step.
Keys still owned when the run ends are released then.

### 4.2 Axes (gamepad)

| Step | Fields | Behaviour |
|---|---|---|
| `{"axis": "ABS_X", "to": 1.0}` | `device`, `over_ms` (duration, default 0) | move the axis to `to`, linearly over `over_ms`; the step ends when the target is reached. The value is held (owned) until changed again or the run ends |
| `{"hold_axis": "ABS_X", "value": 1.0}` | `device`, `attack_ms`, `release_ms` | move to `value` over `attack_ms`, hold until the input is released, return over `release_ms` |

Ramps update the axis every 10 ms. When the run ends, owned axes return to
their previous holder's value or to rest (sticks 0.0, triggers 0.0)
immediately unless a `release_ms` applies.

### 4.3 Timing and flow

| Step | Fields | Behaviour |
|---|---|---|
| `{"wait_ms": DURATION}` | — | wait |
| `{"repeat": COUNT, "steps": [...]}` | — | run `steps` COUNT times |
| `{"while_held": [...]}` | — | run the steps repeatedly while the input is held; the current iteration always completes |
| `{"toggle": [...]}` | — | only allowed as the single step of `steps`: first press starts repeating the steps, the next press stops after the current iteration. `on_release`/`on_retrigger` do not apply |
| `{"parallel": [[...], [...]]}` | — | run branches simultaneously; continue when all have finished |

`release_steps`: when the input is released, they start after `steps`
finished (`on_release: finish`) or after `steps` were cancelled
(`on_release: cancel`). With `release_steps`, a new press while they run is
handled by `on_retrigger`.

### 4.4 Conditions

Each has `then` and `else` step lists; both optional (empty = nothing).

| Step | Extra fields | Chooses `then` when |
|---|---|---|
| `{"if_tap": {...}}` | `timeout_ms` (default 300) | input held when the step starts: it is released within the timeout. Not held: it is pressed **and** released within the timeout (enables double-tap by nesting). `else` runs at the timeout |
| `{"if_single": {...}}` | `timeout_ms` (optional) | the input is released before any other key or button is pressed on **any** input device. If another press comes first, `else` runs **before** that press is processed; at the timeout `else` runs too |
| `{"if_eq": {...}}` | `var`, `value` (same type as the variable) | the variable equals `value` |
| `{"if_led": {...}}` | `led`: `capslock`, `numlock`, `scrolllock` | that LED is on, as reported by the input device of the mapping's trigger (devices without LEDs: always `else`) |

A press of the input while the macro runs goes to an `if_tap` that is
waiting for a press; otherwise `on_retrigger` applies.

### 4.5 Variables

| Step | Behaviour |
|---|---|
| `{"set": {"var": "mode", "value": 1}}` | assign; `value` must have the variable's type |
| `{"add": {"var": "count", "value": 1}}` | add to an int or float variable (int + int stays int) |

## 5. Execution model

- A trigger **press** starts a run of each macro output of the mapping
  (subject to `on_retrigger`); a **release** is delivered to the run
  (`hold_keys`, `hold_axis`, `while_held`, `if_tap`, `if_single`,
  `on_release`, `release_steps`). Autorepeat events are ignored.
- Steps that take no time run immediately one after another within the same
  input event; anything that waits is scheduled on the timer queue. Input
  processing never waits for a macro.
- Each key event is written as its own SYN frame. Timer precision is a few
  milliseconds; durations are lower bounds.
- Loops (`while_held`, `toggle`) take at least 1 ms per iteration, even if
  their steps take no time.
- A run ends when its steps (and `release_steps`) are done; then it releases
  everything it still owns. Cancelled runs (`on_release: cancel`,
  `on_retrigger: restart`, `max_run_ms`, device loss, shutdown) stop
  immediately and release everything they own.
- When the trigger's input device disappears, its runs are cancelled.

## 6. Ownership of outputs

- **Keys/buttons**: every press by a run adds a holder in the engine's
  reference counts; the key goes down on the first holder and up when the
  last holder releases, together with plain `hold`/`tap` outputs.
- **Axes**: each axis has a stack of holders (plain axis outputs and macro
  runs). The most recent holder's value is written; when it lets go, the
  next one's value is restored (ramping over the leaving holder's
  `release_ms` if any), or the axis returns to rest.

## 7. Validation (at load)

Rejected with a message naming the mapping id and the JSON path:

- unknown step keys, fields, or several step keys in one object;
- key references to unknown devices, codes not suitable for the device,
  missing `device` without a macro default;
- axis codes not on the gamepad, values out of range;
- durations < 0, `min > max`, counts outside 0 … 10000;
- unknown variables, `set`/`if_eq` values of the wrong type, `add` on
  non-numbers, `{"var": …}` of the wrong type for a duration or count;
- `toggle` not being the only step;
- `release` of a key the macro never presses;
- empty `steps`.

## 8. Tools

`inpmap macro-trace CONFIG MAPPING_ID [--hold-ms N] [--press-at MS ...]
[--other-key-at MS] [--until-ms N]` runs the mapping's macros against a
simulated clock and recording outputs, and prints the resulting timeline,
e.g.

```
     0.0 ms  keyboard  KEY_A  down
    10.0 ms  keyboard  KEY_A  up
   120.0 ms  keyboard  KEY_B  down
```

No devices are created. Random durations use a fixed seed (`--seed`).

## 9. Not in this version

Mouse movement and wheel (needs a mouse output device), `mod_tap`
(dual-role keys holding back other input), conditions on other held inputs,
named reusable macros, the humanizer (Gaussian durations), curves other than
linear, and layout-aware text typing.

## 10. Examples

Ctrl+C on one key:

```json
{ "macro": { "device": "keyboard", "steps": [ { "tap": ["KEY_LEFTCTRL", "KEY_C"] } ] } }
```

Autofire on the gamepad while held, stopping immediately on release:

```json
{ "macro": { "device": "gamepad", "on_release": "cancel",
  "steps": [ { "while_held": [ { "tap": "BTN_SOUTH", "pause_ms": 30 } ] } ] } }
```

W pushes the left stick up gently (plain output, no macro):

```json
{ "device": "gamepad", "type": "axis", "code": "ABS_Y", "value": -1.0,
  "attack_ms": 150, "release_ms": 50 }
```

CapsLock alone is Escape, combined with another key it is Ctrl:

```json
{ "macro": { "device": "keyboard", "steps": [ { "if_single": {
    "then": [ { "tap": "KEY_ESC" } ],
    "else": [ { "hold_keys": "KEY_LEFTCTRL" } ] } } ] } }
```

Tap, double tap and long press on one key:

```json
{ "macro": { "device": "keyboard", "steps": [ { "if_tap": {
    "then": [ { "if_tap": {
        "then": [ { "tap": "KEY_2" } ],
        "else": [ { "tap": "KEY_1" } ] } } ],
    "else": [ { "tap": "KEY_3" } ] } } ] } }
```

Combo on keyboard and gamepad together:

```json
{ "macro": { "steps": [
    { "tap": { "code": "KEY_Q", "device": "keyboard" } },
    { "wait_ms": { "min": 40, "max": 60 } },
    { "tap": { "code": "BTN_EAST", "device": "gamepad" } } ] } }
```

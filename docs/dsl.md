# InpMap configuration language (DSL) — specification draft

Status: **draft for review** (2026-10-13). Not implemented. Based on the
user's sketch and the decisions in `docs/config-usability.md` and
`docs/format-comparison.md`.

## 1. Goals and principles

- Readable and short to write by hand in Kate or nano.
- **Same capabilities and guarantees as today's model** (`docs/macros.md`):
  the language is translated into the existing validated model, so the
  engine, runtime, ownership of outputs and all safety rules are unchanged.
- **Strict**: every error is reported with file, line and column before any
  device is touched; nothing is guessed silently.
- Declarative: no general-purpose programming (no functions, no arbitrary
  expressions, no file or system access).

File extension: `.inpmap` (e.g. `config/example.inpmap`).

## 2. Lexical structure

- Encoding UTF-8. Line endings LF or CRLF.
- **Comments**: `#` to the end of the line (not inside strings).
- **Statements** end at a line break or `;`. Line breaks inside `( )` are
  ignored, so long option lists may span lines.
- **Blocks**: `{ … }`. A block may be written on one line:
  `on tap { tap KEY_1 }`.
- **Names** (devices, variables, mapping names): `[A-Za-z_][A-Za-z0-9_]*`,
  case-sensitive, not a keyword. (No `-` or `.`, so `a.b` and `x -= 1` are
  never ambiguous.)
- **Codes**: Linux names as today: `KEY_*`, `BTN_*` (keys and buttons),
  `ABS_X`, `ABS_Y`, `ABS_Z`, `ABS_RX`, `ABS_RY`, `ABS_RZ` (gamepad axes).
- **Numbers**: `42`, `-1`, `0.5`, `-1.0`.
- **Durations**: a number directly followed by a unit, no space: `40ms`,
  `1.5s`. Units: `ms`, `s`. Durations are never negative.
- **Strings**: `"…"` with escapes `\"`, `\\`, `\n`, `\t`.
- **Booleans**: `true`, `false`.
- **Keywords** (reserved, cannot be names): `version settings let input
  output map as hold tap press release with wait random repeat while held
  toggle parallel branch on double_tap long_press if else single not and
  keep modifiers left_ctrl right_ctrl left_shift right_shift left_alt
  right_alt
  within after axis move to over cancel restart key_pause max_run none
  true false capslock numlock scrolllock ctrl shift alt meta`.

## 3. File structure

```
version 1

settings { … }                 # optional
let NAME = VALUE               # zero or more variables
input NAME { … }               # one or more physical input devices
output NAME { … }              # one or more virtual output devices
map TRIGGER [as NAME] { … }    # one or more mappings
```

`version` must be the first statement. All other top-level statements may
appear in any order and reference each other regardless of order.

### 3.1 `version`

`version 1` — version of this language. Incompatible changes increase it;
older versions are then migrated explicitly or rejected with a message
naming the supported versions.

### 3.2 `settings`

```
settings {
    key_pause = 10ms
}
```

| Setting | Type | Default | Meaning |
|---|---|---|---|
| `key_pause` | duration | `10ms` | pause after every key press and release made by `tap`, `press`, `release`, `hold`, `with` |
| `modifiers` | list of `ctrl`, `shift`, `alt` (`meta` open) | `ctrl, shift, alt` | keys treated as modifiers (§4.0); all others are normal keys |

### 3.3 Variables

```
let presses = 0          # int
let speed = 1.5          # float
let delay = 50ms         # duration
let layer = "game"       # string
let armed = false        # bool
```

The literal fixes the type. Variables are shared by all mappings of the
running remapper, start with their initial value at every start, and are not
saved.

### 3.4 Input devices

```
input kbd {
    name = "AT Translated Set 2 keyboard"
}
input pad {
    path = "/dev/input/by-id/usb-Razer_Razer_Raiju_V3_Pro_Wireless_-event-joystick"
}
```

Exactly one of `name` (kernel device name, must be unique among connected
devices) or `path` (absolute, usually a `/dev/input/by-id/…` link). Find
both with `inpmap devices`.

### 3.5 Output devices

```
output keyboard {
    type = keyboard
    name = "InpMap Virtual Keyboard"
}
output gamepad { type = gamepad }
```

`type` is `keyboard` or `gamepad`. `name` is optional (default
`InpMap <NAME>`), at most 79 bytes, unique.

## 4. Mappings

```
map TRIGGER [as NAME] {
    OPTIONS...
    STATEMENTS...
}
```

- **TRIGGER**: `INPUT.CODE` (e.g. `kbd.KEY_F9`, `pad.BTN_EAST`), or just
  `CODE` if exactly one input device is declared, optionally followed by
  `modifiers(…)` (§4.0).
- **NAME** (optional): the mapping's name in messages and for
  `inpmap macro-trace`. Default: the trigger as written (`KEY_F9`,
  `pad.BTN_EAST`).
- Each trigger may be mapped only once.
- The original input event is always suppressed (consumed).

### 4.0 Modifiers

A trigger is always **one** key or button. It can additionally require a
**modifier state**: which modifier keys must be held when the key is
pressed. (Arbitrary key combinations were considered and rejected as too
edge-case-prone; see `docs/combinations-research.md` and §12.)

```
map KEY_A modifiers(right_shift) { … }
map KEY_LEFTBRACE modifiers(ctrl, shift) { … }
map KEY_P modifiers(right_ctrl, right_alt) { … }
map pad.BTN_SOUTH modifiers(ctrl) { … }      # Ctrl from the keyboard
map pad.BTN_SOUTH { … }                      # the same button without modifiers
```

Rules:

1. **Modifier keys**: by default `ctrl`, `shift`, `alt` (left and right
   keys each). `settings { modifiers = ctrl, alt }` chooses the set; a key
   that is not in the set (e.g. Shift above) is a normal key and can be
   mapped. A modifier key cannot be a trigger. *(Open: whether `meta` is a
   default modifier.)*
2. **Names**: `ctrl`, `shift`, `alt` = either side; `left_ctrl`,
   `right_ctrl`, `left_shift`, `right_shift`, `left_alt`, `right_alt` =
   exactly that side.
3. **Exact match**: the mapping fires when the key is pressed while the
   required modifiers are held and **no other modifier** is held. A trigger
   without `modifiers(…)` fires only when no modifier is held; otherwise
   the key passes through unchanged (e.g. Shift+A stays a capital A).
4. **Specificity**: if several mappings of the same key match (e.g.
   `modifiers(ctrl)` and `modifiers(right_ctrl)` with right Ctrl held), the
   more specific side wins. Two mappings with the same key and the same
   modifier requirement are an error.
5. **Shared state**: the modifier state is the union of all configured
   input devices, so a gamepad button can be combined with Ctrl on the
   keyboard. Modifiers of devices that are not configured (not grabbed)
   are not visible.
6. **Timing**: modifiers count as they are at the moment the key is
   pressed. Pressing or releasing modifiers while the key is held does not
   affect the running mapping. The trigger release is the release of the
   key itself.
7. **Passed-through modifiers**: modifier keys always pass through to the
   desktop. While a mapping with `modifiers(…)` runs, its required
   modifiers are **temporarily released** on the forwarding device, so its
   output is not modified (Ctrl+Shift+[ → a plain Enter). When the
   mapping's run has **completely** finished (including `on release`),
   modifiers that are still physically held are pressed again on the
   forwarding device, so e.g. a following Ctrl+C works. Keys typed during
   the run arrive without those modifiers. Mapping option `keep modifiers`
   disables the temporary release (then e.g. Shift applies to the output).
8. **Autorepeat** of the key is ignored, as for all triggers.

### 4.1 Output references

A key, button or axis is written `DEVICE.CODE` (`keyboard.KEY_Q`,
`gamepad.BTN_EAST`, `gamepad.ABS_Y`). The `DEVICE.` part may be omitted
when exactly one declared output device can emit the code: a keyboard for
`KEY_*`, a gamepad for gamepad buttons and axes. Otherwise it is an error
that names the candidates.

Gamepad buttons: the positional names `BTN_SOUTH`, `BTN_EAST`, `BTN_NORTH`,
`BTN_WEST` are the documented standard. `BTN_A` (= south) and `BTN_B`
(= east) are accepted. `BTN_X` and `BTN_Y` are accepted with a **warning**,
because in Linux `BTN_X` is the top button (labelled Y on Xbox) and `BTN_Y`
the left one (labelled X).

A **chord** joins keys with `+`: `KEY_LEFTCTRL + KEY_C`. Keys of a chord may
be on different devices.

**Modifier aliases** `ctrl`, `shift`, `alt`, `meta` stand for the left or
right key (`KEY_LEFTCTRL`/`KEY_RIGHTCTRL`, …). In a **trigger** an alias
matches either side. In an **output** an alias presses the **left** key
(`tap ctrl + KEY_C` = `tap KEY_LEFTCTRL + KEY_C`). Note: on many layouts the
right Alt key is AltGr, so `alt` in a trigger also matches AltGr.

### 4.2 Mapping options

Options come first in the body, one per line:

| Option | Meaning | Default |
|---|---|---|
| `keep modifiers` | with `modifiers(…)` only: do not temporarily release the passed-through modifiers while the mapping runs (§4.0) | release them |
| `cancel on release` | when the input is released while statements still run, stop at once and release/re-centre everything this mapping holds | finish the statements |
| `restart on press` | a new press while statements still run cancels them and starts again | the press is ignored (unless a statement waits for it, §6) |
| `key_pause DURATION` | key pause for this mapping | `settings.key_pause` |
| `max_run DURATION` / `max_run none` | cancel (with a warning) if the statements run longer | `60s` |

## 5. Statements

Statements in a mapping body run in order when the input is pressed. They
may press keys and buttons and move axes on any output device.

### 5.1 Holding

| Statement | Meaning |
|---|---|
| `hold KEYS` | press now; keep pressed until the input is released; **does not wait** — the next statement runs at once |
| `axis REF { target = V  attack = D  release = D }` | move the axis to `V` (over `attack`), keep it there until the input is released, then return (over `release`); **does not wait**. `attack`/`release` are optional (default `0ms`). One-line form: `axis REF -1.0 (attack 150ms, release 50ms)` |

Axis values: sticks (`ABS_X`, `ABS_Y`, `ABS_RX`, `ABS_RY`) −1.0 … 1.0,
triggers (`ABS_Z`, `ABS_RZ`) 0.0 … 1.0.

A mapping that contains only `hold` and `axis` statements and no options
behaves exactly like today's plain outputs.

### 5.2 Keys in sequences

| Statement | Meaning |
|---|---|
| `tap KEYS [(pause D)]` | press the keys in order, release them in reverse order, with a pause after every press and every release |
| `press KEYS [(pause D)]` | press and keep pressed until `release` or the end of the mapping's run |
| `release KEYS [(pause D)]` | release keys pressed by `press`; releasing a key never pressed in this mapping is an error |
| `with KEYS { … }` | press the keys, run the block, release the keys in reverse order (e.g. Shift around taps) |

`(pause D)` overrides the key pause for that statement. Keys still pressed
when the mapping's run ends are released then.

### 5.3 Waiting and axes in sequences

| Statement | Meaning |
|---|---|
| `wait D` | wait; `D` is a duration, `random(D1, D2)` (uniform, D1 ≤ D2) or a duration variable |
| `move REF to V [over D]` | move an axis to `V`, linearly over `D`; the statement ends when the target is reached; the axis keeps the value until changed again or the run ends (then it returns to rest) |

### 5.4 Loops and concurrency

| Statement | Meaning |
|---|---|
| `repeat N { … }` | run the block N times (`N`: integer 0 … 10000 or an int variable) |
| `while held { … }` | repeat the block while the input is held; the current pass always completes |
| `toggle { … }` | must be the only statement of the mapping (options allowed): the first press starts repeating the block, the next press stops it after the current pass |
| `parallel { branch { … } branch { … } … }` | run branches at the same time; continue when all have finished |

Loops take at least 1 ms per pass.

### 5.5 Conditions

```
if CONDITION { … }
else if CONDITION { … }
else { … }
```

| Condition | True when |
|---|---|
| `tap [within D]` | input held now: released within D; not held now: pressed **and** released within D (default 300ms). Decided at the latest after D |
| `single [within D]` | the input is released before any other key or button is pressed on any input device (the `else` branch runs **before** that other key is processed); with `within D`, also false after D |
| `NAME == VALUE`, `NAME != VALUE` | variable comparison; `VALUE` must have the variable's type |
| `NAME` (a bool variable) | the variable is `true` |
| `capslock`, `numlock`, `scrolllock` | that LED is on, on the trigger's input device (devices without LEDs: false) |
| `not CONDITION` | negation |

### 5.6 Gestures: tap, double tap, long press

```
on tap        { … }
on double_tap { … }
on long_press { … }
```

A group of these handlers (any subset, any order, at most one each)
distinguishes how the input was pressed. Default window: 300ms; change it
with `within D` on `tap`/`double_tap` and `after D` on `long_press`; all
handlers of a group must use the same window.

| Pressed like this | Runs |
|---|---|
| press and release within the window, no second press within the window | `on tap` |
| two quick taps within the window each | `on double_tap` (without a `double_tap` handler, a second tap is a new `tap`) |
| held longer than the window | `on long_press` |

Handlers without a match do nothing. A gesture group is translated into
today's nested `if_tap` steps.

### 5.7 On release

```
on release { … }
```

Statements run when the input is released, after the main statements have
finished (or were cancelled with `cancel on release`). At most one per
mapping.

### 5.8 Variables

| Statement | Meaning |
|---|---|
| `NAME = VALUE` | assign (same type) |
| `NAME += VALUE`, `NAME -= VALUE` | add / subtract (int, float or duration variables) |

## 6. Execution semantics

Unchanged from `docs/macros.md` §5–§6. In particular: steps without
duration run immediately; waiting never blocks input processing; a press of
the input while a mapping runs goes first to a waiting `if tap`/gesture,
then to `toggle`, otherwise `restart on press` applies or it is ignored;
everything a mapping presses or moves is released / re-centred when its run
ends, is cancelled, loses its input device, or the remapper stops; shared
keys are reference-counted, shared axes use "most recent holder wins".

## 7. Errors and warnings

- Every message has the form `FILE:LINE:COLUMN: message`, e.g.
  `config/my.inpmap:14:9: unknown key code 'KEY_QQ' (did you mean 'KEY_Q'?)`.
- All errors of a file are reported together (as today).
- Errors include: syntax errors, unknown names, codes not suitable for the
  device, ambiguous omitted devices, duplicate triggers or names, options
  after statements, `toggle` not alone, values out of range, type mismatches,
  `release` of keys never pressed, unused devices.
- Warnings (the file still loads): `BTN_X`/`BTN_Y`.

## 8. Translation into the model (coverage)

| Model (`docs/macros.md`) | Language |
|---|---|
| inputs / outputs, `name` / `path` / `type` | `input` / `output` blocks |
| `settings.key_pause_ms` | `settings { key_pause = … }` |
| `variables` | `let` |
| plain key output, mode `hold` | `hold KEYS` |
| plain key output, mode `tap` | `tap KEYS (pause 20ms)` (a macro with the same effect) |
| plain axis output | `axis REF { … }` |
| macro `on_release: cancel` / `on_retrigger: restart` | `cancel on release` / `restart on press` |
| `key_pause_ms`, `max_run_ms` | `key_pause`, `max_run` |
| `release_steps` | `on release { … }` |
| `tap`, `press`, `release`, `with_keys` | `tap`, `press`, `release`, `with` |
| `hold_keys` | `hold` (non-blocking; when it is the last statement, identical) |
| `axis` step / `hold_axis` step | `move … to … over …` / `axis … { … }` |
| `wait_ms` (number, range, variable) | `wait 40ms`, `wait random(40ms, 60ms)`, `wait delay` |
| `repeat`, `while_held`, `toggle`, `parallel` | `repeat`, `while held`, `toggle`, `parallel { branch … }` |
| `if_tap`, `if_single`, `if_eq`, `if_led` | `if tap`, `if single`, `if x == v`, `if capslock` (+ gestures, `else if`, `not`, `!=`, `if flag` for bool variables) |
| `set`, `add` | `x = v`, `x += v`, `x -= v` |

Non-blocking `hold`/`axis` followed by more statements are translated into
a `parallel` with a holding branch, so the existing executor is reused.

## 9. Tools

- `inpmap check FILE` — validate, print a summary and warnings.
- `inpmap macro-trace FILE NAME …` — unchanged, with mapping names from §4.
- Editor support shipped with InpMap: a Kate syntax definition
  (`inpmap.xml`) and a nano syntax file (`inpmap.nanorc`), with install
  instructions.
- Later (not part of this version): `inpmap fmt` (reformat).

## 10. Not in this version

Arithmetic beyond `+=`/`-=`, functions, includes, named reusable blocks,
mouse output, `mod_tap`, conditions on other held inputs, the Gaussian
humanizer, layout-aware text typing, a Lua `script` statement.

## 11. Complete example

The example configuration of `config/example-macros.json`, written in the
language. Device prefixes are omitted where unambiguous (one keyboard, one
gamepad).

```
# InpMap example configuration
version 1

settings {
    key_pause = 10ms
}

let presses = 0

input kbd {
    name = "AT Translated Set 2 keyboard"
}

output keyboard {
    type = keyboard
    name = "InpMap Virtual Keyboard"
}

output gamepad {
    type = gamepad
    name = "InpMap Virtual Gamepad"
}

# X holds KEY_Y and the gamepad's south button (A) at the same time
map KEY_X {
    hold KEY_Y
    hold BTN_SOUTH
}

# F9: tap Q, wait 40-60 ms, tap the gamepad's east button (B)
map KEY_F9 as combo {
    tap KEY_Q
    wait random(40ms, 60ms)
    tap BTN_EAST
    presses += 1
}

# F10: tap types 1, double tap types 2, long press types 3
map KEY_F10 {
    on tap        { tap KEY_1 }
    on double_tap { tap KEY_2 }
    on long_press { tap KEY_3 }
}

# F11: fire the gamepad's south button while held, stop at once on release
map KEY_F11 as autofire {
    cancel on release
    while held {
        tap BTN_SOUTH (pause 30ms)
    }
}

# F12: push the left stick up within 150 ms, return within 50 ms
map KEY_F12 {
    axis ABS_Y {
        target  = -1.0
        attack  = 150ms
        release = 50ms
    }
}

# Caps Lock alone is Escape; held together with another key it is Ctrl
map KEY_CAPSLOCK {
    if single {
        tap KEY_ESC
    } else {
        hold KEY_LEFTCTRL
    }
}
```

More examples:

```
# Ctrl+C on one key
map KEY_F1 { tap KEY_LEFTCTRL + KEY_C }

# Shift held around a sequence, on two input devices
map pad.BTN_TL {
    with keyboard.KEY_LEFTSHIFT {
        tap KEY_A
        tap KEY_B
    }
}

# Counter with condition and release steps
let mode = 0
map KEY_F2 {
    mode += 1
    if mode == 3 {
        mode = 0
    }
    on release { tap KEY_ENTER }
}

# Toggle autofire on and off with the same key
map KEY_F3 {
    toggle {
        tap BTN_SOUTH (pause 50ms)
    }
}

# Two branches at once: stick sweep while tapping
map KEY_F4 {
    parallel {
        branch { move ABS_X to 1.0 over 500ms; move ABS_X to 0.0 over 500ms }
        branch { repeat 5 { tap BTN_WEST; wait 100ms } }
    }
}

# Caps Lock LED decides
map KEY_F5 {
    if capslock { tap KEY_1 } else { tap KEY_2 }
}
```

## 12. Review notes (user review, 2026-10-13)

The user tested the draft with two cases.

**Case 2 works with the draft** (alternating actions via a variable):

```
let bracket_mode = false

map pad.BTN_WEST as alternate {
    if bracket_mode == false {
        bracket_mode = true
        tap KEY_ENTER
        tap KEY_LEFTCTRL + KEY_LEFTSHIFT + KEY_LEFTBRACE
    } else {
        bracket_mode = false
        tap KEY_LEFTCTRL + KEY_LEFTSHIFT + KEY_LEFTBRACE
        wait 500ms
        tap KEY_ENTER
        tap KEY_ESC
        tap BTN_EAST
    }
}
```

**Case 1 needs a combination trigger, not in the draft or the model:**

```
map KEY_LEFTCTRL + KEY_LEFTSHIFT + KEY_LEFTBRACE as bracket_combo {
    tap KEY_ENTER
    wait random(20ms, 60ms)
    hold KEY_LEFTCTRL + KEY_LEFTSHIFT + KEY_LEFTBRACE
    on release {
        wait 200ms
        tap KEY_ENTER
        tap KEY_ESC
        tap BTN_EAST
    }
}
```

Proposed additions — **user decisions 2026-10-13: 1 yes (study Input Remapper first), 2 yes, 3 yes** — all three are now specified (§4.0, §4.1, §5.5):

1. **Combination triggers** (`map A + B + C { … }`): fires when the last key
   is pressed while the others are held (order irrelevant); released as
   soon as any of its keys is released; when it fires, keys of the
   combination that were already passed through to the desktop (e.g.
   Ctrl, Shift) are released on the forwarding device first, so outputs
   are not modified by them; a longer combination wins over a shorter one
   or a single-key mapping on the same key. Needs new engine functionality;
   study Input Remapper's combination handling (`combination_handler.py`)
   before specifying details.
2. **Bool variables as conditions**: `if bracket_mode`, `if not bracket_mode`.
3. Optional aliases `ctrl`, `shift`, `alt`, `meta` = left or right key.

Layout note: `KEY_LEFTBRACE` is the key right of P (`[` on US layouts, `ü`
on German layouts, where `[` is AltGr+8).

**Revision (user, 2026-10-13):** arbitrary combination triggers were
dropped as too edge-case-prone. Replaced by **one key + modifier state**
(`map KEY_LEFTBRACE modifiers(ctrl, shift)`, §4.0), with a fixed modifier
set that the config can reduce (`settings { modifiers = … }`) to map e.g.
Shift as a normal key. Case 1 becomes:

```
map KEY_LEFTBRACE modifiers(ctrl, shift) as bracket_combo {
    tap KEY_ENTER
    wait random(20ms, 60ms)
    hold ctrl + shift + KEY_LEFTBRACE
    on release {
        wait 200ms
        tap KEY_ENTER
        tap KEY_ESC
        tap BTN_EAST
    }
}
```

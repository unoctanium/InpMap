# InpMap configuration reference

This is the complete reference for InpMap configuration files (`.inpmap`).
It explains every feature with examples. If you have not installed InpMap
yet, start with [installation.md](installation.md); for the commands, see
[usage.md](usage.md).

Contents:

1. [A first look](#1-a-first-look)
2. [File basics](#2-file-basics)
3. [Devices](#3-devices)
4. [Settings and variables](#4-settings-and-variables)
5. [Mappings](#5-mappings)
6. [Statements](#6-statements)
7. [How mappings run](#7-how-mappings-run)
8. [Errors and warnings](#8-errors-and-warnings)
9. [Not supported yet](#9-not-supported-yet)
10. [Complete example](#10-complete-example)
11. [More examples](#11-more-examples)
12. [Appendix: names and keywords](#12-appendix-names-and-keywords)

## 1. A first look

```inpmap
version 1

input kbd {
    name = "AT Translated Set 2 keyboard"
}

output keyboard { type = keyboard }
output gamepad  { type = gamepad }

# While X is held: Y on the virtual keyboard and A on the virtual gamepad
map KEY_X {
    hold KEY_Y
    hold BTN_SOUTH
}

# F9 types "hi"
map KEY_F9 {
    tap KEY_H
    tap KEY_I
}
```

A configuration has three parts:

- **Inputs**: the physical devices InpMap takes over (keyboards, gamepads).
  InpMap grabs them exclusively, so the desktop no longer sees them
  directly.
- **Outputs**: virtual devices InpMap creates (a keyboard, a gamepad, or
  several). Applications see them like real devices.
- **Mappings**: what happens when a key or button of an input is pressed.
  A mapping can press keys and buttons and move sticks on **any** output
  device, also several at once.

Everything that no mapping uses — all other keys, the mouse part of a
combined device, the sticks of a gamepad — is passed through unchanged.

## 2. File basics

- The file name must end in `.inpmap`. Encoding UTF-8.
- **Comments** start with `#` and run to the end of the line.
- **Statements** end at a line break or `;`. Inside `( … )` line breaks are
  ignored, so long lists may span lines.
- **Blocks** are written `{ … }` and may be on one line:
  `on tap { tap KEY_1 }`.
- **Names** you choose (devices, variables, mapping names) consist of
  letters, digits and `_`, do not start with a digit, are case-sensitive and
  must not be a [keyword](#123-keywords).
- **Codes** are Linux event names: `KEY_*` for keyboard keys, `BTN_*` for
  buttons, `ABS_*` for gamepad sticks and triggers (§3.3, §12).
- **Numbers**: `42`, `-1`, `0.5`.
- **Durations**: a number directly followed by `ms` or `s`, without a
  space: `40ms`, `1.5s`. Durations are never negative.
- **Strings**: `"…"`, with `\"`, `\\`, `\n`, `\t`.
- **Booleans**: `true`, `false`.

A file has this structure:

```text
version 1                      # required, first
settings { … }                 # optional
let NAME = VALUE               # variables, optional
input NAME { … }               # one or more physical input devices
output NAME { … }              # one or more virtual output devices
map TRIGGER [as NAME] { … }    # one or more mappings
```

`version` comes first; everything else may be in any order and can refer
to things defined further down.

`version 1` is the version of the language. If a future InpMap changes the
language incompatibly, it increases the version and either converts older
files explicitly or rejects them with a message naming the supported
versions.

## 3. Devices

### 3.1 Input devices

```inpmap
input kbd {
    name = "AT Translated Set 2 keyboard"
}
input pad {
    path = "/dev/input/by-id/usb-Razer_Razer_Raiju_V3_Pro_Wireless_-event-joystick"
}
```

Each input names a physical device with exactly one of:

- `name`: the kernel device name. It must be unique among the connected
  devices; some keyboards expose several devices with similar names.
- `path`: an absolute path, usually a stable link in `/dev/input/by-id/`.

`inpmap input-config FILE` lets you pick devices (or identify them by
pressing a key) and writes these blocks for you
([usage.md](usage.md#inpmap-input-config)); `inpmap devices` lists the
names and paths.

Every input must be used: a mapping names it (`kbd.KEY_X`), or at least
one mapping has no device name and so applies to every input (§5.1).
Exception: when any mapping requires [modifiers](#52-modifiers), an input
may be configured only to provide modifiers (e.g. a keyboard whose Ctrl is
combined with gamepad buttons).

When InpMap opens an input device, it checks that the device has every key
or button that a mapping names for it (`kbd.KEY_X`). Mappings without a
device name apply to those inputs that have the key; if none of the
connected inputs has it, InpMap writes a warning to its log. While
running, an input device that disappears (unplugged, wireless sleep) is
picked up again automatically when it returns.

### 3.2 Output devices

```inpmap
output keyboard {
    type = keyboard
    name = "InpMap Virtual Keyboard"
}
output gamepad { type = gamepad }
```

- `type`: `keyboard` or `gamepad`.
- `name` (optional): the device name applications see. Default:
  `InpMap ` followed by the output's name (`InpMap gamepad`). At most 79
  bytes, unique.

Every declared output must be used by a mapping. You may declare several
outputs of the same type, e.g. two gamepads for two players.

### 3.3 What each output can emit

| Output | Codes |
|---|---|
| `keyboard` | every `KEY_*` code |
| `gamepad` | buttons `BTN_SOUTH`, `BTN_EAST`, `BTN_NORTH`, `BTN_WEST`, `BTN_TL`, `BTN_TR`, `BTN_TL2`, `BTN_TR2`, `BTN_SELECT`, `BTN_START`, `BTN_MODE`, `BTN_THUMBL`, `BTN_THUMBR`, `BTN_DPAD_UP`, `BTN_DPAD_DOWN`, `BTN_DPAD_LEFT`, `BTN_DPAD_RIGHT` (and other joystick buttons if you map them); axes `ABS_X`, `ABS_Y` (left stick), `ABS_RX`, `ABS_RY` (right stick), `ABS_Z`, `ABS_RZ` (left and right trigger) |

Gamepad buttons are named by **position**, because the printed labels
differ between controllers:

| Code | Position | Xbox | PlayStation | Nintendo |
|---|---|---|---|---|
| `BTN_SOUTH` (also `BTN_A`) | bottom | A | Cross | B |
| `BTN_EAST` (also `BTN_B`) | right | B | Circle | A |
| `BTN_NORTH` | top | Y | Triangle | X |
| `BTN_WEST` | left | X | Square | Y |

`BTN_X` and `BTN_Y` are accepted but give a **warning**: in Linux `BTN_X` is
the top button (labelled Y on Xbox) and `BTN_Y` the left one (labelled X).

Keyboard codes are **key positions**, not characters: `KEY_Y` is the key
labelled Y on a US keyboard, which types `z` on a German layout. What a key
types is decided by the keyboard layout of your desktop.

Axis values are fractions of the range: sticks −1.0 (left/up) … 1.0
(right/down), triggers 0.0 (released) … 1.0 (fully pressed). The rest
position is 0.0.

## 4. Settings and variables

### 4.1 Settings

```inpmap
settings {
    key_pause = 10ms
    modifiers = ctrl, alt
}
```

| Setting | Default | Meaning |
|---|---|---|
| `key_pause` | `10ms` | pause after every key press and every key release made by `tap`, `press`, `release`, `hold` and `with` (§6). Games that read input once per frame may need a longer pause. |
| `modifiers` | `ctrl, shift, alt, meta` | which keys count as modifiers (§5.2). Keys left out (here Shift and Meta) become normal keys you can map. |

### 4.2 Variables

```inpmap
let presses = 0          # whole number
let speed = 1.5          # decimal number
let delay = 50ms         # duration
let layer = "game"       # string
let armed = false        # boolean
```

The initial value decides the type, and a variable keeps that type.
Variables are shared by all mappings, start with their initial value every
time InpMap starts, and are not saved. Statements that change them are in
§6.8; conditions that test them in §6.5.

## 5. Mappings

```text
map TRIGGER [as NAME] {
    OPTIONS...
    STATEMENTS...
}
```

### 5.1 Trigger and name

The **trigger** is one key or button:

- `KEY_F9` — on **every** input device that has this key;
- `kbd.KEY_F9`, `pad.BTN_EAST` — the input's name, a dot and the code:
  only on that input device.

With one input device, both mean the same. With two keyboards,
`map KEY_CAPSLOCK { … }` remaps Caps Lock on both. The mapping works on
each device independently, as if it were written once per device:
pressing the key on two keyboards at once starts two runs, and a `toggle`
started from one keyboard is stopped from the same keyboard.

```inpmap
version 1
input laptop   { name = "AT Translated Set 2 keyboard" }
input external { path = "/dev/input/by-id/usb-4348_2.4G_Dongle-event-kbd" }
output keyboard { type = keyboard }

map KEY_CAPSLOCK { tap KEY_ESC }            # on both keyboards
map external.KEY_F1 { tap KEY_MUTE }        # only on the external one
map KEY_F2 { tap KEY_VOLUMEDOWN }           # F2 on every keyboard ...
map external.KEY_F2 { tap KEY_VOLUMEUP }    # ... except the external one, which does this
```

The trigger may be followed by `modifiers(…)` (§5.2).

Triggers are `KEY_*` or `BTN_*` codes. Sticks, analog triggers and mouse
movement cannot be triggers.

The original key press is always **suppressed**: the desktop does not see
the trigger key, only what the mapping does.

`as NAME` gives the mapping a name for messages and for
`inpmap macro-trace`. Without it, the name is the trigger as written
(`KEY_F9`, `pad.BTN_EAST`), with the modifiers appended by `+`
(`KEY_LEFTBRACE+ctrl+shift`, `KEY_F5+ignore`).

A key may be mapped several times: with different modifier requirements
(§5.2), and with and without a device name. Which mapping fires when the
key is pressed on a device:

1. The mappings that **name this device** come first. If one of them
   matches the held modifiers, the most specific of those fires (§5.2
   rule 5).
2. Only if none of them matches, the mappings **without a device name**
   are considered the same way.

Mapping the same trigger text with the same modifier requirement twice is
an error.

### 5.2 Modifiers

By default a mapping fires only when **no** modifier key is held. With
`modifiers(…)` it requires certain modifiers instead:

```text
map KEY_A modifiers(right_shift) { … }        # only with the right Shift
map KEY_LEFTBRACE modifiers(ctrl, shift) { … } # Ctrl+Shift+[
map pad.BTN_SOUTH modifiers(ctrl) { … }       # gamepad A while Ctrl is held on the keyboard
map pad.BTN_SOUTH { … }                       # gamepad A without modifiers
map KEY_F5 modifiers(ignore) { … }            # F5 whatever modifiers are held
```

Rules:

1. **Modifier keys** are Ctrl, Shift, Alt and Meta (the Super/Windows key),
   left and right each. `settings { modifiers = … }` (§4.1) can reduce this
   set; keys outside it are normal keys. A modifier key cannot be a trigger.
2. **Names**: `ctrl`, `shift`, `alt`, `meta` mean either side;
   `left_ctrl`, `right_ctrl`, `left_shift`, `right_shift`, `left_alt`,
   `right_alt`, `left_meta`, `right_meta` mean exactly that key. On many
   layouts the right Alt key is AltGr, so `alt` also matches AltGr.
3. **Exact match**: the mapping fires when the required modifiers are held
   and **no other** modifier is held. A mapping without `modifiers(…)`
   fires only when no modifier is held; otherwise the key passes through
   unchanged, so Shift+A still types a capital A.
4. `modifiers(ignore)` fires whatever modifiers are held, or none. It
   cannot be combined with other names.
5. **Most specific wins**: if several mappings of the same key match, an
   exact side (`right_ctrl`) beats either side (`ctrl`), and every exact
   requirement — including "no modifiers" — beats `ignore`, which is the
   fallback. A mapping that names the device is chosen before any mapping
   without a device name (§5.1). Two mappings with the same trigger and the
   same requirement are an error.
6. **From any device**: modifiers held on any configured input count, so a
   gamepad button can be combined with Ctrl on the keyboard. Modifiers of
   devices that are not configured are not seen.
7. **When pressed**: only the modifiers held at the moment the trigger is
   pressed count. Changing them while the trigger is held does not affect
   the running mapping.
8. **Hidden while running**: modifier keys always reach the desktop. While
   a mapping with `modifiers(…)` runs, InpMap temporarily releases its
   required modifiers towards the desktop, so they do not change the
   mapping's output (Ctrl+Shift+[ mapped to Enter gives a plain Enter, not
   Ctrl+Shift+Enter). When the mapping has completely finished, including
   `on release`, modifiers that are still held are pressed again, so a
   following Ctrl+C works. The mapping option `keep modifiers` turns this
   off, so the modifiers apply to the output. With `modifiers(ignore)`
   nothing is hidden: `map KEY_A modifiers(ignore) { tap KEY_B }` types a
   capital B with Shift.

### 5.3 Output keys, chords and aliases

An output key, button or axis is written `DEVICE.CODE`: `keyboard.KEY_Q`,
`gamepad.BTN_EAST`, `gamepad.ABS_Y`. The device part may be left out when
exactly one declared output can emit the code (§3.3); otherwise InpMap
reports an error naming the candidates.

A **chord** joins keys with `+`: `tap KEY_LEFTCTRL + KEY_C` presses Ctrl,
then C, then releases C, then Ctrl. The keys of a chord may be on different
output devices.

The aliases `ctrl`, `shift`, `alt`, `meta` stand for the **left** key in
outputs: `tap ctrl + KEY_C` is `tap KEY_LEFTCTRL + KEY_C`. (In
`modifiers(…)` they match either side, §5.2.)

### 5.4 Mapping options

Options are written first in the mapping, one per line:

| Option | Meaning | Without it |
|---|---|---|
| `cancel on release` | when the trigger is released, stop the statements at once and release everything the mapping holds | the statements finish |
| `restart on press` | a new press while the statements still run cancels them and starts again | the press is ignored (unless a statement waits for it, §7.2) |
| `keep modifiers` | only with `modifiers(…)`: do not hide the modifiers while running (§5.2 rule 8) | they are hidden |
| `key_pause DURATION` | key pause for this mapping | `settings { key_pause }` |
| `max_run DURATION` / `max_run none` | stop the mapping, with a warning in the log, if it runs longer; `none` = no limit | `60s` |

```inpmap
map KEY_F11 {
    cancel on release
    key_pause 5ms
    while held { tap BTN_SOUTH }
}
```

## 6. Statements

When the trigger is pressed, the statements of the mapping run from top to
bottom. Statements that take no time run immediately; statements that wait
never delay other input (§7).

| Group | Statements |
|---|---|
| Holding while the trigger is held | `hold`, `axis` |
| Keys in sequences | `tap`, `press`, `release`, `with` |
| Time and axes | `wait`, `move` |
| Loops and concurrency | `repeat`, `while held`, `toggle`, `parallel` |
| Decisions | `if … else if … else`, `on tap` / `on double_tap` / `on long_press` |
| After release | `on release` |
| Variables | `=`, `+=`, `-=` |
| Doing nothing | `disable` |

### 6.1 Holding: `hold` and `axis`

`hold KEYS` presses the keys and keeps them pressed until the trigger is
released. It does **not wait**: the next statement runs at once.

```inpmap
map KEY_X {
    hold KEY_Y          # keyboard Y and gamepad A, both held while X is held
    hold BTN_SOUTH
}
```

In text fields the desktop's key repeat then types `yyyy`, as with a real
held key; games see one continuous press. For exactly one key press per
trigger press use `tap`.

`axis` holds a gamepad stick or trigger at a value while the trigger is
held, optionally moving there and back gradually:

```inpmap
map KEY_W {
    axis ABS_Y {
        target  = -1.0      # left stick fully up
        attack  = 150ms     # reach it within 150 ms (default 0ms)
        release = 50ms      # back to rest within 50 ms after release (default 0ms)
    }
}
map KEY_S { axis ABS_Y 1.0 (attack 150ms, release 50ms) }   # one-line form
map KEY_D { axis ABS_X 1.0 }
```

`axis` does not wait either. If two mappings hold the same axis, the one
pressed last wins; when it is released, the other one's value applies
again.

### 6.2 Keys in sequences: `tap`, `press`, `release`, `with`

| Statement | Meaning |
|---|---|
| `tap KEYS` | press the keys in order, then release them in reverse order |
| `press KEYS` | press the keys and keep them pressed until a `release` or the end of the mapping |
| `release KEYS` | release keys pressed by `press` in this mapping (anything else is an error) |
| `with KEYS { … }` | press the keys, run the block, release the keys |

After every press and every release comes the key pause (default 10 ms,
§4.1). `(pause D)` after `tap`, `press` or `release` sets it for that
statement: `tap BTN_SOUTH (pause 30ms)`.

```inpmap
map KEY_F1 { tap ctrl + KEY_C }          # Ctrl+C

map KEY_F2 {
    with KEY_LEFTSHIFT {                  # Shift held around two taps: "AB"
        tap KEY_A
        tap KEY_B
    }
}

map KEY_F3 {
    press KEY_LEFTALT
    tap KEY_TAB
    wait 500ms
    release KEY_LEFTALT
}
```

Keys still pressed when the mapping ends are released then.

### 6.3 Time and axes: `wait`, `move`

| Statement | Meaning |
|---|---|
| `wait D` | wait for the duration `D` |
| `wait random(D1, D2)` | wait a random duration between `D1` and `D2` (evenly distributed, `D1` ≤ `D2`) |
| `wait NAME` | wait for the value of a duration variable |
| `move AXIS to V` | set an axis to `V` at once |
| `move AXIS to V over D` | move an axis to `V` in a straight line within `D`; the statement ends when the target is reached |

An axis set by `move` keeps its value until it is moved again or the
mapping ends; then it returns to rest.

```inpmap
map KEY_F4 {
    move ABS_X to 1.0 over 500ms     # sweep the left stick right
    move ABS_X to -1.0 over 1s       # and left
}                                    # back to the centre at the end
```

### 6.4 Loops and concurrency

| Statement | Meaning |
|---|---|
| `repeat N { … }` | run the block `N` times (0 … 10000, or a whole-number variable) |
| `while held { … }` | repeat the block while the trigger is held; the current pass always completes |
| `toggle { … }` | the first press starts repeating the block, the next press stops it after the current pass; must be the only statement of the mapping (options are allowed) |
| `parallel { branch { … } branch { … } }` | run the branches at the same time; continue when all have finished |

Each pass of a loop takes at least 1 ms, even if its statements take no
time.

```inpmap
map KEY_F5 {                         # autofire while held
    cancel on release
    while held { tap BTN_SOUTH (pause 30ms) }
}

map KEY_F6 {                         # autofire on/off with the same key
    toggle { tap BTN_SOUTH (pause 50ms) }
}

map KEY_F7 {                         # sweep the stick while tapping
    parallel {
        branch { move ABS_X to 1.0 over 500ms; move ABS_X to 0.0 over 500ms }
        branch { repeat 5 { tap BTN_WEST; wait 100ms } }
    }
}
```

### 6.5 Conditions: `if`

```text
if CONDITION { … }
else if CONDITION { … }
else { … }
```

`else` may be on the same line as `}` or on the next line.

| Condition | True when |
|---|---|
| `tap` / `tap within D` | the trigger is released quickly: within `D` (default 300ms) of the press. If the trigger has already been released when `if` runs, it must also be pressed again and released within `D`. Decided at the latest after `D`. |
| `single` / `single within D` | the trigger is released before any other key or button is pressed on any input device. If another key comes first, the `else` branch runs **before** that key is processed. With `within D` it is also false after `D`. |
| `NAME == VALUE`, `NAME != VALUE` | compares a variable with a value of the same type |
| `NAME` | a boolean variable is `true` |
| `capslock`, `numlock`, `scrolllock` | that LED is on, on the input device where the trigger was pressed (false for devices without LEDs) |
| `not CONDITION` | negation |

```inpmap
map KEY_CAPSLOCK {                   # Caps Lock alone: Escape; with another key: Ctrl
    if single { tap KEY_ESC } else { hold KEY_LEFTCTRL }
}

map KEY_F8 {
    if capslock { tap KEY_1 } else { tap KEY_2 }
}
```

### 6.6 Gestures: `on tap`, `on double_tap`, `on long_press`

```inpmap
map KEY_F10 {
    on tap        { tap KEY_1 }
    on double_tap { tap KEY_2 }
    on long_press { tap KEY_3 }
}
```

A group of these handlers tells apart how the trigger was pressed. You may
use any of the three, each at most once, in any order.

| Pressed like this | Runs |
|---|---|
| pressed and released within the window, no second press within the window | `on tap` |
| two quick taps | `on double_tap` (without that handler, the second tap counts as a new `tap`) |
| held longer than the window | `on long_press` |

The window is 300ms. Change it with `within D` on `on tap` and
`on double_tap`, or `after D` on `on long_press`; all handlers of a group
must use the same window: `on tap within 200ms { … }`,
`on long_press after 200ms { … }`.

A tap is recognised only when it is over, so `on tap` runs after the
release (with `on double_tap` present, after the double-tap window has
passed).

### 6.7 After release: `on release`

```inpmap
map KEY_F12 {
    tap KEY_1
    on release { tap KEY_2 }         # types 1 on press, 2 on release
}
```

The block runs when the trigger is released, after the other statements
have finished (or were stopped by `cancel on release`). At most one per
mapping; writing it last makes the order easiest to read.

### 6.8 Changing variables

| Statement | Meaning |
|---|---|
| `NAME = VALUE` | set (same type) |
| `NAME += VALUE`, `NAME -= VALUE` | add or subtract (number and duration variables) |

```inpmap
let mode = false
map KEY_F12 {                        # alternate between two actions
    if mode { tap KEY_A } else { tap KEY_B }
    if mode { mode = false } else { mode = true }
}
```

### 6.9 Disabling a key: `disable`

```inpmap
map KEY_INSERT { disable }                  # Insert does nothing
map KEY_Q modifiers(ctrl) { disable }       # Ctrl+Q does nothing; Q alone still types q
```

The key is suppressed and nothing is sent instead. `disable` must be the
only statement of the mapping, without options.

## 7. How mappings run

### 7.1 A run

- Pressing the trigger starts a **run** of the mapping: its statements in
  order.
- Statements without duration run immediately one after another. Anything
  that waits is scheduled; InpMap keeps processing all other input in the
  meantime. Several mappings can run at the same time.
- The run ends when its statements are done and, if there is an
  `on release` block, the trigger was released and that block is done.
- When a run ends or is stopped, everything it still holds is released
  and every axis it moved returns to rest.
- Autorepeat of a held trigger is ignored.

### 7.2 Presses and releases during a run

- A **release** of the trigger reaches the run: `hold`, `axis`,
  `while held`, `if tap`, `if single` and `on release` react to it, and
  `cancel on release` stops the remaining statements at once.
- A new **press** while the run is still going goes first to a statement
  waiting for it (`if tap`, gestures), then to `toggle`. Otherwise
  `restart on press` stops the run and starts a new one; without that
  option the press is ignored.

### 7.3 Shared outputs

- If several mappings hold the same key or button, it stays pressed until
  the **last** of them lets go. One mapping never releases a key another
  one still holds.
- If several mappings hold the same axis, the most recent one wins; when
  it lets go, the previous holder's value applies again, otherwise the
  axis returns to rest.

### 7.4 Safety

Everything a mapping presses or moves is released or re-centred when its
run ends, is stopped (`cancel on release`, `restart on press`, `max_run`),
when its input device disappears, and when InpMap stops. No key is left
stuck.

### 7.5 Timing

- Key pause after every press and release made by `tap`, `press`,
  `release`, `hold` and `with`: default 10 ms (§4.1, §5.4, `(pause D)`).
- `random(D1, D2)` is evenly distributed.
- Axis movements are updated every 10 ms and end exactly on the target.
- Each key event is sent on its own, so applications see every press and
  release. Timer precision is a few milliseconds; durations are minimums.
- `max_run` (default 60 s) stops runaway mappings.

Use `inpmap macro-trace` to see the exact timeline of a mapping without
any devices ([usage.md](usage.md#inpmap-macro-trace)).

## 8. Errors and warnings

InpMap checks the whole file before it touches any device. Every problem is
reported with its position, all problems of a file at once:

```text
config/my.inpmap:14:9: unknown key code 'KEY_QQ' (did you mean 'KEY_Q'?)
```

Errors include: syntax errors; unknown names and codes; codes the device
cannot emit; a device part left out where several outputs could emit the
code; the same trigger and modifiers mapped twice; duplicate names; options
after statements; `toggle` or `disable` not alone; values out of range;
values of the wrong type; `release` of keys never pressed; unused devices.

Warnings (the file still loads): `BTN_X` and `BTN_Y` (§3.3).

Check a file with `inpmap check FILE`.

## 9. Not supported yet

Mouse output (movement, wheel); analog inputs as triggers; dual-role keys
that hold back other keys while undecided; conditions on other held keys;
reusable named blocks; arithmetic beyond `+=`/`-=`; typing text by
character (codes are key positions); randomised "human" timing beyond
`random`.

## 10. Complete example

This is `config/example.inpmap`. With only one keyboard and one gamepad,
device names are left out of the codes.

```inpmap
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

## 11. More examples

A keyboard and a gamepad as inputs; each trigger names its device:

```inpmap
version 1
input kbd { name = "AT Translated Set 2 keyboard" }
input pad { path = "/dev/input/by-id/usb-Razer_Razer_Raiju_V3_Pro_Wireless_-event-joystick" }
output keyboard { type = keyboard }
output gamepad { type = gamepad }

# Ctrl+C on one key
map kbd.KEY_F1 { tap ctrl + KEY_C }

# Shift held around a sequence, triggered from the gamepad
map pad.BTN_TL {
    with keyboard.KEY_LEFTSHIFT {
        tap KEY_A
        tap KEY_B
    }
}

# Counter with condition and release steps
let mode = 0
map kbd.KEY_F2 {
    mode += 1
    if mode == 3 {
        mode = 0
    }
    on release { tap KEY_ENTER }
}

# Toggle autofire on and off with the same key
map kbd.KEY_F3 {
    toggle {
        tap BTN_SOUTH (pause 50ms)
    }
}

# Two branches at once: stick sweep while tapping
map kbd.KEY_F4 {
    parallel {
        branch { move ABS_X to 1.0 over 500ms; move ABS_X to 0.0 over 500ms }
        branch { repeat 5 { tap BTN_WEST; wait 100ms } }
    }
}

# Caps Lock LED decides
map kbd.KEY_F5 {
    if capslock { tap KEY_1 } else { tap KEY_2 }
}

# Gamepad A with Ctrl held on the keyboard, and without
map pad.BTN_SOUTH modifiers(ctrl) { tap KEY_C }
map pad.BTN_SOUTH { hold BTN_SOUTH }
```

A key combination replaced by a sequence, and a gamepad button that
alternates between two sequences:

```inpmap
version 1
input kbd { name = "AT Translated Set 2 keyboard" }
input pad { path = "/dev/input/by-id/usb-Razer_Razer_Raiju_V3_Pro_Wireless_-event-joystick" }
output keyboard { type = keyboard }
output gamepad { type = gamepad }

# Ctrl+Shift+[ : Enter, then hold Ctrl+Shift+[ while the key is held;
# after release: Enter, Escape and gamepad B
map kbd.KEY_LEFTBRACE modifiers(ctrl, shift) as bracket_combo {
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

# Gamepad X: first press opens, second press closes
let bracket_mode = false
map pad.BTN_WEST as alternate {
    if not bracket_mode {
        bracket_mode = true
        tap KEY_ENTER
        tap ctrl + shift + KEY_LEFTBRACE
    } else {
        bracket_mode = false
        tap ctrl + shift + KEY_LEFTBRACE
        wait 500ms
        tap KEY_ENTER
        tap KEY_ESC
        tap BTN_EAST
    }
}
```

## 12. Appendix: names and keywords

### 12.1 Finding key codes

The codes are the kernel's names from `linux/input-event-codes.h`.
`inpmap codes FILTER` lists them (`inpmap codes kp` shows the numpad keys;
[usage.md](usage.md#inpmap-codes)). To see which code a key sends, run
`evtest`, choose your keyboard and press the key: it prints e.g.
`code 45 (KEY_X)`. Some frequently used ones:

| Keys | Codes |
|---|---|
| Letters, digits | `KEY_A` … `KEY_Z`, `KEY_0` … `KEY_9` |
| Function keys | `KEY_F1` … `KEY_F24` |
| Modifiers | `KEY_LEFTCTRL`, `KEY_RIGHTCTRL`, `KEY_LEFTSHIFT`, `KEY_RIGHTSHIFT`, `KEY_LEFTALT`, `KEY_RIGHTALT`, `KEY_LEFTMETA`, `KEY_RIGHTMETA` |
| Editing | `KEY_ENTER`, `KEY_ESC`, `KEY_BACKSPACE`, `KEY_TAB`, `KEY_SPACE`, `KEY_DELETE`, `KEY_INSERT` |
| Navigation | `KEY_UP`, `KEY_DOWN`, `KEY_LEFT`, `KEY_RIGHT`, `KEY_HOME`, `KEY_END`, `KEY_PAGEUP`, `KEY_PAGEDOWN` |
| Locks | `KEY_CAPSLOCK`, `KEY_NUMLOCK`, `KEY_SCROLLLOCK` |
| Numpad | `KEY_KP0` … `KEY_KP9`, `KEY_KPDOT`, `KEY_KPENTER`, `KEY_KPPLUS`, `KEY_KPMINUS`, `KEY_KPASTERISK`, `KEY_KPSLASH`, `KEY_KPEQUAL`, `KEY_KPCOMMA` |
| Other | `KEY_SYSRQ` (Print Screen), `KEY_PAUSE`, `KEY_COMPOSE` (menu key), `KEY_F13` … `KEY_F24` (no physical key on most keyboards; useful as distinct keys for games) |
| Punctuation (US positions) | `KEY_MINUS`, `KEY_EQUAL`, `KEY_LEFTBRACE`, `KEY_RIGHTBRACE`, `KEY_SEMICOLON`, `KEY_APOSTROPHE`, `KEY_GRAVE`, `KEY_BACKSLASH`, `KEY_COMMA`, `KEY_DOT`, `KEY_SLASH` |
| Media | `KEY_MUTE`, `KEY_VOLUMEUP`, `KEY_VOLUMEDOWN`, `KEY_PLAYPAUSE`, `KEY_NEXTSONG`, `KEY_PREVIOUSSONG` |

Remember that these are positions: `KEY_LEFTBRACE` is the key right of P,
which is `[` on a US layout and `ü` on a German one.

Numpad keys are separate codes from the digit row: `KEY_KP1` is the 1 on
the numpad, `KEY_1` the 1 above the letters, and games that tell them apart
(flight simulators, for example) see different keys. What a numpad key
types in a text field depends on the Num Lock state, as on a real
keyboard.

### 12.2 Gamepad buttons and axes

See §3.3.

### 12.3 Keywords

These words are reserved and cannot be used as names:

```text
version settings let input output map as hold tap press release with wait
random repeat while held toggle parallel branch on double_tap long_press if
else single not and keep modifiers ignore ctrl shift alt meta left_ctrl
right_ctrl left_shift right_shift left_alt right_alt left_meta right_meta
within after axis move to over cancel restart key_pause max_run none true
false capslock numlock scrolllock disable
```

## About this document

This reference is also the specification of the language. Changes to the
language are made here first (see `CLAUDE.md` §7). Its first version was
approved on 2026-10-13; it replaces the former `docs/dsl.md` and
`docs/macros.md`.

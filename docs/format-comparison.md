# Format comparison: `config/example-macros.json` in a custom DSL and in KDL

Status: **discussion material** (2026-10-13). Both versions are drafts:
neither has a parser yet, and the KDL text has not been checked by a KDL
parser.

Both translations use the **same vocabulary**, so only the syntax differs.
Vocabulary taken from the user's DSL sketch:

- a mapping body is a list of statements; `hold X` presses X and keeps it
  pressed until the input is released, **without** blocking the next
  statement (today's plain outputs and `hold_keys`);
- `on tap` / `on double_tap` / `on long_press` handlers instead of nested
  `if_tap` (they translate into today's nested `if_tap` steps; the default
  window is 300 ms, changeable per handler);
- `cancel on release` is a mapping option (today's `"on_release": "cancel"`),
  so it cannot be confused with `on release { … }`, which would mean steps
  to run when the input is released (today's `release_steps`);
- devices are written `device.CODE`; with a single input device, `map KEY_X`
  uses it (otherwise `map kbd.KEY_X`);
- the mapping id defaults to the input name (`KEY_F9`), with `as name` to
  choose one;
- durations carry units in the DSL (`40ms`); in KDL the unit is in the name
  (`attack-ms`), because a bare `40ms` is not a valid KDL value.

## Custom DSL

```
# InpMap configuration — custom DSL draft
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
    hold keyboard.KEY_Y
    hold gamepad.BTN_SOUTH
}

# F9: tap Q, wait 40-60 ms, tap the gamepad's east button (B)
map KEY_F9 as combo {
    tap keyboard.KEY_Q
    wait random(40ms, 60ms)
    tap gamepad.BTN_EAST
    presses += 1
}

# F10: tap types 1, double tap types 2, long press types 3
map KEY_F10 {
    on tap        { tap keyboard.KEY_1 }
    on double_tap { tap keyboard.KEY_2 }
    on long_press { tap keyboard.KEY_3 }
}

# F11: fire the gamepad's south button while held, stop at once on release
map KEY_F11 as autofire {
    cancel on release
    while held {
        tap gamepad.BTN_SOUTH (pause 30ms)
    }
}

# F12: push the left stick up within 150 ms, return within 50 ms
map KEY_F12 {
    axis gamepad.ABS_Y {
        target  = -1.0
        attack  = 150ms
        release = 50ms
    }
}

# Caps Lock alone is Escape; held together with another key it is Ctrl
map KEY_CAPSLOCK {
    if single {
        tap keyboard.KEY_ESC
    } else {
        hold keyboard.KEY_LEFTCTRL
    }
}
```

## KDL 2

```kdl
// InpMap configuration — KDL 2 draft
version 1

settings {
    key-pause-ms 10
}

let presses 0

input kbd name="AT Translated Set 2 keyboard"
output keyboard type=keyboard name="InpMap Virtual Keyboard"
output gamepad type=gamepad name="InpMap Virtual Gamepad"

// X holds KEY_Y and the gamepad's south button (A) at the same time
map KEY_X {
    hold keyboard.KEY_Y
    hold gamepad.BTN_SOUTH
}

// F9: tap Q, wait 40-60 ms, tap the gamepad's east button (B)
map KEY_F9 as=combo {
    tap keyboard.KEY_Q
    wait-ms min=40 max=60
    tap gamepad.BTN_EAST
    add presses 1
}

// F10: tap types 1, double tap types 2, long press types 3
map KEY_F10 {
    on-tap        { tap keyboard.KEY_1 }
    on-double-tap { tap keyboard.KEY_2 }
    on-long-press { tap keyboard.KEY_3 }
}

// F11: fire the gamepad's south button while held, stop at once on release
map KEY_F11 as=autofire {
    cancel-on-release
    while-held {
        tap gamepad.BTN_SOUTH pause-ms=30
    }
}

// F12: push the left stick up within 150 ms, return within 50 ms
map KEY_F12 {
    axis gamepad.ABS_Y target=-1.0 attack-ms=150 release-ms=50
}

// Caps Lock alone is Escape; held together with another key it is Ctrl
map KEY_CAPSLOCK {
    if-single {
        then { tap keyboard.KEY_ESC }
        else { hold keyboard.KEY_LEFTCTRL }
    }
}
```

## Notes

| | JSON (today) | Custom DSL | KDL 2 |
|---|---|---|---|
| Comments | no (`description` fields) | `#` | `//`, `/* */`, `/-` comments out a whole node |
| Units | in key names (`attack_ms`) | in values (`150ms`) | in property names (`attack-ms=150`) |
| Expressions | `{"add": {"var": …}}` | `presses += 1`, `random(a, b)` | `add presses 1`, `wait-ms min= max=` |
| if/else | `"then"`/`"else"` lists | `if single { } else { }` | `then { }` / `else { }` child nodes |
| Error positions | JSON path | line and column (own parser, e.g. lark) | node path (no line numbers in ckdl/kdl-py) |
| Highlighting in Kate | built in | own syntax file needed | built in (`*.kdl`) |
| Highlighting in nano | built in | own nanorc needed | own nanorc needed |
| Parser | stdlib | own grammar (lark, pure Python) | ckdl (C) or kdl-py (unreleased KDL 2) |
| Grammar to specify and maintain | — | yes | no (KDL spec) |

Behavioural detail: today's autofire step is
`{"tap": "BTN_SOUTH", "pause_ms": 30}` (30 ms pause after the press and after
the release). Both drafts keep that as a step option (`(pause 30ms)` /
`pause-ms=30`). Writing `tap …` followed by `pause 30ms` instead would add a
30 ms wait to the default 10 ms pauses, which is slightly different timing.

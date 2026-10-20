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
output gamepad { type = gamepad }

# While X is held: Y on the virtual keyboard and A on the virtual gamepad
map KEY_X {
    hold KEY_Y
    hold BTN_FACE_DOWN
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
  several). Applications see them like real devices — instead of the
  inputs.
- **Mappings**: what happens when a key or button of an input is pressed.
  A mapping can press keys and buttons and move sticks on **any** output
  device, also several at once.

Everything that no mapping uses — all other keys, the sticks of a
gamepad — goes unchanged to the output of its kind: keys to the keyboard
output, buttons and sticks to the gamepad output (§3.4).

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
map TRIGGER [as NAME] { … }    # mappings
layer NAME { map … }           # layers, optional (§5.6)
block NAME { … }               # reusable statements, optional (§6.11)
```

A file without any mapping is valid. InpMap then grabs no device and
creates no virtual device: it starts and does nothing until you add
mappings (`inpmap check` notes this).

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

Optionally, `to = …` says where the device's unmapped input goes (§3.4).

`inpmap input-config FILE` lets you pick devices (or identify them by
pressing a key) and writes these blocks for you
([usage.md](usage.md#inpmap-input-config)); `inpmap devices` lists the
names and paths.

Once the file has mappings, every input must be used: a mapping names it
(`kbd.KEY_X`), or at least one mapping has no device name and so applies
to every input (§5.1).
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
- `emulate` (optional, gamepad only): `"dualsense-edge"` makes the output
  present itself as a Sony DualSense Edge, for games that read paddles only
  from real controllers (§3.5).

Once the file has mappings, every declared output must be used: a
mapping sends to it, or an input's unmapped input goes to it (§3.4). You
may declare several outputs of the same type, e.g. two gamepads for two
players.

### 3.3 What each output can emit

| Output | Codes |
|---|---|
| `keyboard` | every `KEY_*` code |
| `gamepad` | buttons `BTN_FACE_DOWN`, `BTN_FACE_RIGHT`, `BTN_FACE_LEFT`, `BTN_FACE_UP`, `BTN_TL`, `BTN_TR`, `BTN_TL2`, `BTN_TR2`, `BTN_SELECT`, `BTN_START`, `BTN_MODE`, `BTN_THUMBL`, `BTN_THUMBR`, `BTN_DPAD_UP`, `BTN_DPAD_DOWN`, `BTN_DPAD_LEFT`, `BTN_DPAD_RIGHT`; if you map them, also the back paddles `BTN_GRIPL`, `BTN_GRIPR`, `BTN_GRIPL2`, `BTN_GRIPR2` and other joystick buttons; axes `ABS_X`, `ABS_Y` (left stick), `ABS_RX`, `ABS_RY` (right stick), `ABS_Z`, `ABS_RZ` (left and right trigger). The D-pad is the `BTN_DPAD_*` buttons; a physical pad's D-pad axes `ABS_HAT0X`/`ABS_HAT0Y` arrive as these buttons (§3.4) |

A gamepad output with `emulate = "dualsense-edge"` has its own fixed set
(§3.5).

The four face buttons are named by **position**, because their labels
differ between controllers:

| Code | Position | Xbox | PlayStation | Nintendo |
|---|---|---|---|---|
| `BTN_FACE_DOWN` | bottom | A | Cross | B |
| `BTN_FACE_RIGHT` | right | B | Circle | A |
| `BTN_FACE_LEFT` | left | X | Square | Y |
| `BTN_FACE_UP` | top | Y | Triangle | X |

These names are InpMap's own. Linux has several names for these codes
(`BTN_A`, `BTN_SOUTH`, `BTN_X`, `BTN_NORTH`, …), and its drivers do not
agree on them: Xbox controllers report the left button with the code
Linux calls `BTN_X` and `BTN_NORTH` ("north" = top), PlayStation and
Nintendo controllers report the top button with it. InpMap does not
accept the Linux names; an error names the replacement. It translates
for you: the left button of any controller is `BTN_FACE_LEFT`, as an
input (InpMap swaps the two codes for controllers with the Linux drivers
`hid-playstation`, `hid-sony` and `hid-nintendo`, as SDL does) and on its
gamepad outputs (where games and Steam see it as X / Square).

Back paddles follow the Linux convention: `BTN_GRIPL` and `BTN_GRIPR` are
the upper left and right paddle, `BTN_GRIPL2` and `BTN_GRIPR2` the lower
ones. Steam shows them as L4, R4, L5 and R5. They are added to a virtual
gamepad only when a mapping uses them, so a gamepad without paddle mappings
does not pretend to have paddles:

```inpmap
version 1
input keys { path = "/dev/input/by-id/usb-Example_Pad-if01-event-kbd" }
output gamepad { type = gamepad }

map keys.KEY_F13 { hold BTN_GRIPL }  # extra button sending F13: upper left paddle
map keys.KEY_F14 { hold BTN_GRIPR }
```

Keyboard codes are **key positions**, not characters: `KEY_Y` is the key
labelled Y on a US keyboard, which types `z` on a German layout. What a key
types is decided by the keyboard layout of your desktop.

Axis values are fractions of the range: sticks −1.0 (left/up) … 1.0
(right/down), triggers 0.0 (released) … 1.0 (fully pressed). The rest
position is 0.0.

### 3.4 Where unmapped input goes

**The declared outputs are the devices applications see.** An input's
unmapped keys, buttons and axes go to the output of their kind, together
with what the mappings send there:

| An input reports | Its unmapped input goes to |
|---|---|
| keyboard keys (`KEY_*`) | the `keyboard` output |
| gamepad buttons, sticks, triggers, D-pad (the set of §3.3) | the `gamepad` output |
| mouse buttons and movement, other buttons and axes such as `BTN_0` or a volume wheel | a pass-through device of the input (rule 3) |

```inpmap
version 1
input kbd { name = "AT Translated Set 2 keyboard" }
input pad { path = "/dev/input/by-id/usb-Razer_Razer_Raiju_V3_Pro_Wireless_-event-joystick" }
input padkeys { path = "/dev/input/by-id/usb-Razer_Razer_Raiju_V3_Pro_Wireless_-if01-event-kbd" }
output keyboard { type = keyboard }
output gamepad { type = gamepad }

map kbd.KEY_CAPSLOCK { tap KEY_ESC }

# The pad's extra buttons send F13 to F16: make them back paddles
map padkeys.KEY_F13 { hold BTN_GRIPL }
map padkeys.KEY_F14 { hold BTN_GRIPR }
map padkeys.KEY_F15 { hold BTN_GRIPL2 }
map padkeys.KEY_F16 { hold BTN_GRIPR2 }
```

Applications see "InpMap keyboard" with all keys of `kbd` (Caps Lock as
Escape) and the unmapped keys of `padkeys`, and "InpMap gamepad" with the
Raiju's sticks, triggers, D-pad and buttons plus the four paddles. Games
see one controller.

**`to`** chooses the target when the default does not fit:

| `to = …` | Meaning |
|---|---|
| `to = gamepad2` | the input's gamepad buttons and axes go to `gamepad2`, e.g. the pad of a second player |
| `to = keyboard2, gamepad2` | one output per kind |
| `to = own` | the input keeps a virtual device of its own that copies its name and identity; mappings still send to the outputs. For devices that do not fit the outputs: DirectInput-style gamepads and flight sticks, or a keyboard whose desktop settings (e.g. its own layout) should stay separate |

Two players, each pad on a gamepad of its own, and a flight stick that
keeps its own device:

```inpmap
version 1
input pad1 {
    name = "Pad One"
    to   = gamepad1
}
input pad2 {
    name = "Pad Two"
    to   = gamepad2
}
input stick {
    name = "Flight Stick"
    to   = own
}
output keyboard { type = keyboard }
output gamepad1 { type = gamepad }
output gamepad2 { type = gamepad }

map pad1.BTN_MODE { tap KEY_ESC }
map pad2.BTN_MODE { tap KEY_ESC }
map stick.BTN_TRIGGER { tap KEY_SPACE }
```

Rules:

1. Without `to`, each kind goes to the only output of that kind. A kind
   not named in `to` also goes to its only output. If a file declares
   several outputs of a kind, every input names one of them in `to` (or
   uses `to = own`); `inpmap check` reports a missing one.
2. **The device must keep working.** If an input reports keys but there
   is no keyboard output, or gamepad buttons or axes that the gamepad
   output does not have (other buttons, flight-stick axes, a right stick
   on `ABS_Z`/`ABS_RZ`), InpMap does **not** grab it and says what to add
   (`output keyboard { type = keyboard }` or `to = own`). At start this is
   an error, before any device is grabbed. A device that appears later is
   left alone, the reason is logged and the other devices keep running.
   Keys and buttons that a mapping uses need no output (if such a mapping
   does not fire, e.g. because of held modifiers, the press is dropped).
   Touchpads, touchscreens and tablets always need `to = own`.
3. Mouse buttons and movement, buttons that are neither keys nor gamepad
   or joystick buttons (such as `BTN_0`), and axes that are neither gamepad
   nor joystick axes (such as a volume wheel) go to a pass-through device
   of the input ("InpMap forward: …") that carries only these, so a mouse
   part keeps working. (A mouse output is planned.)
4. A pad's D-pad axes (`ABS_HAT0X`, `ABS_HAT0Y`) arrive on the gamepad
   output as the D-pad buttons `BTN_DPAD_*`, the D-pad that mappings use
   too. (A device with both D-pad buttons and D-pad axes would confuse
   games: SDL and Steam read only the buttons.) A gamepad output is created
   with a fixed set (§3.3) before any device is opened, so it stays the
   same when a device is missing at start or reconnects.
5. Buttons pass unchanged, key repeat included. Axes are converted by
   their fraction of the range (§5.5): a stick at half way is at half way
   on the output.
6. Mappings work as before: a key, button or axis that a mapping uses is
   not passed on (§5.5 rule 5), and a mapping may send to any output.
7. Unmapped input counts as a holder like a mapping (§7.3).
8. When a device disappears or InpMap stops, everything it holds on the
   outputs is released and its axes return to rest (§7.4).
9. Keyboard LEDs (Caps Lock, Num Lock, Scroll Lock) set on a keyboard
   output are shown on every physical keyboard that sends to it.
10. Outputs keep their own name and identity (§3.2). Rumble (force
    feedback) is not passed on.

What this means in practice:

- Several keyboards arrive as one keyboard; desktop settings for a
  particular physical keyboard or mouse no longer apply to it (use
  `to = own` for that device).
- A file with only a gamepad output and a keyboard input is rejected:
  the keyboard's other keys would have nowhere to go. Add a keyboard
  output.

### 3.5 Emulating a DualSense Edge: `emulate`

Some games see only the standard buttons of a virtual gamepad. Windows
games under Proton are the typical case: Proton hands a virtual gamepad to
them as an Xbox controller, which has no back paddles. Real PlayStation
controllers, by contrast, are passed to the game directly, and the game's
own PlayStation driver reads all their buttons. For such games a gamepad
output can present itself as a Sony DualSense Edge (USB):

```inpmap
version 1
input pad { path = "/dev/input/by-id/usb-Razer_Razer_Raiju_V3_Pro_Wireless_-event-joystick" }
input padkeys { path = "/dev/input/by-id/usb-Razer_Razer_Raiju_V3_Pro_Wireless_-if01-event-kbd" }
output keyboard { type = keyboard }
output gamepad {
    type    = gamepad
    emulate = "dualsense-edge"
}

# The pad's extra buttons send F13 to F16: back paddles and Fn buttons
map padkeys.KEY_F13 { hold BTN_GRIPL }
map padkeys.KEY_F14 { hold BTN_GRIPR }
map padkeys.KEY_F15 { hold BTN_GRIPL2 }
map padkeys.KEY_F16 { hold BTN_GRIPR2 }
```

This is the one exception to InpMap's rule that its virtual devices do not
pretend to be real hardware. Use it only for a game that needs it; without
`emulate` nothing changes.

What is different from a normal gamepad output:

- The device is created through `/dev/uhid` as a HID device with Sony's
  USB IDs (`054C:0DF2`) instead of through `/dev/uinput`. It has a raw HID
  node (`/dev/hidraw*`), which is what lets Proton pass it to the game.
  On the desktop, Linux's `hid-playstation` driver shows it as a DualSense
  Edge: a gamepad plus motion-sensor, touchpad and headset-jack devices,
  which stay idle.
- It has a fixed set of codes, the controls of a DualSense Edge:

  | Code | DualSense Edge | In SDL-based games |
  |---|---|---|
  | `BTN_FACE_DOWN`, `BTN_FACE_RIGHT`, `BTN_FACE_LEFT`, `BTN_FACE_UP` | Cross, Circle, Square, Triangle | A, B, X, Y |
  | `BTN_TL`, `BTN_TR` | L1, R1 | shoulder buttons |
  | `BTN_TL2`, `BTN_TR2` | L2, R2 fully pressed | triggers |
  | `BTN_SELECT`, `BTN_START`, `BTN_MODE` | Create, Options, PS button | Back, Start, Guide |
  | `BTN_THUMBL`, `BTN_THUMBR` | L3, R3 (stick clicks) | stick buttons |
  | `BTN_DPAD_UP`, `BTN_DPAD_DOWN`, `BTN_DPAD_LEFT`, `BTN_DPAD_RIGHT` | D-pad | D-pad |
  | `BTN_GRIPL` | left Fn button (Steam: upper left) | Paddle 4 |
  | `BTN_GRIPR` | right Fn button (Steam: upper right) | Paddle 3 |
  | `BTN_GRIPL2` | left back paddle (Steam: lower left) | Paddle 2 |
  | `BTN_GRIPR2` | right back paddle (Steam: lower right) | Paddle 1 |
  | `ABS_X`, `ABS_Y`, `ABS_RX`, `ABS_RY` | left and right stick | sticks |
  | `ABS_Z`, `ABS_RZ` | L2, R2 analog | triggers |

  The paddle codes follow the **positions** Steam shows for the Edge, like
  the Linux convention of §3.3: `BTN_GRIPL`/`BTN_GRIPR` the upper row (the
  Fn buttons), `BTN_GRIPL2`/`BTN_GRIPR2` the lower row (the back paddles).
  Games number them differently: SDL counts the paddles as seen from the
  back, right paddle first, so World of Warcraft, for example, shows
  `BTN_GRIPR2`, `BTN_GRIPL2`, `BTN_GRIPR`, `BTN_GRIPL` as `PADPADDLE1` to
  `PADPADDLE4`. What else WoW needs: [wow-dualsense.md](wow-dualsense.md).
  The paddles and Fn buttons are always present, because a
  DualSense Edge always has them (unlike §3.3, where a gamepad gets
  paddles only when a mapping uses them). The touchpad, the microphone
  button and the motion sensors are not driven.

Rules:

1. Other codes cannot be sent to this output (an error, §8), and an input
   whose unmapped buttons or axes it does not have is not grabbed (§3.4
   rule 2).
2. A trigger is as far pressed as the larger of its axis (`ABS_Z`,
   `ABS_RZ`) and its button (`BTN_TL2`, `BTN_TR2` = fully pressed). A
   DualSense reports the D-pad as one direction: two neighbouring
   directions held give the diagonal; up and down (or left and right)
   held together count as neither.
3. Its identity is fixed: vendor and product of a DualSense Edge, and a
   serial number (MAC address) derived from the output's name, so it stays
   the same across restarts and differs between two such outputs. `name`
   works as in §3.2.
4. What the game sends back — rumble, the light bar, player LEDs,
   adaptive-trigger effects — is accepted and ignored.
5. InpMap never takes the devices that Linux creates for its own emulated
   controller as inputs, and does not list them in `inpmap devices`.
6. It needs write access to `/dev/uhid`, besides `/dev/uinput`
   ([installation.md](installation.md)). Without it, InpMap stops with an
   error before it grabs any device.
7. Steam: turn Steam Input off for the game (game properties →
   Controller → "Disable Steam Input"). Otherwise Steam hides the
   controller from the game and offers its own virtual controller, which
   has no paddles again. Proton needs no setting: it passes PlayStation
   controllers to the game directly.

Sony, DualSense and PlayStation are trademarks of Sony Interactive
Entertainment. InpMap is not affiliated with Sony; the emulation exists
only so that games accept the controller you actually use.

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
let presses = 0    # whole number
let speed = 1.5    # decimal number
let delay = 50ms   # duration
let mode = "game"  # string
let armed = false  # boolean
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
- `kbd.KEY_F9`, `pad.BTN_FACE_RIGHT` — the input's name, a dot and the code:
  only on that input device.

With one input device, both mean the same. With two keyboards,
`map KEY_CAPSLOCK { … }` remaps Caps Lock on both. The mapping works on
each device independently, as if it were written once per device:
pressing the key on two keyboards at once starts two runs, and a `toggle`
started from one keyboard is stopped from the same keyboard.

```inpmap
version 1
input laptop { name = "AT Translated Set 2 keyboard" }
input external { path = "/dev/input/by-id/usb-4348_2.4G_Dongle-event-kbd" }
output keyboard { type = keyboard }

map KEY_CAPSLOCK { tap KEY_ESC }          # on both keyboards
map external.KEY_F1 { tap KEY_MUTE }      # only on the external one
map KEY_F2 { tap KEY_VOLUMEDOWN }         # F2 on every keyboard ...
map external.KEY_F2 { tap KEY_VOLUMEUP }  # ... except the external one, which does this
```

The trigger may be followed by `modifiers(…)` (§5.2).

Triggers are `KEY_*` or `BTN_*` codes, or a stick, analog trigger or D-pad
axis passing a threshold (§5.5). Mouse movement cannot be a trigger.

The original key press is always **suppressed**: the desktop does not see
the trigger key, only what the mapping does.

`as NAME` gives the mapping a name for messages and for
`inpmap macro-trace`. Without it, the name is the trigger as written
(`KEY_F9`, `pad.BTN_FACE_RIGHT`), with the modifiers appended by `+`
(`KEY_LEFTBRACE+ctrl+shift`, `KEY_F5+ignore`). For axes, spaces become
`_` (`pad.ABS_RZ_above_0.5`).

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
map pad.BTN_FACE_DOWN modifiers(ctrl) { … }       # gamepad A while Ctrl is held on the keyboard
map pad.BTN_FACE_DOWN { … }                       # gamepad A without modifiers
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
`gamepad.BTN_FACE_RIGHT`, `gamepad.ABS_Y`. The device part may be left out when
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
    while held { tap BTN_FACE_DOWN }
}
```

### 5.5 Sticks, analog triggers and the D-pad as triggers

A mapping can fire when an axis of an input device passes a threshold.
The axis then works like a button:

```inpmap
version 1
input pad { path = "/dev/input/by-id/usb-Razer_Razer_Raiju_V3_Pro_Wireless_-event-joystick" }
output keyboard { type = keyboard }

map pad.ABS_RZ above 0.5 { hold KEY_SPACE }   # right trigger pressed more than half
map pad.ABS_HAT0Y below -0.5 { tap KEY_KP8 }  # D-pad up
map pad.ABS_HAT0Y above 0.5 { tap KEY_KP2 }   # D-pad down
map pad.ABS_X below -0.7 as stick_left { hold KEY_A }
```

**Values** are fractions of the range the device reports for the axis:

| The device's range | Values | Examples |
|---|---|---|
| negative to positive | −1.0 … 1.0, rest 0.0; negative is left or up | sticks, D-pad (`ABS_HAT0X`/`ABS_HAT0Y`: −1, 0 or 1), rudder |
| from 0 | 0.0 … 1.0, rest 0.0 | analog triggers (`ABS_Z`, `ABS_RZ`), most throttles |

`inpmap axes FILE` shows the axes of your input devices with their
current values while you move them, to find good thresholds
([usage.md](usage.md#inpmap-axes)).

Rules:

1. `above V` presses when the value rises above `V`, `below V` when it
   falls below `V`. `V` lies between −1.0 and 1.0 and is not 0.
2. It is released when the value comes back past the threshold by
   **0.05** (so a value jittering at the threshold does not press and
   release repeatedly): `above 0.5` releases below 0.45.
3. Everything that works with buttons works here: `hold`, `tap`, macros,
   gestures, `while held`, `modifiers(…)`, devices or every input (§5.1).
4. Several thresholds on one axis are fine. `above 0.3` and `above 0.9`
   make a two-stage trigger; at full press both mappings are held. The
   same axis, direction and value twice is an error.
5. An axis used by a mapping is **suppressed** on that device: games no
   longer see its analog value, only what the mappings send. The device's
   other axes pass through.
6. Axes that can be triggers: `ABS_X`, `ABS_Y`, `ABS_Z`, `ABS_RX`,
   `ABS_RY`, `ABS_RZ`, `ABS_THROTTLE`, `ABS_RUDDER`, `ABS_WHEEL`,
   `ABS_GAS`, `ABS_BRAKE`, `ABS_HAT0X` … `ABS_HAT3Y`.
7. When InpMap opens the device it checks that the axis exists and that
   the threshold can be reached (e.g. `below -0.5` can never fire on a
   0.0 … 1.0 trigger): an error for a mapping that names the device, a
   warning in the log otherwise.

### 5.6 Layers

A **layer** is a group of mappings that only applies while the layer is
active. A mapping switches it on, either while its trigger is held or until
it is switched off again:

```inpmap
version 1
input kbd { name = "AT Translated Set 2 keyboard" }
input pad { path = "/dev/input/by-id/usb-Razer_Razer_Raiju_V3_Pro_Wireless_-event-joystick" }
output keyboard { type = keyboard }
output gamepad { type = gamepad }

# Caps Lock: tapped alone = Escape; held with other keys = layer "nav"
map kbd.KEY_CAPSLOCK {
    if single { tap KEY_ESC } else { hold layer nav }
}

layer nav {
    map kbd.KEY_W { hold KEY_UP }
    map kbd.KEY_A { hold KEY_LEFT }
    map kbd.KEY_S { hold KEY_DOWN }
    map kbd.KEY_D { hold KEY_RIGHT }
    map kbd.KEY_Q { disable }
}

# The gamepad's Xbox button switches the flight layer on and off
map pad.BTN_MODE { layer dcs toggle }

layer dcs {
    map pad.BTN_FACE_DOWN { tap KEY_KP5 }
    map pad.ABS_HAT0Y below -0.5 { tap KEY_KP8 }
    map pad.BTN_FACE_RIGHT { hold BTN_FACE_RIGHT }  # still B on the virtual gamepad
}
```

Rules:

1. **Definition**: `layer NAME { … }` at the top level contains one or more
   `map` statements, nothing else. Mappings outside any layer form the
   **base**, which is always active. Layer names follow the rules for
   names (§2) and are unique.
2. **Switching** (statements, §6.10): `hold layer NAME` keeps the layer
   active while the trigger is held; `layer NAME on`, `layer NAME off` and
   `layer NAME toggle` switch it until switched again. A layer is active
   while it is switched on **or** held by at least one `hold layer`.
   `layer NAME off` does not end a `hold layer`. All layers start off.
3. **Which mapping fires**: when a key is pressed, the active layers are
   searched from the most recently activated to the oldest, then the base.
   The first one with a matching mapping wins (within a layer, the usual
   rules apply: device-named first, then modifiers, §5.1, §5.2). A key that
   no active layer maps falls through to the layers below and the base; a
   key that nothing maps passes through to the desktop.
4. **Held keys keep their mapping**: the mapping is chosen when the key is
   pressed. If the layer is switched off while the key is held, the key
   still releases through the mapping that pressed it, so nothing gets
   stuck. Running mappings (macros, toggles) of a layer continue when the
   layer is switched off.
5. **Global**: a layer applies to all input devices, whichever device
   switched it on (a gamepad button can switch a keyboard layer).
6. A layer's mappings can switch layers too, also their own layer.
7. **Names**: a mapping in a layer is named `LAYER:TRIGGER` unless it has
   an `as` name (`nav:kbd.KEY_W`). The same trigger may be mapped once in
   each layer and once in the base.
8. `inpmap macro-trace` activates the layer of the mapping it simulates.

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
| Layers | `hold layer`, `layer … on`, `layer … off`, `layer … toggle` |
| Reusing statements | `call` |

### 6.1 Holding: `hold` and `axis`

`hold KEYS` presses the keys and keeps them pressed until the trigger is
released. It does **not wait**: the next statement runs at once.

```inpmap
map KEY_X {
    hold KEY_Y  # keyboard Y and gamepad A, both held while X is held
    hold BTN_FACE_DOWN
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
        target  = -1.0   # left stick fully up
        attack  = 150ms  # reach it within 150 ms (default 0ms)
        release = 50ms   # back to rest within 50 ms after release (default 0ms)
    }
}
map KEY_S { axis ABS_Y 1.0 (attack 150ms, release 50ms) }  # one-line form
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
statement: `tap BTN_FACE_DOWN (pause 30ms)`.

```inpmap
map KEY_F1 { tap ctrl + KEY_C }  # Ctrl+C

map KEY_F2 {
    with KEY_LEFTSHIFT {  # Shift held around two taps: "AB"
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
    move ABS_X to 1.0 over 500ms  # sweep the left stick right
    move ABS_X to -1.0 over 1s    # and left
}                                 # back to the centre at the end
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
map KEY_F5 {  # autofire while held
    cancel on release
    while held { tap BTN_FACE_DOWN (pause 30ms) }
}

map KEY_F6 {  # autofire on/off with the same key
    toggle { tap BTN_FACE_DOWN (pause 50ms) }
}

map KEY_F7 {  # sweep the stick while tapping
    parallel {
        branch {
            move ABS_X to 1.0 over 500ms
            move ABS_X to 0.0 over 500ms
        }
        branch {
            repeat 5 {
                tap BTN_FACE_LEFT
                wait 100ms
            }
        }
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
| `layer NAME` | the layer is active (§5.6) |
| `not CONDITION` | negation |

```inpmap
map KEY_CAPSLOCK {  # Caps Lock alone: Escape; with another key: Ctrl
    if single { tap KEY_ESC } else { hold KEY_LEFTCTRL }
}

map KEY_F8 {
    if capslock { tap KEY_1 } else { tap KEY_2 }
}
```

### 6.6 Gestures: `on tap`, `on double_tap`, `on long_press`

```inpmap
map KEY_F10 {
    on tap { tap KEY_1 }
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
    on release { tap KEY_2 }  # types 1 on press, 2 on release
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
map KEY_F12 {  # alternate between two actions
    if mode { tap KEY_A } else { tap KEY_B }
    if mode { mode = false } else { mode = true }
}
```

### 6.9 Disabling a key: `disable`

```inpmap
map KEY_INSERT { disable }             # Insert does nothing
map KEY_Q modifiers(ctrl) { disable }  # Ctrl+Q does nothing; Q alone still types q
```

The key is suppressed and nothing is sent instead. `disable` must be the
only statement of the mapping, without options.

### 6.10 Switching layers

| Statement | Meaning |
|---|---|
| `hold layer NAME` | activate the layer until the trigger is released; **does not wait**, like `hold` |
| `layer NAME on` | switch the layer on |
| `layer NAME off` | switch it off (a `hold layer` still keeps it active) |
| `layer NAME toggle` | switch it on if it is off, otherwise off |

```inpmap
map KEY_F1 { layer dcs on }
map KEY_F2 { layer dcs off }
map KEY_F3 {
    if layer dcs { tap KEY_1 } else { tap KEY_2 }
}

layer dcs {
    map KEY_F4 { tap KEY_KP5 }
}
```

See §5.6 for how layers choose mappings.

### 6.11 Reusable blocks: `block` and `call`

A **block** gives a sequence of statements a name, so several mappings can
use it:

```inpmap
version 1
input kbd { name = "AT Translated Set 2 keyboard" }
input pad { path = "/dev/input/by-id/usb-Razer_Razer_Raiju_V3_Pro_Wireless_-event-joystick" }
output keyboard { type = keyboard }
output gamepad { type = gamepad }

block bracket {
    tap ctrl + shift + KEY_LEFTBRACE
}

block close_dialog {
    wait 500ms
    tap KEY_ENTER
    tap KEY_ESC
    tap BTN_FACE_RIGHT
}

let bracket_mode = false

map pad.BTN_FACE_LEFT as alternate {
    if not bracket_mode {
        bracket_mode = true
        tap KEY_ENTER
        call bracket
    } else {
        bracket_mode = false
        call bracket
        call close_dialog
    }
}

map kbd.KEY_LEFTBRACE modifiers(ctrl, shift) as bracket_combo {
    tap KEY_ENTER
    hold ctrl + shift + KEY_LEFTBRACE
    on release { call close_dialog }
}
```

Rules:

1. `block NAME { … }` is written at the top level; `call NAME` may be
   used wherever a statement may stand, also inside `if`, loops,
   `parallel` and `on release`, and inside other blocks.
2. **A call works as if the block's statements were written in its
   place.** So they belong to the calling mapping: its trigger (`hold`,
   `while held`, `if tap`, `if single` refer to it), its options
   (`key_pause`, `cancel on release`, …) and its run (everything they press
   is released when the mapping's run ends).
3. A block may contain any statement except mapping options, `on
   release`, `toggle` and `disable`, which only make sense for a whole
   mapping.
4. A block must not call itself, directly or through other blocks.
5. Block names follow the rules for names (§2) and are unique. Blocks
   take no parameters.
6. Errors inside a block are reported at the block's lines, once, however
   often it is called. A block that is never called gets a warning.

## 7. How mappings run

### 7.1 A run

- Pressing the trigger starts a **run** of the mapping: its statements in
  order. Which mapping runs is decided at this moment, by the held
  modifiers and the active layers (§5.2, §5.6).
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
- Unmapped input that goes to an output (§3.4) counts as a holder too: a
  button held on a pad and by a mapping stays down until both let go. A
  mapping that moves an axis overrides the device's value while it holds;
  afterwards the device's current value applies again.

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

Errors include: syntax errors; unknown names and codes (Linux names of the
face buttons such as `BTN_A` name their replacement, §3.3); codes the device
cannot emit; a device part left out where several outputs could emit the
code; the same trigger and modifiers mapped twice; duplicate names; options
after statements; `toggle` or `disable` not alone; values out of range;
values of the wrong type; `release` of keys never pressed; unused devices; axis
thresholds that are 0, outside −1.0 … 1.0, or on an axis that cannot be a
trigger; unknown, duplicate or empty layers; statements other than `map`
inside a layer; unknown or duplicate blocks, blocks that call themselves,
and statements a block may not contain (§6.11); `to` naming an
unknown output or two outputs of one kind, `own` together with outputs, a
missing `to` where several outputs of a kind exist (§3.4); `emulate` on
an output that is not a gamepad, or with an unknown value (§3.5). At
start: no write access to `/dev/uhid` for an emulating output (§3.5).
When InpMap opens a device: keys without a keyboard output, gamepad
buttons or axes the gamepad output does not have (§3.4 rule 2).

Warnings (the file still loads): blocks that are never called.

Check a file with `inpmap check FILE`.

## 9. Not supported yet

Mouse output (movement, wheel; mice pass through, §3.4 rule 3); analog axes driving analog outputs (e.g.
a stick moving the virtual stick with a curve); mouse movement as a
trigger; dual-role keys
that hold back other keys while undecided; conditions on other held keys;
arithmetic beyond `+=`/`-=`; typing text by
character (codes are key positions); randomised "human" timing beyond
`random`.

## 10. Complete example

This is the example that comes with InpMap: a safe tour of the main
features. `inpmap input-config example` copies it to
`~/.config/inpmap/example.inpmap` and adds your keyboard as an `input`
block after `version 1`; then `inpmap run example --timeout 60` lets you
try it ([usage.md](usage.md#2-your-first-configuration)). Its mappings name
no device, so they work with whichever keyboard you add.

```inpmap
# InpMap example: a safe tour of the main features.
#
# Make your own copy with your keyboard:  inpmap input-config example
# Try it (stops by itself after 60 s):     inpmap run example --timeout 60
# Emergency stop at any time: hold Backspace + Escape + Enter together.
#
# Only F1 to F8, Caps Lock and Insert are remapped; letters type as usual.
# Everything used here is explained in docs/configuration.md.
version 1

output keyboard { type = keyboard }
output gamepad { type = gamepad }

# F1: one key, two devices - keyboard A and gamepad A while F1 is held
map KEY_F1 {
    hold KEY_A
    hold BTN_FACE_DOWN
}

# F2: tap types 1, double tap types 2, long press types 3
map KEY_F2 {
    on tap { tap KEY_1 }
    on double_tap { tap KEY_2 }
    on long_press { tap KEY_3 }
}

# F3: a sequence - Q, a random pause of 40 to 60 ms, then gamepad B
map KEY_F3 {
    tap KEY_Q
    wait random(40ms, 60ms)
    tap BTN_FACE_RIGHT
}

# F4: autofire gamepad A while F4 is held
map KEY_F4 {
    cancel on release
    while held { tap BTN_FACE_DOWN (pause 30ms) }
}

# F5: autofire switched on by one press and off by the next
map KEY_F5 {
    toggle { tap BTN_FACE_DOWN (pause 50ms) }
}

# F6: push the left stick up within 150 ms; it returns within 50 ms on release
map KEY_F6 {
    axis ABS_Y {
        target  = -1.0
        attack  = 150ms
        release = 50ms
    }
}

# Ctrl+F7: copy (Ctrl+C); F7 alone stays F7
map KEY_F7 modifiers(ctrl) { tap ctrl + KEY_C }

# F8: alternates between "Hi" and "Hi!", with a variable and a reusable block
block greet {
    tap shift + KEY_H
    tap KEY_I
}

let first = true

map KEY_F8 {
    if first {
        first = false
        call greet
    } else {
        first = true
        call greet
        tap shift + KEY_1
    }
}

# Caps Lock: tapped alone = Escape; held together with other keys = layer "nav"
map KEY_CAPSLOCK {
    if single { tap KEY_ESC } else { hold layer nav }
}

# While Caps Lock is held, W A S D are arrow keys
layer nav {
    map KEY_W { hold KEY_UP }
    map KEY_A { hold KEY_LEFT }
    map KEY_S { hold KEY_DOWN }
    map KEY_D { hold KEY_RIGHT }
}

# Insert does nothing
map KEY_INSERT { disable }

# With a gamepad: add it as input "pad" (inpmap input-config example), then
# remove the "#" in front of these two lines:
# map pad.ABS_RZ above 0.5 { hold KEY_SPACE }       # R2 pressed more than half: Space
# map pad.ABS_HAT0Y below -0.5 { tap KEY_PAGEUP }   # D-pad up: Page Up
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
        tap BTN_FACE_DOWN (pause 50ms)
    }
}

# Two branches at once: stick sweep while tapping
map kbd.KEY_F4 {
    parallel {
        branch {
            move ABS_X to 1.0 over 500ms
            move ABS_X to 0.0 over 500ms
        }
        branch {
            repeat 5 {
                tap BTN_FACE_LEFT
                wait 100ms
            }
        }
    }
}

# Caps Lock LED decides
map kbd.KEY_F5 {
    if capslock { tap KEY_1 } else { tap KEY_2 }
}

# Gamepad A with Ctrl held on the keyboard, and without
map pad.BTN_FACE_DOWN modifiers(ctrl) { tap KEY_C }
map pad.BTN_FACE_DOWN { hold BTN_FACE_DOWN }
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
        tap BTN_FACE_RIGHT
    }
}

# Gamepad X: first press opens, second press closes
let bracket_mode = false
map pad.BTN_FACE_LEFT as alternate {
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
        tap BTN_FACE_RIGHT
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

Outputs: see §3.3. As triggers (§5.5), the usual axes of a gamepad are:

| Axis | On an Xbox-style pad |
|---|---|
| `ABS_X`, `ABS_Y` | left stick (left/right, up/down) |
| `ABS_RX`, `ABS_RY` | right stick |
| `ABS_Z`, `ABS_RZ` | left and right analog trigger (LT/L2, RT/R2) |
| `ABS_HAT0X`, `ABS_HAT0Y` | D-pad (left/right, up/down) on many pads; others have `BTN_DPAD_*` buttons |

Flight sticks and throttles also use `ABS_THROTTLE`, `ABS_RUDDER` and
further hats (`ABS_HAT1X` …). `inpmap axes FILE` shows what your devices
have.

### 12.3 Keywords

These words are reserved and cannot be used as names:

```text
version settings let input output map as hold tap press release with wait
random repeat while held toggle parallel branch on double_tap long_press if
else single not and keep modifiers ignore ctrl shift alt meta left_ctrl
right_ctrl left_shift right_shift left_alt right_alt left_meta right_meta
within after axis move to over cancel restart key_pause max_run none true
false capslock numlock scrolllock disable above below layer off block call
own
```

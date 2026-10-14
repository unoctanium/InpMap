# Using InpMap

This guide shows how to get started and describes every command. The
configuration language itself is described in
[configuration.md](configuration.md).

The command is written as `inpmap`; [installation.md](installation.md)
shows how to make it available under that name.

## 1. How InpMap works

```text
physical keyboard ──grab──► InpMap ──► virtual keyboard  ──► desktop, games
physical gamepad  ──grab──►        ──► virtual gamepad   ──►
                                   ──► "InpMap forward: …" (everything not mapped)
```

1. InpMap creates the virtual output devices of your configuration.
2. It opens the configured physical devices and **grabs** them, so the
   desktop no longer receives their events directly.
3. Mapped keys and buttons drive the virtual devices. Everything else is
   passed through unchanged by a forwarding device named
   `InpMap forward: <device name>`, so the rest of the keyboard keeps
   working.
4. When InpMap stops, it releases every held key, ungrabs the devices and
   removes all its virtual devices.

## 2. First contact

**Profiles.** Your configurations live in `~/.config/inpmap/`, one file
per profile: the profile `example` is `~/.config/inpmap/example.inpmap`.
Commands take a profile name or a path to a file; without either, they use
the profile `default`:

```sh
inpmap run                     # ~/.config/inpmap/default.inpmap
inpmap run example             # ~/.config/inpmap/example.inpmap
inpmap run /tmp/test.inpmap    # a file anywhere (ends in .inpmap or contains a /)
```

**1. Get the example with your keyboard.**

```sh
inpmap input-config example
```

This creates `~/.config/inpmap/example.inpmap` from the example that comes
with InpMap, a safe tour of the main features
([configuration.md §10](configuration.md#10-complete-example)), and asks
for your keyboard:

```text
Input devices for ~/.config/inpmap/example.inpmap (grouped by physical device):

  Razer Razer Raiju V3 Pro(Wireless) (1532:1027)
      1               gamepad     11 buttons  Generic X-Box pad
      2               keyboard   267 keys     Razer Razer Raiju V3 Pro(Wireless) Keyboard
      ...
  2.4G Dongle (4348:4744)
      5               keyboard   163 keys     2.4G Dongle
      6               keyboard   130 keys     2.4G Dongle Keyboard
      ...
> i
Press a key or button on the device you want (Ctrl+C to cancel) ...
That was 5: 2.4G Dongle (keyboard).
5 selected as 'kbd': 2.4G Dongle
> w
```

Many keyboards and gamepads appear as several devices (keys, media keys,
mouse, touchpad). Type `i` and press a key on your keyboard: InpMap finds
the right part. `w` writes and quits. Details:
[§3](#inpmap-input-config).

**2. Try it**, with a time limit:

```sh
inpmap run example --timeout 60
```

Now press F1 to F8, Caps Lock (alone, and held together with W A S D) and
Insert, and compare with the comments in the file. Letters type as usual.
InpMap stops by itself after 60 seconds or with Ctrl+C; the emergency stop
**Backspace + Escape + Enter** (held together) always works.

**3. Your own configuration.** Create the profile `default`, which the
service uses later ([installation.md §6](installation.md#6-running-in-the-background-user-service)):

```sh
inpmap input-config            # pick your devices; creates ~/.config/inpmap/default.inpmap
inpmap detect                  # press keys: see them written as triggers
$EDITOR ~/.config/inpmap/default.inpmap
inpmap check                   # every problem with its position
inpmap run --timeout 60
```

`inpmap detect` prints each key you press as you would write it in a
mapping (`kbd.KEY_F7`, `kbd.KEY_F7 modifiers(ctrl)`, `pad.ABS_RZ above
0.5`); copy what you need into the file. `inpmap macro-trace` simulates
a mapping without any device. A profile without mappings is valid: InpMap
then starts but does nothing.

## 3. Commands

General options: `--version` prints the version; `-v`/`--verbose` (before
the command, e.g. `inpmap -v run …`) enables debug logging.

`PROFILE_OR_FILE` is a profile name (`dcs` = `~/.config/inpmap/dcs.inpmap`)
or a path (it ends in `.inpmap` or contains a `/`). Where it is in
brackets it may be left out; then the profile `default` is used. A
missing profile is reported with the command that creates it.

### `inpmap check`

```text
inpmap check [PROFILE_OR_FILE]
```

Validates the configuration and prints a summary of inputs, outputs, mappings and
variables. Warnings go to the error output; the file is still valid.
Touches no devices.

### `inpmap codes`

```text
inpmap codes [FILTER]
```

Lists the names you can use in a configuration: every `KEY_*` and `BTN_*`
code (all of them can be triggers) and the gamepad axes, with the output
type that can send each one. `FILTER` keeps the names that contain it,
in any case:

```text
$ inpmap codes kp1
NAME                         CODE  SENT BY
KEY_KP1                        79  keyboard
$ inpmap codes btn_a
NAME                         CODE  SENT BY
BTN_SOUTH                     304  gamepad  (also BTN_A)
```

"only as input" marks codes that no InpMap output can send (e.g. mouse
buttons); they can still trigger mappings.

### `inpmap axes`

```text
inpmap axes [PROFILE_OR_FILE] [--timeout SECONDS]
```

Shows the sticks, analog triggers and D-pad axes of the configuration's
input devices with their current values, as `above`/`below` use them
([configuration.md §5.5](configuration.md#55-sticks-analog-triggers-and-the-d-pad-as-triggers)),
and whether each threshold of your mappings is on. Move the stick or
press the trigger and watch the value; Ctrl+C stops.

```text
pad        ABS_X        -0.02   (-32768..32767)
pad        ABS_RZ       +0.73   (0..255)   r2: above 0.5 ON
pad        ABS_HAT0Y    -1.00   (-1..1)   dpad_up: below -0.5 ON
```

The devices are only read, not grabbed. A device that the InpMap service
holds cannot be read by anyone else; `axes` says so, and you stop the
service for the moment (`systemctl --user stop 'inpmap@*'`).

### `inpmap detect`

```text
inpmap detect [PROFILE_OR_FILE] [--timeout SECONDS]
```

Shows every key or button you press, and every stick, analog trigger or
D-pad you move past half way, written as you would write the trigger of a
mapping, with the input names of the profile and the modifiers you hold:

```text
kbd.KEY_F7                       2.4G Dongle
kbd.KEY_F7 modifiers(ctrl)       2.4G Dongle
pad.BTN_SOUTH                    Generic X-Box pad
pad.ABS_RZ above 0.5             Generic X-Box pad
pad.ABS_HAT0Y below -0.5         Generic X-Box pad   (D-pad up)
KEY_VOLUMEUP                     2.4G Dongle Keyboard   (not in default; add it with: inpmap input-config default)
```

Copy the trigger into a mapping, e.g. `map kbd.KEY_F7 modifiers(ctrl) { … }`.
Pressing a modifier alone prints nothing. Devices are only read, not
grabbed, so your key presses also reach the terminal (they are thrown away
when `detect` ends). Devices held by the InpMap service cannot be read;
`detect` says so. Without a profile file, triggers are printed without
input names. Ctrl+C stops.

### `inpmap input-config`

```text
inpmap input-config [PROFILE_OR_FILE] [--all]
```

Lists the input devices with keys or buttons, grouped by physical device
(devices are listed from `/sys`, so this works before any permission
setup), and adds `input` blocks for the ones you choose to the
configuration.
Built-in system buttons (power and sleep buttons, brightness keys) are
left out; `--all` lists them too.

| Command | Meaning |
|---|---|
| `N` | select or deselect device number `N`; the name is suggested (`kbd`, `pad`, `kbd2`, …) |
| `N NAME` | select device `N` under the name `NAME` (or rename it) |
| `i` | identify: press a key or button on a device within 15 seconds, and it is selected. Needs read access to the devices. |
| `l` | list again |
| `w` | write and quit |
| `q` | quit without changes |

Devices that the file already uses are marked with their name (`[kbd]`).
The new blocks select a device by its `/dev/input/by-id` link if it has
one (stable when you plug it into another port), otherwise by its name if
no other device has the same name, otherwise by its `/dev/input/by-path`
link.

The file is changed as text: the new blocks are inserted after the last
`input` block (or after `version`), everything else stays as it is. The
previous version is kept with `.bak` appended to its name. Afterwards the
file is checked like with `inpmap check`. A file that does not exist is
created: the profile `example` from the example that comes with InpMap
(§2), every other one as a starter file with a keyboard and a gamepad
output and a commented example mapping. A file with syntax errors is not
changed.

### `inpmap fmt`

```text
inpmap fmt PROFILE_OR_FILE... [--check] [--diff]
inpmap fmt -
```

Rewrites configuration files in one consistent layout. Only the layout
changes, never the meaning: before writing, InpMap parses the result again
and checks that it describes exactly the same configuration; otherwise
the file is left alone and the problem is reported. A file with syntax
errors is not touched. Files are replaced atomically; there is no backup
file, so use `--diff` first if you are unsure (or keep the file in git).

| Option | Meaning |
|---|---|
| `--check` | change nothing; list the files that are not formatted and exit with 1 (for scripts) |
| `--diff` | change nothing; show what would change |
| `-` | read from standard input, write the result to standard output (for editors) |

**Formatting rules:**

1. **Indentation:** 4 spaces per level; tabs become spaces.
2. **One statement per line.** Statements joined with `;` are put on
   separate lines, except inside a block that stays on one line (rule 3).
3. **Short blocks:** a block (`{ … }`) with exactly one statement or
   property and nothing nested stays on one line if it was written on one
   line and the line stays within 100 characters:
   `on tap { tap KEY_1 }`, `output gamepad { type = gamepad }`. Every other
   block is written over several lines, its closing `}` on its own line.
4. **Spaces:** one space between words and around `=`, `==`, `!=`, `+=`,
   `-=` and the `+` of chords (`tap ctrl + KEY_C`); a space before `{`;
   none inside parentheses, one after each comma: `modifiers(ctrl, shift)`,
   `(pause 30ms)`, `random(40ms, 60ms)`.
5. **`else`** follows the closing brace: `} else {`, `} else if … {`.
6. **Blank lines:** kept where you put them, but at most one in a row;
   none at the start or end of a block or the file.
7. **Comments** are kept with their text unchanged. A comment on its own
   line is indented like the line after it. Comments at the end of
   consecutive lines are aligned to one column, at least two spaces after
   the longest of those lines.
8. **Alignment:** in consecutive property lines of a `settings`,
   `input`, `output` or `axis` block, the `=` signs are aligned
   (`target  = -1.0`, `attack  = 150ms`). Nothing else is aligned, not
   even gesture handlers (`on tap { … }`).
9. **Kept as written:** the order of all statements, names, numbers
   (`0.5`, `-1.0`), durations (`1.5s`), strings, and whether a device or
   an `as` name is written.
10. Long lines are not wrapped.

All examples in this documentation and the example that comes with InpMap are
formatted this way (a test checks it).

### `inpmap devices`

```text
inpmap devices [--all]
```

Lists the physical input devices with keys or buttons (`--all`: all
devices), one entry per event device, with their names and their
`/dev/input/by-id` or `by-path` links, and reports device nodes you are
not allowed to read. (`inpmap input-config` shows the same devices grouped
per physical device.) While InpMap is running,
its own devices appear too, marked `[InpMap virtual device]`; they are never
selected by an `input` block.

### `inpmap run`

```text
inpmap run [PROFILE_OR_FILE] [--timeout SECONDS] [--wait-for-devices]
```

- `--timeout SECONDS`: stop by itself after this time.
- `--wait-for-devices`: if an input device cannot be opened at startup
  (missing, no permission), wait for it instead of failing. The service
  uses this.

Runs the remapper in the foreground:

1. checks the configuration;
2. creates the virtual output devices;
3. opens the configured input devices and checks that each has the keys and
   buttons mapped for it;
4. waits until no key is held on a device, then grabs it;
5. remaps until Ctrl+C, `SIGTERM`, `SIGHUP` (terminal closed), the
   `--timeout` or the emergency stop (below);
6. releases everything, ungrabs and removes the virtual devices.

Behaviour while running:

- **Emergency stop**: hold **Backspace, Escape and Enter** at the same time
  (in any order) on a remapped device, and InpMap stops at once, releases
  everything and gives the devices back to the desktop. Use it when a
  configuration makes the keyboard unusable. It always works, whatever the
  configuration maps these keys to; the keys also reach the focused
  application as usual. A stopped service stays stopped until you start it
  again or log in again.
- **Device lost** (unplugged, wireless sleep): its held outputs are released
  at once; other devices keep working; InpMap checks every second and
  grabs the device again when it is back. A device missing at **startup**
  is an error, because it usually means a wrong `name` or `path`, unless
  `--wait-for-devices` is given.
- **Keyboard LEDs** (Caps Lock, Num Lock, Scroll Lock): the desktop sets
  them on the forwarding device; InpMap copies them to the physical
  keyboard.
- **Event loss** under heavy load: key states are resynchronised, so no key
  stays stuck.
- **Desktop settings per device** (e.g. a keyboard layout for one keyboard)
  apply to the forwarding device, which has the original's vendor and
  product ID.
- **Force feedback** (rumble) is not supported.
- A device grabbed by another program (e.g. Input Remapper) cannot be used
  at the same time: InpMap reports "already grabbed by another program".

### `inpmap macro-trace`

```text
inpmap macro-trace PROFILE_OR_FILE MAPPING [options]
```

Runs one mapping on a simulated clock and prints every output with its
time. No devices are opened or created, so this is a safe way to try out
timing, gestures and conditions.

`MAPPING` is the mapping's name: its `as` name, or the trigger as written
(`KEY_F9`, `pad.BTN_EAST`, `KEY_LEFTBRACE+ctrl+shift`; `inpmap check` lists
them).

| Option | Meaning |
|---|---|
| `--hold-ms N` | how long each press lasts (default 100) |
| `--press-at MS` | press the trigger at this time; repeat the option for several presses (default: once at 0) |
| `--other-key-at MS` | press another key at this time, e.g. to try `if single` |
| `--modifiers NAMES` | modifiers held, e.g. `ctrl,right_shift`, or `none` (default: those the mapping requires) |
| `--led NAME` | treat `capslock`, `numlock` or `scrolllock` as lit (repeatable) |
| `--until-ms N` | simulate up to this time |
| `--seed N` | seed for random waits, for repeatable output |

```text
$ inpmap macro-trace example KEY_F2 --press-at 0 --press-at 150 --hold-ms 50
      0.0 ms  >> input pressed
     50.0 ms  >> input released
    150.0 ms  >> input pressed
    200.0 ms  >> input released
    200.0 ms  keyboard   KEY_2            down
    210.0 ms  keyboard   KEY_2            up
```

Lines with `>>` are the simulated inputs. A mapping in a layer is
simulated with its layer active (`>> layer nav active`). For mappings with modifiers the
timeline also shows when the modifiers are hidden from the desktop and
restored.

### `inpmap test-outputs`

```text
inpmap test-outputs [PROFILE_OR_FILE] [--delay S] [--hold S] [--only DEVICE] [--no-emit]
```

Creates the configured virtual devices, waits `--delay` seconds (default 3,
time to start `evtest`), then presses and releases every output code used
by the mappings, each for `--hold` seconds (default 0.2). Physical devices
are not touched.

- `--only DEVICE`: only this output device (repeatable).
- `--no-emit`: only create the devices for `--delay` seconds, for
  inspection.

Keyboard output goes to the focused window like real typing. Watch the
gamepad with `evtest` (choose "InpMap Virtual Gamepad" or the name from
your configuration).

### `inpmap udev-rules`

```text
inpmap udev-rules [PROFILE_OR_FILE]
```

Prints udev rules that give your login session access to `/dev/uinput` and
the input devices of the configuration, which must be connected. Nothing is installed;
see [installation.md](installation.md#3-device-permissions).

### `inpmap service-unit`

```text
inpmap service-unit
```

Prints the systemd user unit `inpmap@.service` with the path of this
installation: `inpmap@NAME` runs `inpmap run --wait-for-devices NAME`, i.e.
the profile `NAME`. The profiles found in `~/.config/inpmap/` are listed in
its comments with their check result. Nothing is installed; see
[installation.md §6](installation.md#6-running-in-the-background-user-service).

### `inpmap syntax-file`

```text
inpmap syntax-file kate|nano
```

Prints InpMap's syntax highlighting file for Kate/KWrite or nano; see
[installation.md §5](installation.md#5-optional-syntax-highlighting) for
where to put it.

### Exit codes

| Code | Meaning |
|---|---|
| 0 | success |
| 1 | invalid configuration |
| 2 | wrong command-line usage |
| 3 | device error (missing device, no permission, already grabbed, …) |
| 130 | interrupted (Ctrl+C during `test-outputs`) |

## 4. The virtual devices

- **Keyboard**: has every keyboard key, so the desktop treats it as a
  normal keyboard.
- **Gamepad**: the standard buttons, D-pad, two sticks and two triggers
  ([configuration.md §3.3](configuration.md#33-what-each-output-can-emit)),
  so games and SDL recognise it as a gamepad and the desktop does not
  mistake it for a keyboard.
- Both report the USB vendor ID `0x0001` (product `0x0001` keyboard,
  `0x0002` gamepad); they do not pretend to be real hardware.

## 5. Troubleshooting

| Problem | What to do |
|---|---|
| "cannot create virtual …" or "no read access to …" | set up permissions ([installation.md §3](installation.md#3-device-permissions)) |
| "no readable device named …" | the `name` is wrong, the device is not connected, or you lack permission; check `inpmap devices`, or use `path` |
| "N devices are named …" | use `path` with a `/dev/input/by-id` link instead of `name` |
| "already grabbed by another program" | the InpMap service is running (`systemctl --user stop 'inpmap@*'`), or another remapper (e.g. Input Remapper) uses the device |
| the service does not run | `systemctl --user status inpmap@default` and `journalctl --user -u inpmap@default` show the reason (an invalid configuration is reported with its line number) |
| "no such configuration" | the profile does not exist yet; create it with the command shown (`inpmap input-config NAME`) |
| a mapped key does nothing | the trigger may be on another entry of the same keyboard (check with `evtest`); a mapping without `modifiers(…)` does not fire while a modifier is held |
| a key types the wrong character | codes are key positions: `KEY_Y` types `z` on a German layout |
| holding a mapped key types `yyyy` | that is the desktop's key repeat for a held key; use `tap` for a single press |
| a game ignores very short taps | increase the key pause (`settings { key_pause = 30ms }`) |
| the keyboard is unusable because of a mapping | hold Backspace + Escape + Enter together: InpMap stops (emergency stop) |
| more detail needed | run with `inpmap -v run …` for debug logging |

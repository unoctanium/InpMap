# Using InpMap

This guide shows how to write a first configuration and describes every
command. The configuration language itself is described in
[configuration.md](configuration.md).

The examples call the program as `.venv/bin/inpmap` from the InpMap
directory (see [installation.md](installation.md)); after
`source .venv/bin/activate`, plain `inpmap` works too.

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

## 2. Your first configuration

**Find your device.**

```sh
.venv/bin/inpmap devices
```

```text
/dev/input/event7: '2.4G Dongle'
    keys: 248, gamepad buttons: 0
    /dev/input/by-id/usb-4348_2.4G_Dongle-event-kbd
```

Each entry shows the device node, the kernel name, how many keys and
gamepad buttons it has, and stable links to it. Many keyboards show up
several times (e.g. a second entry for media keys). If unsure which entry
is the right one, run `evtest`, pick an entry and press the key you want to
map: the right entry prints events.

**Write the configuration.** Start from the example:

```sh
cp config/example.inpmap config/local.inpmap
$EDITOR config/local.inpmap
```

Put your device's name or by-id link into the `input` block:

```text
input kbd {
    path = "/dev/input/by-id/usb-4348_2.4G_Dongle-event-kbd"
}
```

and write your mappings ([configuration.md](configuration.md)). Files named
`config/local*` are ignored by git, so your personal configuration stays
out of the repository.

**Check it.**

```sh
.venv/bin/inpmap check config/local.inpmap
```

prints a summary or every problem with its position
(`config/local.inpmap:14:9: unknown key code 'KEY_QQ'`).

**Simulate a mapping** without any devices:

```sh
.venv/bin/inpmap macro-trace config/local.inpmap KEY_F10 --press-at 0 --press-at 150 --hold-ms 50
```

**Try it for real**, with a time limit:

```sh
.venv/bin/inpmap run config/local.inpmap --timeout 30
```

It stops by itself after 30 seconds, or earlier with Ctrl+C. Use a time
limit for first tests: if a mapping makes the keyboard hard to use, it
ends on its own.

## 3. Commands

General options: `--version` prints the version; `-v`/`--verbose` (before
the command, e.g. `inpmap -v run …`) enables debug logging.

### `inpmap check`

```text
inpmap check FILE
```

Validates `FILE` and prints a summary of inputs, outputs, mappings and
variables. Warnings go to the error output; the file is still valid.
Touches no devices.

### `inpmap devices`

```text
inpmap devices [--all]
```

Lists the physical input devices with keys or buttons (`--all`: all
devices), their names and their `/dev/input/by-id` or `by-path` links, and
reports device nodes you are not allowed to read. While InpMap is running,
its own devices appear too, marked `[InpMap virtual device]`; they are never
selected by an `input` block.

### `inpmap run`

```text
inpmap run FILE [--timeout SECONDS] [--wait-for-devices]
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
inpmap macro-trace FILE MAPPING [options]
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
$ inpmap macro-trace config/example.inpmap KEY_F10 --press-at 0 --press-at 150 --hold-ms 50
      0.0 ms  >> input pressed
     50.0 ms  >> input released
    150.0 ms  >> input pressed
    200.0 ms  >> input released
    200.0 ms  keyboard   KEY_2            down
    210.0 ms  keyboard   KEY_2            up
```

Lines with `>>` are the simulated inputs. For mappings with modifiers the
timeline also shows when the modifiers are hidden from the desktop and
restored.

### `inpmap test-outputs`

```text
inpmap test-outputs FILE [--delay S] [--hold S] [--only DEVICE] [--no-emit]
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
inpmap udev-rules FILE
```

Prints udev rules that give your login session access to `/dev/uinput` and
the input devices of `FILE`, which must be connected. Nothing is installed;
see [installation.md](installation.md#3-device-permissions).

### `inpmap service-unit`

```text
inpmap service-unit FILE
```

Prints a systemd user unit that runs `inpmap run --wait-for-devices FILE`
at login, with the absolute paths of this installation. Nothing is
installed; see
[installation.md §6](installation.md#6-running-in-the-background-user-service).

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
| "already grabbed by another program" | the InpMap service is running (`systemctl --user stop inpmap`), or another remapper (e.g. Input Remapper) uses the device |
| the service does not run | `systemctl --user status inpmap` and `journalctl --user -u inpmap` show the reason (an invalid configuration is reported with its line number) |
| a mapped key does nothing | the trigger may be on another entry of the same keyboard (check with `evtest`); a mapping without `modifiers(…)` does not fire while a modifier is held |
| a key types the wrong character | codes are key positions: `KEY_Y` types `z` on a German layout |
| holding a mapped key types `yyyy` | that is the desktop's key repeat for a held key; use `tap` for a single press |
| a game ignores very short taps | increase the key pause (`settings { key_pause = 30ms }`) |
| the keyboard is unusable because of a mapping | hold Backspace + Escape + Enter together: InpMap stops (emergency stop) |
| more detail needed | run with `inpmap -v run …` for debug logging |

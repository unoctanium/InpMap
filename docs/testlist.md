# Tests at the PC (2026-10-14)

> **Results (2026-10-14):** all passed except 4a (built-in "Power Button"
> listed twice; fixed: built-in system buttons are hidden unless `--all`)
> and 5g (login, not done yet). Re-test: 4a list and 5g.
> Section 7 (axes, added later): passed (2026-10-14).

Manual tests for everything built while you were away: the emergency stop,
`inpmap input-config`, numpad keys, the user service and profiles. Do them
in this order; each test needs the previous ones only where noted.

Commands are for fish (your shell). Run them in the InpMap directory:

```sh
cd ~/Projects/InpMap
```

Report back: for each test either "OK" or what you saw instead (copy the
output or the log lines). The checklist at the end can be copied into
your reply.

## Next: migration and the new commands (added 2026-10-14)

Do this section first; sections 0 to 8 below are the earlier tests (all
passed except 5g). From here on the command is plain `inpmap` and
configurations live in `~/.config/inpmap/`.

### M1. Migrate your setup

```sh
cd ~/Projects/InpMap
systemctl --user stop 'inpmap@*' inpmap
systemctl --user disable inpmap@local inpmap      # whichever is enabled; errors for the other are fine
mkdir -p ~/.local/bin
ln -s ~/Projects/InpMap/.venv/bin/inpmap ~/.local/bin/inpmap
inpmap --version
mkdir -p ~/.config/inpmap
cp config/local.inpmap ~/.config/inpmap/default.inpmap
inpmap check
```

**Expected:** `inpmap 0.1.0`; `check` (without a name) says
`/home/odo/.config/inpmap/default.inpmap: OK` with your mappings. (If
`inpmap` is not found, log out and in again: `~/.local/bin` is then on the
`PATH`.) Keep `config/local.inpmap` until everything works, then delete it.

### M2. The new service unit

```sh
rm -f ~/.config/systemd/user/inpmap.service ~/.config/systemd/user/inpmap@.service
inpmap service-unit > ~/.config/systemd/user/inpmap@.service
head -12 ~/.config/systemd/user/inpmap@.service
systemctl --user daemon-reload
systemctl --user enable --now inpmap@default
systemctl --user status inpmap@default
```

**Expected:** the comments list `default  OK`; the unit's `ExecStart` ends
with `run --wait-for-devices %i`; status `active (running)`; your mappings
work. Then log out and in again (this is also the open test 5g):
**expected** `inpmap@default` is running again without doing anything.

### M3. The example as first contact

```sh
systemctl --user stop 'inpmap@*'
inpmap input-config example
```

Press `i`, then a letter key, then `w`. **Expected:** the dongle keyboard is
selected as `kbd`; `Check: OK.`; `~/.config/inpmap/example.inpmap` starts
with `# InpMap example` and has your `input kbd` block after `version 1`.

```sh
inpmap run example --timeout 60
```

**Expected** (in a text editor):

| Key | Result |
|---|---|
| F1 held | `a` with key repeat (and gamepad A, see `evtest`) |
| F2 tap / double tap / long press | `1` / `2` / `3` |
| F3 | `q` |
| Ctrl+F7 | copies (Ctrl+C); F7 alone does what F7 always does |
| F8, F8 again | `Hi`, then `Hi!` |
| Caps Lock tapped | Escape |
| Caps Lock held + W A S D | arrow keys |
| Insert | nothing |
| letters | normal |

F4, F5, F6 act on the virtual gamepad only (watch with `evtest` on
"InpMap gamepad").

### M4. detect

```sh
inpmap detect
```

Press F7, Ctrl+F7, a gamepad button, R2, D-pad up, and a volume key; then
Ctrl+C. **Expected:** lines like `kbd.KEY_F7`, `kbd.KEY_F7
modifiers(ctrl)`, `pad.BTN_SOUTH`, `pad.ABS_RZ above 0.5`,
`pad.ABS_HAT0Y below -0.5 … (D-pad up)`, and for the volume key (on another
part of the keyboard) `KEY_VOLUMEUP … (not in default; add it with: inpmap
input-config default)`. Pressing Ctrl alone prints nothing. After Ctrl+C,
the letters you typed do not appear at the shell prompt.

### M5. A profile without mappings

```sh
inpmap input-config empty          # pick your keyboard, then w
inpmap check empty
inpmap run empty --timeout 10
```

**Expected:** `check` ends with `note: no mappings yet; InpMap starts but
grabs nothing and does nothing`; `run` logs `no mappings in this
configuration: nothing is grabbed or created`, the keyboard works normally,
and `inpmap devices | grep -i inpmap` shows no InpMap devices meanwhile.
Afterwards: `rm ~/.config/inpmap/empty.inpmap`, and start your service
again: `systemctl --user start inpmap@default`.

### M6. Syntax files (optional)

Install them as in `docs/installation.md` §5 (`inpmap syntax-file kate >
…`). **Expected:** Kate highlights `~/.config/inpmap/default.inpmap`.

## Safety first

- **Emergency stop:** hold **Backspace + Escape + Enter** together on the
  keyboard. InpMap stops at once and gives the keyboard back. Test 1
  tries it before anything else.
- Foreground tests use `--timeout`, so they also end by themselves.
- The mouse is never grabbed: you can always click into a terminal and
  run `systemctl --user stop inpmap 'inpmap@*'`.

## 0. Preparation

```sh
git log --oneline -1
.venv/bin/inpmap --version
.venv/bin/inpmap check config/local.inpmap
```

**Expected:**
- the last commit is the one adding this file (`docs/testlist.md`);
- `inpmap 0.1.0`;
- `config/local.inpmap: OK (version 1)` followed by the summary. Your
  mappings all name their device, so they show as `kbd KEY_X`,
  `pad BTN_WEST` and so on.

## 1. Emergency stop (foreground)

```sh
.venv/bin/inpmap run config/local.inpmap --timeout 60
```

1. Wait for `INFO inpmap.runtime: remapping active`.
2. Press X once: `y` is typed (your mapping works).
3. Hold **Backspace**, **Escape** and **Enter** together (any order).

**Expected:**
- InpMap stops at once, without waiting for the 60 seconds. The last
  lines are:
  ```text
  WARNING inpmap.runtime: emergency stop requested (Backspace+Escape+Enter held)
  INFO inpmap.runtime: stopping (emergency stop: Backspace+Escape+Enter)
  ...
  stopped (emergency stop: Backspace+Escape+Enter); all devices released
  ```
- `echo $status` prints `0`.
- The keyboard works normally again: X types `x`.
- The three keys also reached the terminal (an empty Enter and so on).
  That is expected and harmless.

## 2. `inpmap codes`

```sh
.venv/bin/inpmap codes kp
.venv/bin/inpmap codes btn_a
.venv/bin/inpmap codes abs
```

**Expected:**
- `kp`: 22 lines from `KEY_KPASTERISK` (55) to `KEY_KPRIGHTPAREN` (180),
  all "keyboard", among them `KEY_KP1 79` and `KEY_KPENTER 96`;
- `btn_a`: `BTN_SOUTH  304  gamepad  (also BTN_A)`;
- `abs`: `ABS_X` … `ABS_RZ` as "gamepad axis (stick)" or "(trigger)", and
  since test 7 was added also `ABS_THROTTLE`, `ABS_RUDDER`, …,
  `ABS_HAT0X` … `ABS_HAT3Y` as "- (only as input)".

## 3. Numpad output

This shows that the virtual keyboard sends numpad codes, which DCS World
and Flight Simulator need. It uses a copy, so your configuration stays
unchanged.

```sh
cp config/local.inpmap /tmp/numpad.inpmap
echo 'map kbd.KEY_F8 { tap KEY_KP1; tap KEY_KPENTER }' >> /tmp/numpad.inpmap
.venv/bin/inpmap check /tmp/numpad.inpmap
.venv/bin/inpmap run /tmp/numpad.inpmap --timeout 60
```

In a **second terminal**: `evtest`, then choose **InpMap Virtual Keyboard**.
Then press **F8** once.

**Expected:**
- `check` says OK and lists `kbd.KEY_F8: kbd KEY_F8 -> macro (2 steps)`;
- evtest shows `code 79 (KEY_KP1), value 1`, then `value 0`, then
  `code 96 (KEY_KPENTER)` value 1 and 0;
- in a text field with Num Lock on, F8 types `1` followed by Enter.

Optional: if DCS World or Flight Simulator is installed, bind something to
"Num 1" in the game and press F8.

Stop with Ctrl+C (or wait for the timeout).

## 4. `inpmap input-config`

### 4a. New file, identifying devices by key press

```sh
.venv/bin/inpmap input-config /tmp/new.inpmap
```

**Expected:** a list grouped by physical device. Numbers may differ; on
your PC it looked like this:

```text
  Razer Razer Raiju V3 Pro(Wireless) (1532:1027)
      4               keyboard   267 keys     Razer Razer Raiju V3 Pro(Wireless) Keyboard
      5               mouse        5 keys     Razer Razer Raiju V3 Pro(Wireless) Mouse
      6               touchpad     5 keys     Razer Razer Raiju V3 Pro(Wireless) Touchpad
      7               gamepad     11 buttons  Generic X-Box pad
  2.4G Dongle (4348:4744)
      8               keyboard   163 keys     2.4G Dongle
      9               keyboard   130 keys     2.4G Dongle Keyboard
     10               mouse        5 keys     2.4G Dongle Mouse
```

Then:

1. Type `i` and Enter, then press a **button on the gamepad** (e.g. A)
   within 15 seconds.
   **Expected:** `That was 7: Generic X-Box pad (gamepad).` and
   `7 selected as 'pad': Generic X-Box pad`.
2. Type `i` and Enter, then press a **letter key** (e.g. A).
   **Expected:** `That was 8: 2.4G Dongle (keyboard).` and
   `8 selected as 'kbd'`. The terminal may still show the `a` you pressed,
   but it is discarded: the next command works normally.
3. Type `l` and Enter. **Expected:** both entries are marked, `+ pad` and
   `+ kbd`.
4. Type `w` and Enter.
   **Expected:** the two `input` blocks with `/dev/input/by-id/...` paths
   are shown, then `Now add your mappings, then run inpmap check on the
   file.`

```sh
cat /tmp/new.inpmap
```

**Expected:** a starter file with `version 1`, `input pad`, `input kbd`,
`output keyboard`, `output gamepad` and a commented example mapping.

### 4b. Adding to an existing file

```sh
cp config/local.inpmap /tmp/t.inpmap
.venv/bin/inpmap input-config /tmp/t.inpmap
```

**Expected:** the dongle keyboard entry is marked `[kbd]`, the gamepad
entry `[pad]`.

1. Type the number of the **2.4G Dongle Keyboard** entry (9 above) and
   Enter. **Expected:** `9 selected as 'kbd2'`.
2. Type the gamepad's number (7). **Expected:**
   `7 is already in the file as 'pad'.`
3. Type `w`. **Expected:** `Added to /tmp/t.inpmap:` with `input kbd2`,
   `The previous version is in /tmp/t.inpmap.bak.` and `Check: OK.`

```sh
diff /tmp/t.inpmap.bak /tmp/t.inpmap
```

**Expected:** only the four new lines (`input kbd2 { … }` plus a blank
line), placed right after your `input pad` block.

### 4c. Quit without changes

```sh
.venv/bin/inpmap input-config /tmp/t.inpmap
```

Type `9`, then `q`. **Expected:** `No changes written.`, and
`diff /tmp/t.inpmap.bak /tmp/t.inpmap` shows the same four lines as in 4b,
nothing more.

## 5. User service (single configuration)

### 5a. Install and start

```sh
mkdir -p ~/.config/systemd/user
.venv/bin/inpmap service-unit config/local.inpmap > ~/.config/systemd/user/inpmap.service
cat ~/.config/systemd/user/inpmap.service
systemctl --user daemon-reload
systemctl --user enable --now inpmap.service
systemctl --user status inpmap
```

**Expected:**
- the unit contains `ExecStart="/home/odo/Projects/InpMap/.venv/bin/python3" -m inpmap run --wait-for-devices "/home/odo/Projects/InpMap/config/local.inpmap"`;
- `enable` reports a created symlink;
- status shows `Active: active (running)`. The last log lines include
  `opened input 'kbd'`, `opened input 'pad'`, `grabbed ...` for both, and
  `remapping active`.

### 5b. Mappings work under the service

Try X (types `y`), F10 (tap, double tap, long press), the bracket combo
(Ctrl+Shift+[) and the Razer pad's alternate button, as in your earlier
tests.

**Expected:** everything behaves as in the foreground.

```sh
journalctl --user -u inpmap -b --no-pager | tail -20
```

**Expected:** the same log lines as in a terminal. No raw keystrokes are
logged.

### 5c. Emergency stop under the service

Hold Backspace + Escape + Enter.

```sh
systemctl --user status inpmap
```

**Expected:** `Active: inactive (dead)` (stopped, **not** restarted), and
the log shows `emergency stop requested`. The keyboard types normally.

Start it again:

```sh
systemctl --user start inpmap
```

### 5d. Gamepad switched off at start

1. Unplug the Razer pad's USB receiver (or cable). Switching the pad off
   may not be enough: a receiver can keep its devices while the pad is
   off.
2. `systemctl --user restart inpmap`
3. `journalctl --user -u inpmap -n 20 --no-pager`

**Expected:** the service is running (not failed), and the log shows
`WARNING inpmap.runtime: waiting for input 'pad': ... does not exist`
once, not every second. The keyboard mappings work.

4. Plug the receiver in again (and switch the pad on).

**Expected:** within about 1–2 seconds the log shows
`opened input 'pad'`, `grabbed ...` and `remapping active`, and the pad's
mapping works.

### 5e. Invalid configuration: no restart loop

1. Back up your configuration and add a broken line:
   ```sh
   cp config/local.inpmap /tmp/local.backup
   echo 'map kbd.KEY_F7 { tap KEY_QQ }' >> config/local.inpmap
   systemctl --user restart inpmap
   systemctl --user status inpmap
   ```
   **Expected:** `Active: failed (Result: exit-code)`, and the status lines
   show `/home/odo/Projects/InpMap/config/local.inpmap:NN:CC: unknown key code 'KEY_QQ'`
   with the line number. Run `status` again after 10 seconds: it is still `failed`, with
   no `activating (auto-restart)` in between.
2. Repair it:
   ```sh
   cp /tmp/local.backup config/local.inpmap
   .venv/bin/inpmap check config/local.inpmap
   systemctl --user restart inpmap
   ```
   **Expected:** check OK; the service is `active (running)` again.

### 5f. Holding the devices

While the service runs:

```sh
.venv/bin/inpmap run config/local.inpmap --timeout 10
```

**Expected:** exit with
`error: ... already grabbed by another program`, and exit status 3
(`echo $status`).

### 5g. Login

Log out of KDE and log in again.

**Expected:** `systemctl --user status inpmap` shows `active (running)`,
started at the login time, and the mappings work without doing anything.

### 5h. Stop and clean up

```sh
systemctl --user disable --now inpmap.service
.venv/bin/inpmap devices | grep -i inpmap
```

**Expected:** `disable` reports the removed symlink; `grep` prints
nothing (no InpMap virtual or forwarding devices are left). Keep the unit
file for now; test 6 shows that profiles take precedence over it.

## 6. Profiles

```sh
.venv/bin/inpmap service-unit --profiles config > ~/.config/systemd/user/inpmap@.service
head -8 ~/.config/systemd/user/inpmap@.service
systemctl --user daemon-reload
```

**Expected:** the comments list `example  OK` and `local  OK`.

### 6a. Start a profile

```sh
systemctl --user start inpmap@local
systemctl --user status inpmap@local
```

**Expected:** `active (running)`, with the description
`InpMap input remapper, profile local`; your mappings work.

### 6b. Switch profiles

```sh
systemctl --user stop 'inpmap@*' && systemctl --user start inpmap@example
journalctl --user -u inpmap@example -n 10 --no-pager
```

**Expected:** `inpmap@local` stops and the keyboard is back to normal. The
`example` profile looks for a keyboard named "AT Translated Set 2
keyboard", which your PC does not have, so its log shows
`waiting for input 'kbd': ... no readable device named 'AT Translated Set 2 keyboard'`.
It keeps running and does not grab your keyboard.

Switch back:

```sh
systemctl --user stop 'inpmap@*' && systemctl --user start inpmap@local
```

**Expected:** the mappings work again.

### 6c. A profile stops the single-configuration service

```sh
systemctl --user stop 'inpmap@*'
systemctl --user start inpmap.service
systemctl --user start inpmap@local
systemctl --user status inpmap.service inpmap@local --no-pager | grep Active
```

**Expected:** `inpmap.service` is `inactive (dead)`, `inpmap@local` is
`active (running)`.

### 6d. Choose what starts at login

Keep **one** of the two variants enabled.

- Profiles, e.g. `local`:
  ```sh
  systemctl --user enable inpmap@local
  ```
- Or the single configuration:
  ```sh
  systemctl --user stop 'inpmap@*'
  systemctl --user enable --now inpmap.service
  ```

`systemctl --user list-unit-files 'inpmap*'` shows what is enabled.

## 7. Sticks, triggers and the D-pad as triggers (added 2026-10-14)

`inpmap axes` cannot read the pad while the service holds it, so stop the
service for this test:

```sh
systemctl --user stop inpmap 'inpmap@*'
cp config/local.inpmap /tmp/axes.inpmap
printf '%s\n' \
  'map pad.ABS_RZ above 0.5 as r2 { hold KEY_SPACE }' \
  'map pad.ABS_Z above 0.3 as l2_soft { tap KEY_1 }' \
  'map pad.ABS_Z above 0.9 as l2_hard { tap KEY_2 }' \
  'map pad.ABS_HAT0Y below -0.5 as dpad_up { tap KEY_KP8 }' \
  'map pad.ABS_HAT0Y above 0.5 as dpad_down { tap KEY_KP2 }' >> /tmp/axes.inpmap
.venv/bin/inpmap check /tmp/axes.inpmap
```

**Expected:** OK; the summary lists e.g. `r2: pad ABS_RZ above 0.5 -> ...`.

### 7a. Live values

```sh
.venv/bin/inpmap axes /tmp/axes.inpmap
```

Press R2 slowly, then L2, then the D-pad up and down, then move the left
stick. Ctrl+C stops.

**Expected:** rows for `ABS_X`, `ABS_Y`, `ABS_Z`, `ABS_RX`, `ABS_RY`,
`ABS_RZ`, `ABS_HAT0X`, `ABS_HAT0Y`. The values follow your movements:
the triggers 0.00 to 1.00, the sticks -1.00 to 1.00, the D-pad -1, 0 or
1. `r2: above 0.5` switches to `ON` past half way, `dpad_up: below -0.5
ON` while up is held. Note roughly where the triggers feel "half" and
"full" for your own thresholds later.

### 7b. Remapping

```sh
.venv/bin/inpmap run /tmp/axes.inpmap --timeout 60
```

Open a text editor and:

1. Press R2 fully and hold it, then release. **Expected:** a held space
   (the desktop's key repeat types several spaces); it stops when you
   release R2 past about 0.45.
2. Press L2 gently (about a third), release; then fully, release.
   **Expected:** gently types `1`; fully types `1` and then `2`.
3. D-pad up, D-pad down. **Expected:** the numpad 8 and 2 (with Num Lock
   on: `8` and `2`).
4. In a game or `evtest` on the **InpMap forward: Generic X-Box pad**
   device: **Expected:** no `ABS_RZ`, `ABS_Z` or `ABS_HAT0Y` events while
   you press R2, L2 or the D-pad (suppressed), but `ABS_X`/`ABS_Y` from the
   left stick still arrive.

Afterwards start your service again, e.g.
`systemctl --user start inpmap@local`.

## 8. Layers (added 2026-10-14)

```sh
cp config/local.inpmap /tmp/layers.inpmap
printf '%s\n' \
  'map kbd.KEY_TAB { if single { tap KEY_TAB } else { hold layer nav } }' \
  'map kbd.KEY_F7 { layer nav toggle }' \
  'layer nav {' \
  '    map kbd.KEY_W { hold KEY_UP }' \
  '    map kbd.KEY_A { hold KEY_LEFT }' \
  '    map kbd.KEY_S { hold KEY_DOWN }' \
  '    map kbd.KEY_D { hold KEY_RIGHT }' \
  '    map kbd.KEY_Q { disable }' \
  '}' >> /tmp/layers.inpmap
.venv/bin/inpmap check /tmp/layers.inpmap
```

**Expected:** OK; the summary ends with `layers: nav` and lists
`nav:kbd.KEY_W` … `nav:kbd.KEY_Q`. (Tab is used because your Caps Lock is
already mapped; modifier keys such as Alt cannot be triggers.)

Stop the service if it runs (`systemctl --user stop 'inpmap@*' inpmap`), then:

```sh
.venv/bin/inpmap run /tmp/layers.inpmap --timeout 60
```

In a text editor:

1. Type `wasdq`. **Expected:** `wasdq` (layer off).
2. Hold Tab and press W, A, S, D, Q. **Expected:** the cursor moves
   up, left, down, right; Q does nothing.
3. Release Tab, type `wasd`. **Expected:** `wasd` again.
4. Tap Tab alone. **Expected:** a normal Tab.
5. Press F7, type `wasd`. **Expected:** arrow movement (layer on). Press
   F7 again, type `wasd`. **Expected:** letters again.
6. Hold Tab, press and **hold** W (cursor keeps moving up), release Tab
   first, then W. **Expected:** the movement stops when W is
   released; no stuck arrow key.

Afterwards start your service again, e.g. `systemctl --user start inpmap@local`.

## Checklist for your reply

```text
M1 migration .....................
M2 new service unit + login ......
M3 example ........................
M4 detect .........................
M5 profile without mappings .......
M6 syntax files ...................
0  preparation ..................
1  emergency stop (foreground) ...
2  inpmap codes ..................
3  numpad output .................
4a input-config new file / i .....
4b input-config existing file ....
4c input-config quit .............
5a service install/start .........
5b mappings under the service ....
5c emergency stop under service ..
5d gamepad off at start ..........
5e invalid config, no loop .......
5f devices held by service .......
5g login .........................
5h stop and clean up .............
6a profile start .................
6b profile switch ................
6c profile stops single service ..
6d chosen for login: .............
7a axes: live values .............
7b axes: remapping ...............
8  layers .........................
```

# Manual tests on real hardware

The unit tests (`python -m pytest`) need no devices, and the hardware tests
(`python -m pytest -m hardware`) use synthetic devices only. What they
cannot show is how InpMap behaves with real keyboards and gamepads, the
desktop and games. Run these checks before a release and after changes to
devices, grabbing, the runtime or the service.

Use a separate test profile so your own configuration stays untouched, and
a time limit for every foreground run. The emergency stop (hold
**Backspace + Escape + Enter** together) must work at any time.

## Preparation

```sh
inpmap --version
inpmap input-config mtest        # pick your keyboard (i, then a key) and, if you have one, a gamepad (as 'pad')
```

Open `~/.config/inpmap/mtest.inpmap` and add the acceptance test mapping,
using the input name of your keyboard:

```text
map kbd.KEY_X {
    hold KEY_Y
    hold BTN_FACE_DOWN
}
```

Then `inpmap check mtest`: **expected** OK.

## 1. Virtual devices

```sh
inpmap test-outputs mtest --no-emit --delay 20
```

Meanwhile, in another terminal: `evtest`. **Expected:** "InpMap keyboard"
and "InpMap gamepad" (or the names from the profile) are listed; after 20
seconds both disappear again.

## 2. Acceptance test: remapping, suppression, release

```sh
inpmap run mtest --timeout 60
```

In a text editor, press X briefly, then type other letters; meanwhile
`evtest` on the virtual gamepad. **Expected:** X types `y` (the key at the Y
position of your layout), never `x`; the gamepad reports `BTN_FACE_DOWN` 1 and 0;
other keys type normally; holding X gives the desktop's key repeat; nothing
stays pressed after release.

## 2a. Routing: the outputs replace the physical devices

During the `run` of section 2: `inpmap devices` in another terminal.
**Expected:** no "InpMap forward: …" entry for the keyboard (unless it has
a mouse part); typing works through "InpMap keyboard"; Num Lock and Caps
Lock LEDs on the physical keyboard follow the desktop.

With a gamepad as input `pad`: in KDE's game controller settings and in
Steam's controller test there is **one** controller, "InpMap gamepad", and
its sticks, triggers, D-pad and buttons all work. A gamepad with extra
buttons that send keys (e.g. the Razer Raiju's keyboard part, mapped to
`BTN_GRIPL` …) shows them as L4/R4/L5/R5 on the same controller.

Remove the `output keyboard` line and run again. **Expected:** InpMap
stops at once with "… is not taken over … there is no keyboard output";
the keyboard keeps working. Restore the line afterwards.

## 2b. Emulated DualSense Edge

Needs the udev rules of a profile with `emulate` (or run as described in
`tools/dualsense_edge_uhid.py`). Profile: the pad as input `pad` (its extra
buttons mapped to `BTN_GRIPL`, `BTN_GRIPR`, `BTN_GRIPL2`, `BTN_GRIPR2`),
`output gamepad { type = gamepad; emulate = "dualsense-edge" }`.

1. `inpmap run PROFILE`. **Expected:** `journalctl -k` shows
   "playstation …: Registered DualSense controller"; `inpmap devices` lists
   "InpMap gamepad" and its Motion Sensors, Touchpad and Headset Jack as
   InpMap's own; `getfacl` on the new `/dev/hidraw*` node shows your user.
2. `evtest` on "InpMap gamepad": sticks, triggers, D-pad (as `ABS_HAT0X/Y`)
   and buttons work; `BTN_GRIPL`, `BTN_GRIPR`, `BTN_GRIPL2`, `BTN_GRIPR2`
   arrive as `BTN_TRIGGER_HAPPY1` … `4` (the Edge's left Fn, right Fn,
   left paddle, right paddle; Linux 7.2 or later). The pad's X button is
   code 0x134 there (evtest: `BTN_WEST`; the PlayStation driver numbers
   by position, §3.3).
   Steam's controller settings show `BTN_GRIPL`/`BTN_GRIPR` in the upper
   row and `BTN_GRIPL2`/`BTN_GRIPR2` in the lower row, each on its side;
   X shows as Square, Y as Triangle.
3. A Windows game under Proton with Steam Input disabled (e.g. WoW with the
   InputLogger addon): the controller is a DualSense with ID 054C:0DF2;
   `BTN_GRIPR2`, `BTN_GRIPL2`, `BTN_GRIPR`, `BTN_GRIPL` arrive as
   `PADPADDLE1` … `PADPADDLE4` (SDL paddles 1 to 4); X and Y as `PAD3` and
   `PAD4`; View (`BTN_SELECT`) as `PADBACK` once the WoW configuration of
   [wow-dualsense.md](wow-dualsense.md) is in place (otherwise `PADSOCIAL`).
4. Stop InpMap. **Expected:** the four devices disappear, nothing stays
   pressed in the game.
5. Touchpad: add the pad's touchpad as an input (`inpmap input-config
   PROFILE`, kind "touchpad"), run again. **Expected:** the desktop
   pointer no longer follows the physical touchpad directly; `evtest` on
   "InpMap gamepad Touchpad" shows `ABS_MT_POSITION_X/Y` (0–1919, 0–1079)
   following the finger over the whole surface (corners reach the
   extremes), a second finger in slot 1, a third ignored, `BTN_LEFT` on
   the click; lifting ends every contact. In Steam (Steam Input on), the
   controller test shows the touchpad; "Left/Right Trackpad" react to
   the halves, a radial menu on one half opens and selects. Stop InpMap
   while touching: the contact ends.

## 3. Emergency stop

During a `run`, hold Backspace + Escape + Enter. **Expected:** InpMap stops
at once with `stopped (emergency stop: Backspace+Escape+Enter)`, exit status
0, and the keyboard works normally.

## 4. Device lost and back

During a `run`, unplug the keyboard's receiver (or the gamepad) while a
mapped key is held, then plug it in again. **Expected:** the output is
released at once; InpMap keeps running and grabs the device again within
about a second; the mapping works again. Keyboard LEDs (Caps Lock) follow
the desktop's state.

## 5. Tools

- `inpmap input-config example`, then `inpmap run example --timeout 60`:
  the example does what its comments say (F1 to F8, Caps Lock with W A S D,
  Insert).
- `inpmap detect mtest`: keys, keys with Ctrl, gamepad buttons, R2 and the
  D-pad are printed as triggers; modifiers alone print nothing.
- `inpmap axes mtest`: stick, trigger and D-pad values follow the movements.

## 6. Service

```sh
inpmap service-unit > ~/.config/systemd/user/inpmap@.service
systemctl --user daemon-reload
systemctl --user start inpmap@mtest
systemctl --user status inpmap@mtest
```

**Expected:** `active (running)` and the mapping works. Then:

- `journalctl --user -u inpmap@mtest` shows the start without errors.
- Unplug the gamepad, `systemctl --user restart inpmap@mtest`: the log says
  once that it waits for the device; after plugging it in it is grabbed.
- Add `map KEY_F7 { tap KEY_QQ }` to the profile and restart: the service
  is `failed` with the line number of the error and is **not** restarted
  in a loop. Remove the line again.
- With the service running, `inpmap run mtest --timeout 5` reports
  "already grabbed by another program" (exit status 3).
- `systemctl --user enable inpmap@mtest`, log out and in: the service runs
  without any action.
- Emergency stop under the service: it is `inactive (dead)` afterwards.

## Cleaning up

```sh
systemctl --user disable --now inpmap@mtest
rm ~/.config/inpmap/mtest.inpmap
inpmap devices | grep -i inpmap         # nothing: no InpMap devices are left
```

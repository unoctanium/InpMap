# Installing InpMap

InpMap currently runs on **Linux**. You need:

- Python 3.11 or newer (so far tested with 3.14 only);
- the Python package `evdev` (best from your distribution, see below);
- for the recommended permission setup: systemd-logind, which almost every
  desktop distribution uses.

InpMap installs nothing system-wide except an optional udev rules file for
device permissions (step 3). It runs as your normal user, never as root.

## 1. System packages

| Distribution | Command | Tested |
|---|---|---|
| Arch, CachyOS, Manjaro | `sudo pacman -S --needed python python-evdev git evtest` | yes (CachyOS) |
| Debian, Ubuntu | `sudo apt install python3 python3-venv python3-evdev git evtest` | not yet |
| Fedora | `sudo dnf install python3 python3-evdev git evtest` | not yet |

`evtest` is optional; it shows the events of any input device and is
useful for finding key codes and checking InpMap's virtual devices.

Without a distribution package for evdev, pip builds it itself. That needs
a C compiler, Python headers and kernel headers (Debian:
`build-essential python3-dev linux-libc-dev`); then create the virtual
environment in step 2 **without** `--system-site-packages`.

## 2. InpMap in a virtual environment

```sh
git clone https://github.com/unoctanium/InpMap.git
cd InpMap
python3 -m venv --system-site-packages .venv   # lets the venv use the distribution's evdev
.venv/bin/pip install -e .
```

pip also downloads InpMap's only other dependency, the pure-Python parser
library `lark`. The command is then `.venv/bin/inpmap` (or just `inpmap` after
`source .venv/bin/activate`). Check it with `.venv/bin/inpmap --version`.

## 3. Device permissions

InpMap needs:

- **write access to `/dev/uinput`**, to create its virtual devices;
- **read/write access to the input devices you configure**
  (`/dev/input/eventN`), to read and grab them and to set their LEDs.

Check the current state:

```sh
getfacl /dev/uinput            # look for user:<you>:rw-
.venv/bin/inpmap devices       # reports device nodes you cannot read
```

If both are fine (some systems already allow it, e.g. through the
`steam-devices` package), skip this step.

Do not run InpMap as root and do not make device nodes world-writable.

### Option A (recommended): rules for exactly your devices

This needs a configuration file first (see [usage.md](usage.md#2-your-first-configuration));
plug in the configured devices, then:

```sh
.venv/bin/inpmap udev-rules config/local.inpmap > 70-inpmap.rules
cat 70-inpmap.rules            # review: one rule for /dev/uinput, one per input device
sudo install -m 644 70-inpmap.rules /etc/udev/rules.d/70-inpmap.rules
sudo udevadm control --reload
sudo udevadm trigger --subsystem-match=input --subsystem-match=misc
```

The rules give access to the user of the active local login session only,
and only to `/dev/uinput` and the configured devices (matched by name plus
vendor and product ID, so other keyboards stay inaccessible). Run the
commands again after adding input devices to your configuration.

### Option B: the `input` group

```sh
sudo usermod -aG input "$USER"     # then log out and in again
```

Simpler, but every program you run can then read every input device,
including everything you type. Access to `/dev/uinput` is still needed
separately (the first rule of Option A, or a distribution package such as
Arch's `steam-devices`).

## 4. Configure and test

Continue with [usage.md](usage.md#2-your-first-configuration): find your
device, write a configuration, check it, try it.

## 5. Optional: syntax highlighting

- **Kate / KWrite**: copy `editors/inpmap.xml` to
  `~/.local/share/org.kde.syntax-highlighting/syntax/` and restart the
  editor; `.inpmap` files are then highlighted (mode "InpMap").
- **nano**: add `include "/path/to/InpMap/editors/inpmap.nanorc"` to
  `~/.config/nano/nanorc` (or `~/.nanorc`). Not tested yet.

## 6. Running in the background (user service)

Once a configuration works with `inpmap run`, let systemd start InpMap
automatically whenever you log in. It runs as a **user service**
(`systemctl --user`): as your user, without root, with the device access of
your login session (step 3).

**Install:**

```sh
mkdir -p ~/.config/systemd/user
.venv/bin/inpmap service-unit config/local.inpmap > ~/.config/systemd/user/inpmap.service
cat ~/.config/systemd/user/inpmap.service      # review
systemctl --user daemon-reload
systemctl --user enable --now inpmap.service
```

`inpmap service-unit` writes the absolute paths of this installation and of
your configuration file into the unit. Run it again if you move either.

**Everyday commands:**

| Task | Command |
|---|---|
| Is it running? | `systemctl --user status inpmap` |
| Show its log | `journalctl --user -u inpmap` (add `-f` to follow) |
| Apply an edited configuration | `.venv/bin/inpmap check config/local.inpmap`, then `systemctl --user restart inpmap` |
| Stop until the next login | `systemctl --user stop inpmap` |
| Do not start at login any more | `systemctl --user disable inpmap` |

**How it behaves:**

- It starts when you log in and stops when your last session ends.
  It does not run at the login screen.
- An input device that is missing at startup (e.g. a gamepad that is still
  switched off) does not stop the service: InpMap waits for it and grabs it
  when it appears. The log says why it is waiting.
- If the configuration is invalid, the service stops with an error and is
  not restarted; `systemctl --user status inpmap` and the log show the
  problem with its line number. Other failures (e.g. device permissions
  not ready right after login) are retried every 3 seconds, at most 5 times
  per minute.
- If a configuration makes your keyboard unusable, hold **Backspace,
  Escape and Enter** together: InpMap stops at once (emergency stop) and is
  not restarted until you start it again or log in again.
- While the service runs, it holds your devices: stop it before running
  `inpmap run` by hand, otherwise that reports "already grabbed by another
  program".

A system-wide service (running without anyone logged in) is not supported.

### Several configurations (profiles)

To switch between configurations, for example one per game, put them into
one directory and install the profile unit instead of the single one:

```sh
ls config/                              # dcs.inpmap  msfs.inpmap  desktop.inpmap
.venv/bin/inpmap service-unit --profiles config > ~/.config/systemd/user/inpmap@.service
systemctl --user daemon-reload
systemctl --user enable --now inpmap@desktop     # started at every login
```

Profile `NAME` runs `config/NAME.inpmap`; the comments at the top of the
unit list the profiles found. Profile names may contain letters, digits,
`-`, `_` and `.`. Only one profile can hold the devices at a time, so
switch like this:

```sh
systemctl --user stop 'inpmap@*' && systemctl --user start inpmap@dcs
```

A profile file added later needs no new unit; just start it. Starting a
profile also stops the single-configuration service (`inpmap.service`) if
it runs. Logs: `journalctl --user -u inpmap@dcs`. To see which profiles
start at login: `systemctl --user list-unit-files 'inpmap@*'`.

Remove: `systemctl --user stop 'inpmap@*'`, then
`systemctl --user disable inpmap@NAME` for each enabled profile, then
`rm ~/.config/systemd/user/inpmap@.service` and
`systemctl --user daemon-reload`.

**Remove:**

```sh
systemctl --user disable --now inpmap.service
rm ~/.config/systemd/user/inpmap.service
systemctl --user daemon-reload
```

## Uninstall

1. If you installed the user service: remove it as described in §6.
2. If you installed the udev rules:
   ```sh
   sudo rm /etc/udev/rules.d/70-inpmap.rules
   sudo udevadm control --reload
   sudo udevadm trigger --subsystem-match=input --subsystem-match=misc
   ```
3. If you joined the `input` group only for InpMap:
   `sudo gpasswd -d "$USER" input` (takes effect at the next login).
4. Remove the editor files you copied, if any.
5. Delete the InpMap directory (including `.venv`).

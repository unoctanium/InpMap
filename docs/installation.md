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
git clone <repository-url> InpMap      # or copy the directory
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

## Running in the background

InpMap currently runs in the foreground (`inpmap run`). Running it as a
systemd service, started automatically, is being implemented next; this
section will describe its installation.

## Uninstall

1. If you installed the udev rules:
   ```sh
   sudo rm /etc/udev/rules.d/70-inpmap.rules
   sudo udevadm control --reload
   sudo udevadm trigger --subsystem-match=input --subsystem-match=misc
   ```
2. If you joined the `input` group only for InpMap:
   `sudo gpasswd -d "$USER" input` (takes effect at the next login).
3. Remove the editor files you copied, if any.
4. Delete the InpMap directory (including `.venv`).

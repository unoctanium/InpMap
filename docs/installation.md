# Installing InpMap

InpMap currently runs on **Linux**. You need:

- Python 3.11 or newer (so far tested with 3.14 only);
- the Python package `evdev` (best from your distribution, see below);
- for the recommended permission setup: systemd-logind, which almost every
  desktop distribution uses.

InpMap installs nothing system-wide except an optional udev rules file for
device permissions (step 3). It runs as your normal user, never as root.
Your configurations live in `~/.config/inpmap/`.

## 1. System packages

On **Arch Linux, CachyOS or Manjaro**, skip this step and use the package
(step 2a): it installs everything it needs.

| Distribution | Command | Tested |
|---|---|---|
| Arch, CachyOS, Manjaro | `sudo pacman -S --needed python python-evdev python-pipx evtest` | yes (CachyOS) |
| Debian, Ubuntu | `sudo apt install python3 python3-evdev pipx evtest` | not yet |
| Fedora | `sudo dnf install python3 python3-evdev pipx evtest` | not yet |

For installing from the source code (step 2c) add `git`, and on Debian or
Ubuntu `python3-venv`.

`evtest` is optional; it shows the events of any input device and is
useful for checking InpMap's virtual devices.

Without a distribution package for evdev, pip builds it itself. That needs
a C compiler, Python headers and kernel headers (Debian:
`build-essential python3-dev linux-libc-dev`); then create the virtual
environment in step 2 **without** `--system-site-packages`.

## 2. InpMap

### 2a. Arch Linux, CachyOS, Manjaro: as a package (recommended)

InpMap will be in the AUR (`paru -S inpmap`) as soon as new AUR accounts
can be registered again. Until then, build the same package from this
repository:

```sh
sudo pacman -S --needed base-devel git
git clone https://github.com/unoctanium/InpMap.git ~/InpMap
cd ~/InpMap/packaging/aur
makepkg -sri
```

`makepkg` downloads the released InpMap from PyPI, installs the build tools and
dependencies with pacman (`-s`), builds and tests the package, installs it
(`-i`) and removes the build-only tools again (`-r`). The package contains:

- the command `/usr/bin/inpmap`;
- the user service unit (step 6 is then just `systemctl --user enable`);
- access to `/dev/uinput` for the logged-in user (step 3 then only needs
  the rules for your own devices; the message after installing shows the
  commands);
- the Kate and nano syntax files (step 5 is not needed).

To update: `cd ~/InpMap && git pull && cd packaging/aur && makepkg -sri`.
To remove: `sudo pacman -R inpmap` (your profiles in `~/.config/inpmap/`
stay).

### 2b. From PyPI (other distributions)

```sh
pipx install --system-site-packages inpmap
inpmap --version
```

[pipx](https://pipx.pypa.io/) installs InpMap into its own environment and
puts the command `inpmap` into `~/.local/bin` (run `pipx ensurepath` once
if it is not found). `--system-site-packages` lets it use the evdev package
of your distribution instead of compiling it. Update with
`pipx upgrade inpmap`, remove with `pipx uninstall inpmap`.

### 2c. From the source code (for development)

```sh
git clone https://github.com/unoctanium/InpMap.git ~/InpMap
cd ~/InpMap
python3 -m venv --system-site-packages .venv   # lets the venv use the distribution's evdev
.venv/bin/pip install -e .
mkdir -p ~/.local/bin
ln -s ~/InpMap/.venv/bin/inpmap ~/.local/bin/inpmap
inpmap --version
```

pip also downloads InpMap's only other dependency, the pure-Python parser
library `lark`. The link in `~/.local/bin` makes the command available as
plain `inpmap` (that folder is on the `PATH` of most distributions; if
`inpmap --version` is not found, log out and in again or add it to the
`PATH`). All documentation writes the command as `inpmap`.

To update later: `cd ~/InpMap && git pull`.

## 3. Device permissions

InpMap needs:

- **write access to `/dev/uinput`**, to create its virtual devices;
- **read/write access to the input devices you configure**
  (`/dev/input/eventN`), to read and grab them and to set their LEDs;
- only for an emulated DualSense Edge
  ([configuration.md §3.5](configuration.md#35-emulating-a-dualsense-edge-emulate)):
  **write access to `/dev/uhid`**, and for the games read/write access to
  the controller's `/dev/hidraw*` node.

Check the current state:

```sh
getfacl /dev/uinput            # look for user:<you>:rw-
inpmap devices                 # reports device nodes you cannot read
```

If both are fine (some systems already allow it, e.g. through the
`steam-devices` package), skip this step.

Do not run InpMap as root and do not make device nodes world-writable.

### Option A (recommended): rules for exactly your devices

This needs a configuration with your devices first
([usage.md](usage.md#2-first-contact)); plug them in, then:

```sh
inpmap udev-rules > 70-inpmap.rules     # devices of the profile 'default'; or: inpmap udev-rules NAME
cat 70-inpmap.rules                     # review: one rule for /dev/uinput, one per input device
sudo install -m 644 70-inpmap.rules /etc/udev/rules.d/70-inpmap.rules
sudo udevadm control --reload
sudo udevadm trigger --subsystem-match=input --subsystem-match=misc
```

The rules give access to the user of the active local login session only,
and only to `/dev/uinput` and the configured devices (matched by name plus
vendor and product ID, so other keyboards stay inaccessible). Run the
commands again after adding input devices to your configuration.

If the profile has an output with `emulate = "dualsense-edge"`, the rules
also grant `/dev/uhid` and the raw HID node of InpMap's emulated
controller (only devices created through `/dev/uhid` with the DualSense
Edge's IDs match). `/dev/uhid` lets a program create any HID device, a
little more than `/dev/uinput` allows; profiles without `emulate` do not
get this rule. Arch's `steam-devices` package already grants the raw HID
node of a DualSense Edge, but not `/dev/uhid`.

### Option B: the `input` group

```sh
sudo usermod -aG input "$USER"     # then log out and in again
```

Simpler, but every program you run can then read every input device,
including everything you type. Access to `/dev/uinput` is still needed
separately (the first rule of Option A, or a distribution package such as
Arch's `steam-devices`).

## 4. First contact and your own configuration

Continue with [usage.md](usage.md#2-first-contact): try the example, then
create your own configuration.

## 5. Optional: syntax highlighting

- **Kate / KWrite**:
  ```sh
  mkdir -p ~/.local/share/org.kde.syntax-highlighting/syntax
  inpmap syntax-file kate > ~/.local/share/org.kde.syntax-highlighting/syntax/inpmap.xml
  ```
  Restart the editor; `.inpmap` files are then highlighted (mode "InpMap").
- **nano**:
  ```sh
  mkdir -p ~/.local/share/inpmap ~/.config/nano
  inpmap syntax-file nano > ~/.local/share/inpmap/inpmap.nanorc
  echo "include \"$HOME/.local/share/inpmap/inpmap.nanorc\"" >> ~/.config/nano/nanorc
  ```
  Not tested yet.

Run the commands again after updating InpMap.

## 6. Running in the background (user service)

With the package (step 2a) the unit is already installed: skip "Install"
and only run the `enable` command below. (A unit file of your own in
`~/.config/systemd/user/inpmap@.service` would take precedence over the
packaged one; remove it if you created one earlier.)

Once a configuration works with `inpmap run`, let systemd start it
automatically whenever you log in. InpMap runs as a **user service**
(`systemctl --user`): as your user, without root, with the device access
of your login session (step 3). The service runs one **profile** at a
time: `inpmap@default` runs `~/.config/inpmap/default.inpmap`,
`inpmap@dcs` runs `~/.config/inpmap/dcs.inpmap`.

**Install** (once):

```sh
mkdir -p ~/.config/systemd/user
inpmap service-unit > ~/.config/systemd/user/inpmap@.service
cat ~/.config/systemd/user/inpmap@.service      # review
systemctl --user daemon-reload
systemctl --user enable --now inpmap@default     # started now and at every login
```

`inpmap service-unit` writes the path of this installation into the unit;
run it again if you move InpMap. Profiles added later need no new unit.

**Everyday commands:**

| Task | Command |
|---|---|
| Is it running? | `systemctl --user status inpmap@default` |
| Show its log | `journalctl --user -u inpmap@default` (add `-f` to follow) |
| Apply an edited configuration | `inpmap check`, then `systemctl --user restart inpmap@default` |
| Switch to another profile | `systemctl --user stop 'inpmap@*' && systemctl --user start inpmap@dcs` |
| Start another profile at login instead | `systemctl --user disable inpmap@default && systemctl --user enable inpmap@dcs` |
| Which profiles start at login? | `systemctl --user list-unit-files 'inpmap@*'` |
| Stop until the next login | `systemctl --user stop 'inpmap@*'` |

**How it behaves:**

- It starts when you log in and stops when your last session ends.
  It does not run at the login screen.
- A profile without mappings starts but does nothing (no device is grabbed),
  so `inpmap@default` can be enabled before you have written mappings.
- An input device that is missing at startup (e.g. a gamepad that is still
  switched off) does not stop the service: InpMap waits for it and grabs it
  when it appears. The log says why it is waiting.
- If the configuration is invalid, the service stops with an error and is
  not restarted; `systemctl --user status inpmap@default` and the log show
  the problem with its line number. Other failures (e.g. device permissions
  not ready right after login) are retried every 3 seconds, at most 5 times
  per minute.
- If a configuration makes your keyboard unusable, hold **Backspace,
  Escape and Enter** together: InpMap stops at once (emergency stop) and is
  not restarted until you start it again or log in again.
- Only one profile can hold the devices at a time. While the service runs,
  stop it before running `inpmap run` by hand, otherwise that reports
  "already grabbed by another program".

A system-wide service (running without anyone logged in) is not supported.

**Remove:**

```sh
systemctl --user stop 'inpmap@*'
systemctl --user disable inpmap@default        # each enabled profile
rm ~/.config/systemd/user/inpmap@.service
systemctl --user daemon-reload
```

## Uninstall

With the package (step 2a): `systemctl --user disable --now 'inpmap@NAME'`
for each enabled profile, then `sudo pacman -R inpmap`; also step 2 below
if you created device rules, and step 6 for your profiles. Otherwise:

1. If you installed the user service: remove it as described in §6.
2. If you installed the udev rules:
   ```sh
   sudo rm /etc/udev/rules.d/70-inpmap.rules
   sudo udevadm control --reload
   sudo udevadm trigger --subsystem-match=input --subsystem-match=misc
   ```
3. If you joined the `input` group only for InpMap:
   `sudo gpasswd -d "$USER" input` (takes effect at the next login).
4. Remove the syntax files, if you installed them (§5), and the `include`
   line from your nano configuration.
5. Remove the program: `pipx uninstall inpmap`, or, if you installed from
   the source code, `rm ~/.local/bin/inpmap` and delete `~/InpMap`
   (including `.venv`).
6. Your configurations are in `~/.config/inpmap/`; delete that folder if
   you do not need them any more.

# AUR package `inpmap`

The files of the AUR package: `PKGBUILD`, `.SRCINFO`, the user unit
`inpmap@.service` (which runs `/usr/bin/inpmap`), the udev rule
`70-inpmap-uinput.rules` and the messages `inpmap.install`. The package
builds from the release on PyPI, runs the unit tests, and installs:

- the program (`/usr/bin/inpmap`);
- the user unit in `/usr/lib/systemd/user/`, so `systemctl --user enable
  --now inpmap@default` works right away;
- a udev rule giving the logged-in user access to `/dev/uinput` (applied at
  once: pacman's systemd hook reloads udev rules);
- the Kate and nano syntax files, the license and the documentation.

Access to the physical keyboards and gamepads is deliberately not granted
by the package (a general rule would let every program read every
keyboard); the message after installing shows how to create rules for
exactly the configured devices with `inpmap udev-rules`.

Tests keep the packaged unit and udev rule in step with what
`inpmap service-unit` and `inpmap udev-rules` generate.

## Test build

```sh
sudo pacman -S --needed base-devel python-build python-installer python-pytest python-lark-parser
cp -r packaging/aur /tmp/inpmap-aur && cd /tmp/inpmap-aur
makepkg -f                  # downloads, builds, tests, packages
namcap PKGBUILD *.pkg.tar.zst    # optional lint (pacman -S namcap)
```

`makepkg -f` only builds; users get the package installed by `paru -S
inpmap`. To test the installation itself, use `makepkg -fi` (build and
install) after removing other installations: `pipx uninstall inpmap`, and
`rm ~/.config/systemd/user/inpmap@.service` (a unit there takes precedence
over the packaged one). Remove the package with `sudo pacman -R inpmap`.

## Publishing (first time)

Needs an AUR account with an SSH key.

```sh
git clone ssh://aur@aur.archlinux.org/inpmap.git aur-inpmap
cp packaging/aur/{PKGBUILD,.SRCINFO,inpmap@.service,70-inpmap-uinput.rules,inpmap.install} aur-inpmap/
cd aur-inpmap
git add PKGBUILD .SRCINFO inpmap@.service 70-inpmap-uinput.rules inpmap.install
git commit -m "inpmap 0.2.0"
git push
```

## New version

After a new release is on PyPI: set `pkgver` (and `pkgrel=1`), update the
checksums (`updpkgsums` from `pacman-contrib`, or `makepkg -g`), regenerate
`.SRCINFO` with `makepkg --printsrcinfo > .SRCINFO`, test build, then copy
the five files into the AUR repository, commit and push. A change to the
packaging alone increases `pkgrel`.

Notes: nano only uses `/usr/share/nano/inpmap.nanorc` if
`include /usr/share/nano/*.nanorc` is enabled in `/etc/nanorc` (on Arch
it is commented out by default).

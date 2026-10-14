# AUR package `inpmap`

The files of the AUR package: `PKGBUILD`, `.SRCINFO` and the user unit
`inpmap@.service` (which runs `/usr/bin/inpmap`). The package builds from
the release on PyPI, runs the unit tests, and installs the program, the
user unit (`/usr/lib/systemd/user/`), the Kate and nano syntax files, the
license and the documentation.

`tests/test_linux_service.py` checks that this unit stays in step with the
one `inpmap service-unit` generates.

## Test build

```sh
sudo pacman -S --needed base-devel python-build python-installer python-pytest python-lark-parser
cp -r packaging/aur /tmp/inpmap-aur && cd /tmp/inpmap-aur
makepkg -f                  # downloads, builds, tests, packages
namcap PKGBUILD *.pkg.tar.zst    # optional lint (pacman -S namcap)
```

Install it for a real test with `sudo pacman -U inpmap-*.pkg.tar.zst`
(first `pipx uninstall inpmap`, so there is only one `inpmap` command), and
remove it again with `sudo pacman -R inpmap`.

## Publishing (first time)

Needs an AUR account with an SSH key.

```sh
git clone ssh://aur@aur.archlinux.org/inpmap.git aur-inpmap
cp packaging/aur/{PKGBUILD,.SRCINFO,inpmap@.service} aur-inpmap/
cd aur-inpmap
git add PKGBUILD .SRCINFO inpmap@.service
git commit -m "inpmap 0.2.0"
git push
```

## New version

After a new release is on PyPI: set `pkgver` (and `pkgrel=1`), update the
checksums (`updpkgsums` from `pacman-contrib`, or `makepkg -g`), regenerate
`.SRCINFO` with `makepkg --printsrcinfo > .SRCINFO`, test build, then copy
the three files into the AUR repository, commit and push. A change to the
packaging alone increases `pkgrel`.

Notes: nano only uses `/usr/share/nano/inpmap.nanorc` if
`include /usr/share/nano/*.nanorc` is enabled in `/etc/nanorc` (on Arch
it is commented out by default). The package installs no udev rules:
device access stays the user's decision (see docs/installation.md §3).

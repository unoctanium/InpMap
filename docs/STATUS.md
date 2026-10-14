# Project status

The handoff document for development sessions (see `CLAUDE.md` §16): where
the project stands, what was decided and why, and what comes next. A new
session continues from this file plus the repository. Goals and milestones:
[roadmap.md](roadmap.md).

Last updated: 2026-10-14

## Current position

- V1, V1.1, the configuration language and the systemd user service are
  done and verified on real hardware (see "Verification").
- **Publishing (roadmap)** is in progress:
  - a. ✅ Independent of the source tree: profiles in `~/.config/inpmap/`,
    example and syntax files in the package, `inpmap@NAME` unit, `detect`.
  - b. ✅ Release 0.2.0 on PyPI (published 2026-10-14): CI is green on Python 3.11–3.14; version,
    changelog, metadata, `MANIFEST.in` and the release workflow are ready;
    the PyPI "pending publisher" (project `inpmap`, workflow `release.yml`,
    environment `pypi`) and the GitHub environment `pypi` are set up.
    Before tagging, the repository was cleaned for publication (see the
    decisions of 2026-10-14 below).
  - c. 🔧 **AUR package prepared; upload waits for AUR registration**
    (2026-10-14): `packaging/aur/` — `PKGBUILD` (from the PyPI sdist
    0.2.0, sha256 checked; depends python, python-evdev,
    python-lark-parser; check() runs the unit tests; installs the program,
    `/usr/lib/systemd/user/inpmap@.service` with `/usr/bin/inpmap`, Kate
    syntax file in `/usr/share/org.kde.syntax-highlighting/syntax/` —
    lookup via XDG_DATA_DIRS verified with ksyntaxhighlighter6 —, nano
    file in `/usr/share/nano/`, license, docs), `.SRCINFO` (generated),
    README (test build, first upload, updates). Verified: `makepkg
    --printsrcinfo`, `makepkg --verifysource` (download + both checksums
    pass), the unit with `systemd-analyze verify`, a drift test against
    `inpmap service-unit`. ✅ Test build by the maintainer: `makepkg -f` →
    "Finished making: inpmap 0.2.0-1" (2026-10-14). **Decision (2026-10-14,
    after comparing user service vs. system service as root or as a
    dedicated `inpmap` user):** keep the user service; the package installs
    `/usr/lib/udev/rules.d/70-inpmap-uinput.rules` (uaccess for
    /dev/uinput, like steam-devices; pacman's systemd hook reloads udev at
    once) and shows a post-install message with the commands for the
    per-device rules (`inpmap udev-rules`); no generic rule for all
    keyboards (would let every program read every keyboard). pkgrel=2,
    `inpmap.install` (post_install, post_remove), drift test against
    `UINPUT_RULE`; `udevadm verify` and `makepkg --verifysource` pass.
    ✅ Installation test by the maintainer (2026-10-14, "all as expected"):
    `makepkg -fi` (0.2.0-2) after removing the pipx version and the own
    unit; `/usr/bin/inpmap` 0.2.0; packaged unit used by
    `inpmap@default` (active); Kate highlights via the system file;
    `pacman -R` with the removal message; reinstalled — the development
    machine now runs the locally built AUR package. ⏳ **Open:** **upload to the AUR once account
    registration reopens** (it was closed on 2026-10-14: HTTP 503, "paused
    while we deal with a wave of automated account creation"; watch
    aur-general / Arch news), following packaging/aur/README.md; then
    document `paru -S inpmap` in installation.md and the README.
  - d. Demo (GIF or asciinema), a few external testers, then announcements
    (r/linux_gaming, r/hotas, r/hoggit, r/archlinux, Arch forum, Show HN),
    respecting each community's self-promotion rules.

## Next steps

1. ✅ **InpMap 0.2.0 released** (2026-10-14): tag `v0.2.0` pushed with the
   maintainer's OK; release workflow succeeded; pypi.org/project/inpmap
   shows 0.2.0 (wheel + sdist, author, MIT, Python ≥ 3.11, project links). The release workflow tests, checks tag = version,
   builds and uploads to PyPI (a version can never be uploaded twice).
2. ✅ Verified on the development machine (2026-10-14): `python-pipx`
   installed, `pipx install --system-site-packages inpmap` → `inpmap
   0.2.0`; unit regenerated (ExecStart points to the pipx Python),
   `inpmap@default` active; `inpmap run example` works. On this machine the
   plain `inpmap` command was the PyPI release; since the AUR test it is
   the locally built package (`/usr/bin/inpmap`). Development and tests
   always use the source tree's `.venv/bin/inpmap` / `.venv/bin/python`.
3. Step c: maintainer's test build of the AUR package; the upload waits
   until AUR registration reopens. Meanwhile the maintainer decides what
   comes next (e.g. step d).

## Decisions (and why)

| Decision | Reason |
|---|---|
| Configuration language `.inpmap` (lark LALR parser) replaced JSON | readable by hand; errors with `FILE:LINE:COLUMN`; one format only |
| `docs/configuration.md` is the language specification; changes there first, with the maintainer's approval | the reference and the implementation must not drift |
| Linux code names (`KEY_X`, `BTN_SOUTH`) as vocabulary; table generated into `_linux_codes.py` | core free of evdev (Windows later); test cross-checks with evdev |
| Passthrough through one forwarding uinput device per grabbed input, copying vendor/product, without `EV_REP` and `EV_FF` | unmapped input keeps working; per-device desktop settings apply; no double key repeat; no 30 s rumble stalls |
| Startup: outputs → open inputs → wait until no key is held → grab | never leave a grab behind on failure; no stuck keys in the desktop |
| Device loss releases its outputs; the device is reopened every second | wireless sleep and replugging work without a restart |
| Shared outputs reference-counted; axes: most recent holder wins | releasing one input never releases another's output |
| Timed work on the engine's timer queue; macros as generator fibers | the input loop never blocks; deterministic cancellation |
| Modifiers: exact match, `modifiers(ignore)` as fallback, hidden from the desktop while a mapping runs | Shift+A stays a capital A; outputs are not altered by held modifiers |
| Triggers without a device apply to every input; device-named mappings first | multi-keyboard setups without duplication |
| Axes as triggers: values from the device's range (−1…1 or 0…1), hysteresis 0.05, virtual key codes ≥ 0x10000 | reuses the whole key machinery; no chatter at the threshold |
| Layers: most recently activated first, then the base; mapping fixed at press | unmapped keys fall through; nothing gets stuck when a layer turns off |
| Blocks expanded by the compiler (`call` as if written in place) | no new runtime semantics |
| `inpmap fmt`: re-render from the parse tree, comments re-attached, result must parse to the same tree; gesture handlers not aligned | layout can never change the meaning |
| Profiles in `~/.config/inpmap/`; argument = profile name unless it ends in `.inpmap` or contains `/`; default profile `default` | works the same from a package and from the source tree |
| A configuration without mappings is valid and idle (nothing grabbed or created) | the service can be enabled before mappings exist |
| Only the template unit `inpmap@.service` (instance = profile) | one way to run a service; switching profiles with systemctl |
| Emergency stop Backspace + Escape + Enter, exit 0 | a way out when a configuration makes the keyboard unusable; the service is not restarted |
| Example shipped in the package; `input-config example` copies it and adds the keyboard | packages cannot write into home directories; first contact in two commands |
| Built-in system buttons (host bus) hidden in `input-config` unless `--all` | two identical "Power Button" entries confused users |
| Not wanted: grabbing all keyboards automatically; typing by character through the layout | wrong grabs are dangerous; key codes are what games need |
| MIT license; PyPI via trusted publishing; `pipx install --system-site-packages` | no stored tokens; uses the distribution's evdev instead of compiling it |
| Repository cleaned for publication (2026-10-14): the German AI-assistant brief `project_spec.md` replaced by `docs/roadmap.md`; the personal test protocol replaced by `docs/manual-tests.md`; `docs/macros-research.md` kept only locally (git-ignored); no personal data in this file | a public repository and the PyPI page should show product documentation, not internal working notes |
| Auto-commit at each finished, test-passing step; never push without the maintainer's OK | `CLAUDE.md` §13, §16 |

## Development environment (verified)

- CachyOS (Arch based), KDE Plasma on Wayland, Python 3.14.
- `python-evdev` 2.0.0 from the distribution; the project venv uses
  `--system-site-packages`.
- Device access on the development machine: membership in the `input`
  group, and `/dev/uinput` access through the `uaccess` rules of the
  distribution packages `steam-devices` and `kdeconnect`.
- CI: GitHub Actions on Ubuntu, Python 3.11–3.14; evdev is built there
  against Ubuntu's (older) kernel headers.

## Verification

- Unit tests: 557 passed (`.venv/bin/python -m pytest`); ruff clean.
- Hardware tests (synthetic uinput devices, `-m hardware`): 14; all passed
  in their last runs on the development machine.
- CI: green on Python 3.11, 3.12, 3.13, 3.14.
- Real hardware (a USB keyboard dongle and a Razer Raiju V3 Pro gamepad):
  acceptance test X → Y + gamepad A with suppression; passthrough; LEDs;
  macros; modifiers; tap/hold gestures; axes as triggers (R2, two-stage L2,
  D-pad); layers; the user service incl. login, emergency stop, missing
  gamepad at start, invalid configuration without restart loop; profiles;
  `input-config` with key identification; `detect`; the example; a profile
  without mappings; Kate syntax file — all passed.
- Not verified: Debian/Ubuntu/Fedora installation, other desktops, Steam
  and SDL recognition of the virtual gamepad in games, the nano syntax
  file, installing the generated udev rules.

## Uncommitted work

- None.

## Open questions

- What to do while the AUR step is blocked (maintainer's choice).

## Session log

- **2026-10-13** — V1 (virtual devices, engine, physical input, grab,
  passthrough, robustness, udev rules), V1.1 macros, the configuration
  language replacing JSON, the systemd user service; acceptance test and
  macro tests passed on real hardware.
- **2026-10-14** — Emergency stop; mappings for every input; `disable`;
  `input-config`; `codes`; profiles service; axes as triggers and `axes`;
  layers; blocks; `fmt`; documentation for newcomers; GitHub repository;
  publishing step a (profiles in `~/.config/inpmap`, packaged example and
  syntax files, `detect`, idle configurations); release preparation and
  CI; repository cleaned for publication.

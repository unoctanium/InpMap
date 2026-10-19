# Project status

The handoff document for development sessions (see `CLAUDE.md` §16): where
the project stands, what was decided and why, and what comes next. A new
session continues from this file plus the repository. Goals and milestones:
[roadmap.md](roadmap.md).

Last updated: 2026-10-19

## Current position

- V1, V1.1, the configuration language, the systemd user service and
  **routing by kind** (0.3.0) are done and verified on real hardware.
- **InpMap 0.3.0 released** (2026-10-15): on PyPI; CI and the release
  workflow green; the Arch package in `packaging/aur` is 0.3.0 (pkgrel 1),
  test-built and installed by the maintainer with `makepkg -sri`. The
  maintainer's login service runs a personal profile (`inpmap@gaming`:
  small keyboard with a Caps Lock layer, Raiju pad + its keyboard part as
  one controller with back paddles) with the packaged 0.3.0.
- **Publishing (roadmap)** is in progress:
  - a. ✅ Independent of the source tree (profiles, packaged example and
    syntax files, `inpmap@NAME`, `detect`).
  - b. ✅ PyPI: 0.2.0 (2026-10-14), 0.3.0 (2026-10-15); trusted publishing
    via `.github/workflows/release.yml`, environment `pypi`.
  - c. 🔧 AUR package ready (`packaging/aur/`, README there: test build,
    first upload, updates). User service + packaged uaccess rule for
    /dev/uinput + post-install hint for per-device rules. ⏳ **Upload waits
    until AUR account registration reopens** (HTTP 503 since 2026-10-14; on
    2026-10-19 the page answered behind a bot check, so it may be open
    again: the maintainer checks in a browser); then document `paru -S inpmap`. Interim: installation.md §2a
    (clone, `makepkg -sri`).
  - d. 🔧 Demo, testers, announcements. d1 ✅ (issue forms,
    `CONTRIBUTING.md`, topics). d2 demo GIF: the maintainer records with
    Spectacle (storyboard: `run example` beside an editor and a gamepad
    tester; F1 → `a` + gamepad A; F4 autofire; F8; Caps Lock + WASD;
    `detect`), Claude converts with ffmpeg to `docs/media/demo.gif` (< 5 MB)
    for review. d3 "call for testers" issue text: drafted 2026-10-19 and
    shown to the maintainer for review (not stored in the repository; the
    maintainer posts it). d4 announcement drafts
    per venue (r/linux_gaming, r/hotas, r/hoggit, r/archlinux, Arch forum,
    Show HN) after checking each venue's rules, as a private page.

## Next steps

1. Step d2 (demo recording by the maintainer), then d3, d4 — or whatever
   the maintainer chooses.
2. AUR upload when registration reopens.
3. Optional, not scheduled: capitalised default device names ("InpMap
   Gamepad") — offered, maintainer has not decided; routed axis events
   framed per SYN_REPORT (skipped, no problem observed).
4. Backlog items added 2026-10-14/15 (roadmap): udev device notifications
   instead of 1 s polling; guided device permissions; keeping the other
   interfaces of configured devices open (Raiju stalls when one is unread).

### Routing by kind (0.3.0) — how it was built, for reference

Decided 2026-10-15 by the maintainer after comparing a `forward` option,
"remap in place" and InputPlumber's composite devices; replaces the old
model (every input passed through on a clone), no compatibility kept (no
users yet). Spec: configuration.md §3.4. Code: `routing.py`
(`plan_route` → `RoutePlan`, `Router`), `axes.py` (base values), runtime
wiring, `InputSource.capabilities/start_passthrough`, keyboard LEDs from
the output. Findings during the hardware test: misc buttons (`BTN_0` on the
Raiju's keyboard part) go to the pass-through device; a pad's D-pad axes
become `BTN_DPAD_*` because SDL/Steam ignore hat axes when a device also
has D-pad buttons (SDL Linux joystick code: "Prefer digital D-Pad
buttons"). Steam remembers a controller's name per vendor/product ID, so
the hardware tests now use product IDs 0x7E01/0x7E02 (`tests/hardware.py`).

## Decisions (and why)

| Decision | Reason |
|---|---|
| Configuration language `.inpmap` (lark LALR parser) replaced JSON | readable by hand; errors with `FILE:LINE:COLUMN`; one format only |
| `docs/configuration.md` is the language specification; changes there first, with the maintainer's approval | the reference and the implementation must not drift |
| Linux code names (`KEY_X`, `BTN_SOUTH`) as vocabulary; table generated into `_linux_codes.py` | core free of evdev (Windows later); test cross-checks with evdev |
| Routing by kind (0.3.0): unmapped input goes to the output of its kind; what no output carries (mouse parts, misc buttons, extra axes) to a small pass-through device; `to = OUTPUT`/`to = own`; a device that does not fit is never grabbed (error at start, exit 1; later only logged) | applications see exactly the configured devices (one controller per pad incl. extra buttons); the original device keeps working when the configuration does not fit (maintainer's requirement) |
| Pass-through devices copy vendor/product, without `EV_REP` and `EV_FF`; key repeat is not routed to the outputs | no double key repeat (desktops repeat themselves); no 30 s rumble stalls |
| The virtual gamepad has no D-pad axes; a pad's D-pad axes become `BTN_DPAD_*` | SDL and Steam use only the D-pad buttons when a device has both |
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
| No udev RUN hook like Input Remapper's autoload; replugged devices are found by reopening every second (udev notifications are in the backlog) | a udev rule runs as root and cannot reach a user service; polling costs little and works without root |
| Keep the user service rather than a root service like Input Remapper's (compared again 2026-10-14); the gaps (device permission setup, hotplug delay) go to the backlog as guided permissions and udev notifications | no root process parses user-editable files; fewer parts; one service per user |
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

- Unit tests: 627 passed (`.venv/bin/python -m pytest`); ruff clean.
- Hardware tests (synthetic uinput devices, `-m hardware`): 19, all passed
  on 2026-10-15 (incl. routing: keyboard + pad into the outputs, mouse part
  on a pass-through device, LEDs to the physical keyboard, refused device
  never grabbed).
- CI: green on Python 3.11–3.14 for `6935fbc`; release workflow green for
  `v0.3.0`.
- Real hardware (keyboard dongle, Razer Raiju V3 Pro): everything listed
  for 0.2 (acceptance test, macros, modifiers, gestures, axes, layers,
  service, profiles, tools) plus, on 2026-10-15, routing: typing through
  "InpMap keyboard", LEDs, no keyboard clone; the Raiju with its extra
  buttons as one controller in KDE and Steam (sticks, triggers, D-pad,
  buttons, L4/R4/L5/R5); touchpad unaffected; the packaged 0.3.0 as login
  service.
- Not verified: Debian/Ubuntu/Fedora installation, other desktops, the
  nano syntax file, installing the generated udev rules, two players with
  `to`.

## Uncommitted work

- None.

## Open questions

- None pending. Known device quirk (not an InpMap bug, documented in
  usage.md §5): the Razer Raiju V3 Pro stalls completely when one of its
  USB interfaces is read by no program (e.g. its touchpad disabled in KDE);
  enabling the touchpad fixed it (confirmed 2026-10-15).

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
  CI; repository cleaned for publication; release 0.2.0 on PyPI; AUR
  package prepared, test-built and installed locally (upload blocked by
  closed AUR registration); interim Arch instructions; Input Remapper's
  autoload and root-service design compared with InpMap's user service
  (kept), two backlog items added. All work pushed.
- **2026-10-15** — Step d1: issue forms (bug report, test report),
  `CONTRIBUTING.md`, repository topics (set by the maintainer); verified on
  GitHub. Razer Raiju V3 Pro stalls traced to an unread interface (touchpad
  disabled in KDE), not an InpMap bug; fix confirmed; troubleshooting entry
  in usage.md; backlog item to keep sibling interfaces open. Back
  paddles (`BTN_GRIP*`) on the virtual gamepad. Input/output model
  redesigned after studying InputPlumber: routing by kind (spec, `to`,
  route planner, router, LEDs, switch-on, docs), hardware-tested with the
  Raiju; README "What you can do with it"; release 0.3.0 on PyPI and in
  the Arch package; hardware tests got their own product IDs. All work
  pushed.
- **2026-10-19** — Session start: state consistent, 627 unit tests passed,
  ruff clean. AUR registration page no longer 503 (bot check). Step d3
  "call for testers" text drafted for the maintainer's review.

# Project status

The handoff document for development sessions (see `CLAUDE.md` §16): where
the project stands, what was decided and why, and what comes next. A new
session continues from this file plus the repository. Goals and milestones:
[roadmap.md](roadmap.md).

Last updated: 2026-10-20

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

### Side project: DualSense Edge output via /dev/uhid (started 2026-10-20)

Requested by the separate wow-input project (its own `STATUS.md` holds the
WoW test logs). Goal: WoW Classic "Forever" beta under Proton receives the
back paddles. uinput pads reach Wine only via SDL → XInput (no paddle
bits); a uhid device has a real hidraw node that Proton can pass through to
WoW's SDL HIDAPI PS5 driver. Plan: (1) standalone prototype in `tools/`
(no change to InpMap's code), tested by the maintainer in WoW; (2) only then
an opt-in output `emulate = "dualsense-edge"` (an explicit, documented
exception to "virtual devices never impersonate real hardware").

Research (2026-10-20, from kernel `hid-playstation.c`, SDL2
`SDL_hidapi_ps5.c`/`SDL_gamecontroller.c`, hid-tools `sony_gamepad.py`,
Wine/Proton `winebus.sys` incl. the CachyOS 11.0 fork):
- Report 0x01 is 64 bytes; Edge bits in byte 10: 0x10 left Fn, 0x20 right
  Fn, 0x40 left paddle, 0x80 right paddle. SDL2 (PID 0x0DF2 only):
  PADDLE1 = right paddle, PADDLE2 = left paddle, PADDLE3 = right Fn,
  PADDLE4 = left Fn. WoW's rawIndex is the SDL game-controller button
  index: PADPADDLE1–4 = rawIndex 16–19 (observed in WoW 2026-10-20; not the
  reversed raw joystick buttons b17–b20 of the PS5 driver). Kernel ≥ 7.2: BTN_TRIGGER_HAPPY1–4 = lFn, rFn,
  lPaddle, rPaddle.
- hid-playstation probe needs feature 0x09 (20 bytes), 0x20 (64), 0x05 (41),
  first byte = ID, else probe fails; no CRC on USB; MAC must be unique.
- SDL needs a 64-byte report within 16 ms of opening (else "Bluetooth").
- Proton passes 054C:0DF2 as hidraw by default (no env variable); no XInput
  copy; same-ID SDL/evdev duplicates are removed. Steam Input must be
  disabled for the game, otherwise Steam lists the pad in
  `SDL_GAMECONTROLLER_IGNORE_DEVICES`, which winebus honours for hidraw.
  Avoid the `sdlinput` compat option (sets `PROTON_DISABLE_HIDRAW=1`).
- Steam's `60-steam-input.rules` already gives the hidraw node uaccess
  (`KERNELS=="*054C:0DF2*"`); `/dev/uhid` itself is root-only.
- The descriptor and feature replies come from hid-tools (a dump of a
  DualSense 0x0CE6); check hid-tools' license before copying them into
  InpMap's package in stage 2.

Stage 1 done in code: `tools/dualsense_edge_uhid.py` (stdlib only, run with
sudo) plus `tests/test_tool_dualsense_edge_uhid.py`.

(a) Desktop test passed 2026-10-20: hid-playstation probed it
("Registered DualSense controller hw_version=0x00000313
fw_version=0x0100001e"), created gamepad, motion sensors, touchpad and
headset-jack devices; `/dev/hidraw10` got `user:<maintainer>:rw-`; the
gamepad has BTN_TRIGGER_HAPPY1–4; one round recorded through evdev gave
BTN_SOUTH, HAPPY4, HAPPY3, HAPPY2, HAPPY1 with releases, device removed
cleanly on exit. Steam (running, Steam Input on) immediately created two
virtual "Microsoft X-Box 360 pad" devices (28de:11ff) — expect double
input on the desktop while Steam runs.
(b) WoW test: the maintainer reported "works" on 2026-10-20 (Steam Input
disabled for the shortcut, `--start-delay 60`); details are in wow-input's
`STATUS.md`. Stage 1 is done.

Stage 2 decisions (maintainer, 2026-10-20): option `emulate =
"dualsense-edge"` on a gamepad output; the existing codes stay
(`BTN_SOUTH` = Cross …); back paddles = `BTN_GRIPL`/`BTN_GRIPR`, Fn
buttons = `BTN_GRIPL2`/`BTN_GRIPR2`. My suggestions on the other points
(packaged uaccess rule for `/dev/uhid`, ignore own uhid devices,
document Steam Input off, check the hid-tools license, no feedback) are
in configuration.md §3.5, approved by the maintainer 2026-10-20 ("go").

Stage 2 implemented 2026-10-20 (unit-tested; hardware test pending):
- `backends/linux_uhid.py`: `UhidDualSenseEdge` (one thread per device
  answers GET_REPORT and streams a report every 4 ms; set_key/set_axis
  change state under a lock and send at once), own report descriptor and
  feature replies written from the protocol facts — hid-tools is GPL-2.0,
  so its dump is no longer used; MAC = 02:49:4d + 3 bytes of sha256(output
  id) (stable, distinct, marks the kernel's nodes as own via `uniq`).
- `models.OutputDeviceSpec.emulate`, `codes.DUALSENSE_EDGE_BUTTONS`,
  `output_capabilities(..., emulate)`, routing uses the emulated set,
  validator errors (unknown value, non-gamepad, button the Edge lacks).
- `linux_setup.is_own_node(phys, uniq)` used by device listing,
  input-config and input resolution.
- `inpmap udev-rules`: adds `/dev/uhid` (uaccess) and a hidraw rule for
  uhid-created 054C:0DF2 only when the profile emulates (decided instead
  of a packaged uhid rule: no wider permissions for everyone who installs
  the package).
- `tools/dualsense_edge_uhid.py` is now a thin press-sequence tool on top
  of the module.
- Docs: configuration.md §3.5, installation.md §3, usage.md §4/§5,
  manual-tests.md §2b, CHANGELOG (Unreleased), README, roadmap.
- The two earlier local commits of the prototype (7536f2d, …) contain the
  hid-tools (GPL-2.0) descriptor dump; not pushed. Ask the maintainer
  before pushing whether to squash them out (history rewrite needs OK).
Hardware test of the integration, 2026-10-20 (maintainer's gaming profile
copy with `emulate`, `.venv/bin/inpmap run`, udev rules from `inpmap
udev-rules` installed): hid-playstation registered it with our own
firmware values (hw 0x1, fw 0x10000); name "InpMap Gamepad", uniq
02:49:4d:54:db:a8; `inpmap devices` marks its nodes as own; /dev/uhid and
/dev/hidraw10 have `user:<maintainer>:rw-`. evdev recording: Raiju F21 →
BTN_TRIGGER_HAPPY3 (left paddle), F22 → HAPPY4 (right paddle), face,
shoulder, trigger and menu buttons, every press released. WoW (Steam
Input disabled): controller reported as DualSense, all buttons detected
(maintainer). Stopping InpMap: WoW reports the DualSense disconnected.
After the DualSense disappears, WoW switches to another pad in-game with
the addon's `/il use 2` (CVar GamePadSingleActiveID); confirmed by the
maintainer.

Maintainer's decisions 2026-10-20: squash the unpushed prototype commits
(done: one commit b47ce2c…, tree identical, no hid-tools data left in the
unpushed history); `emulate = "dualsense-edge"` is now in the maintainer's
`gaming` profile (the installed 0.3.0 rejects it: `inpmap@gaming` fails
until 0.4.0 is installed); release 0.4.0. 0.4.0 released (push + tag
v0.4.0 on the maintainer's "go"; on PyPI). Two problems found after it:
(1) the AUR test build failed: `tests/test_tool_dualsense_edge_uhid.py`
needs `tools/`, which the sdist lacks → now skipped there (like the
packaged-rule test); (2) the maintainer expected `BTN_GRIPL/GRIPR/GRIPL2/
GRIPR2` = `PADPADDLE1/2/3/4`, but §3.5 followed SDL's sides (SDL counts
paddles as seen from the back: paddle 1 = the Edge's right paddle).
Decision (maintainer, 2026-10-20): number order — GRIPL → Edge right
paddle bit (SDL 1), GRIPR → left paddle (2), GRIPL2 → right Fn (3), GRIPR2
→ left Fn (4); Steam/evtest show it mirrored, documented in §3.5. Both in
0.4.1. Then AUR PKGBUILD 0.4.1, `makepkg -sri` by the maintainer,
`inpmap udev-rules gaming` reinstalled, service restart; the WoW check of
the new order is still to do.

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

- Unit tests: 684 passed (`.venv/bin/python -m pytest`); ruff clean.
- Hardware tests (synthetic uinput devices, `-m hardware`): 19, all passed
  on 2026-10-20 (incl. routing: keyboard + pad into the outputs, mouse
  part on a pass-through device, LEDs to the physical keyboard, refused
  device never grabbed). They do not cover the emulated controller (needs
  /dev/uhid); that was tested by hand in WoW (above).
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

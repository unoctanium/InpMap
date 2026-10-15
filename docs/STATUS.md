# Project status

The handoff document for development sessions (see `CLAUDE.md` §16): where
the project stands, what was decided and why, and what comes next. A new
session continues from this file plus the repository. Goals and milestones:
[roadmap.md](roadmap.md).

Last updated: 2026-10-15

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
    machine now runs the locally built AUR package. Interim instructions
    for Arch/CachyOS/Manjaro (installation.md §2a, README): clone, `cd
    packaging/aur`, `makepkg -sri` (order checked in /usr/bin/makepkg:
    with -s -r -i only make/check deps are removed, runtime deps stay);
    PyPI became §2b, source §2c. ⏳ **Open:** **upload to the AUR once account
    registration reopens** (it was closed on 2026-10-14: HTTP 503, "paused
    while we deal with a wave of automated account creation"; watch
    aur-general / Arch news), following packaging/aur/README.md; then
    document `paru -S inpmap` in installation.md and the README.
  - d. 🔧 Demo, a few external testers, then announcements
    (r/linux_gaming, r/hotas, r/hoggit, r/archlinux, Arch forum, Show HN),
    respecting each community's self-promotion rules. Plan:
    - d1. ✅ (2026-10-15) Issue forms `.github/ISSUE_TEMPLATE/`
      (`bug_report.yml`, `test_report.yml`, `config.yml` linking the
      troubleshooting table), `CONTRIBUTING.md` (linked from the README and
      development.md, in the sdist). Pushed; the maintainer confirmed both
      forms appear on GitHub's "New issue" page and set the repository
      topics in the GitHub UI (`gh` is not installed on the development
      machine).
    - d2. Demo GIF: the maintainer records with Spectacle following the
      storyboard (`input-config example` with `i`; `run example` beside an
      editor and a gamepad tester; F1 → `a` + gamepad A; Caps Lock + WASD;
      `detect`); Claude converts it with ffmpeg to `docs/media/demo.gif`.
    - d3. "Call for testers" issue text.
    - d4. Announcement drafts per venue after checking each venue's rules,
      as a private page, not in the repository.

## Next steps

**Current work: routing by kind (InpMap 0.3)** — decided 2026-10-15 by the
maintainer (replaces the `forward` idea; inspired by InputPlumber's
composite devices). Spec: configuration.md §3.4 (approved 2026-10-15;
carries a temporary "being implemented" note to remove in step 9; its
examples are `text` blocks until `to` exists). Same `version 1`, no
compatibility with the old pass-through model (no users yet). Plan (each
step committed with passing tests):
0. ✅ Spec (configuration.md §1, §3.1–3.4, §7.3, §8, §9, §12.3).
1. ✅ Output capabilities in core (`output.output_capabilities`, `codes.KEYBOARD_OUTPUT_KEYS`/`GAMEPAD_OUTPUT_BUTTONS`, `macros.OUTPUT_AXIS_KINDS`). The D-pad axes added here were removed again after the Steam test (see "Open questions"): physical D-pad axes become BTN_DPAD_*.
2. ✅ Language `to` (`to = OUT[, OUT]`, `to = own`; `own` reserved; grammar,
   compiler, `InputDeviceSpec.own/targets`, `Validator.resolve_targets`,
   used-rules, syntax files; tests in `tests/test_routing_config.py`).
   Until step 7 the runtime still passes every input through on its own
   device (as if `to = own`).
3. ✅ Route planner `routing.py` (`plan_route` → `RoutePlan`,
   `AxisRoute.value` conversion incl. unsigned sticks and D-pad axes,
   `InputRefused` with fix hints; tests `tests/test_routing.py`). Decisions
   made here (spec §3.4 rule 2 updated): codes a mapping names need no
   target (dropped when the mapping does not fire); touch devices always
   need `to = own`; ABS axes outside the joystick/touch sets (ABS_VOLUME,
   ABS_MISC) go to the pass-through.
4. ✅ Shared holders: axis base values (`AxisStacks.set_base/clear_base`;
   a mapping overrides, afterwards the device value applies again; most
   recently updated device wins). Buttons share the engine's reference
   counts through its `press_key`/`release_key` (used by the router).
5. ✅ Router (`routing.Router`): unmapped keys/buttons as engine holders
   (shared ref counts), axes as base values, key repeat dropped (desktops
   repeat the virtual keyboard themselves), mask/unmask for modifiers,
   detach releases everything; tests in `tests/test_routing.py`.
6. ✅ Keyboard LED parts: the virtual keyboard declares NUML/CAPSL/SCROLLL;
   `OutputDevice.fileno/poll_leds`, `OutputManager.feedback_filenos/poll_leds`
   (hardware test passes); `InputSource.set_leds`; `InputBackend.wait(…,
   feedback)`. Applying them to routed keyboards is wired in step 7.
7. ✅ Switched on (2026-10-15): backend opens without a forwarder;
   `InputSource.capabilities/start_passthrough` (full copy for `to = own`,
   partial device for mouse buttons/EV_REL/extra axes, none otherwise);
   runtime plans each device at open (`plan_route`), routes unmapped
   keys/axes through `Router`, applies keyboard-output LEDs to routed
   keyboards (also at grab), detaches on loss/shutdown. Refusal: error at
   start (also with --wait-for-devices; CLI exit 1 = no service restart),
   later only logged and retried. Existing pass-through tests now use
   `to = own`; new tests: `tests/test_runtime_routing.py` (fakes) and
   routed hardware tests in `tests/test_linux_input.py` (keyboard + pad
   into the outputs with no pass-through devices, axes scaled incl. D-pad,
   mouse part on a pass-through device with only BTN_LEFT/REL, LEDs to the
   physical keyboard, refused device never grabbed). Unit tests 626, all
   19 hardware tests pass. Docs (step 9) not yet updated: usage.md and
   README still describe the old pass-through model.
8. Optional: axis events framed per SYN_REPORT.
9. Docs, example, manual tests, CHANGELOG; remove the §3.4 note.
Risks noted: per-keyboard desktop settings lost (use `to = own`);
DirectInput pads and flight sticks need `to = own`; Steam may read the
physical pad via hidraw (unchanged).

0. ✅ (2026-10-15) Back paddles on the virtual gamepad: `BTN_GRIPL`,
   `BTN_GRIPR`, `BTN_GRIPL2`, `BTN_GRIPR2` accepted as gamepad outputs
   (range 0x220–0x227 in `codes.py`), declared only when mapped;
   configuration.md §3.3 with example, CHANGELOG "Unreleased". Verified:
   unit tests, hardware backend tests, a real uinput gamepad declaring the
   four codes. Not verified: Steam showing them from an InpMap profile.
   **Proposed next (maintainer to approve the design in configuration.md
   first):** merge a physical device into a named output (e.g. `input pad
   { …; forward = gamepad }`), so a controller's sticks and buttons and
   mapped extras come out of one virtual gamepad instead of a forwarding
   device plus the InpMap gamepad.

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
3. Step c: done except the AUR upload, which waits until AUR registration
   reopens.
4. **Next: step d2** — the maintainer records the demo with Spectacle
   following the storyboard (under "Current position", d2) and gives the
   video's path; Claude converts it to `docs/media/demo.gif` (target under
   5 MB) for the maintainer to review before it goes into the README.
   Preparation asked of the maintainer: add the new keyboard to the
   `example` profile (`inpmap input-config example`), since the old
   keyboard was replaced. Three backlog items were added on 2026-10-14/15
   (udev device notifications; guided device permissions; keeping the
   other interfaces of configured devices open) — not scheduled.

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

- **Pending manual test (asked 2026-10-15): routing on real hardware**, with
  the development build (`.venv/bin/inpmap`), services stopped:
  (1) `run example --timeout 120`: normal typing in an editor works through
  "InpMap keyboard", F1 gives `a` + gamepad A, Caps Lock + WASD arrows, Num
  Lock LED on the physical keyboard follows; `inpmap devices`/KDE show no
  "InpMap forward: …" for the keyboard. (2) a Raiju profile (pad +
  keyboard part, F15–F18 → BTN_GRIP*; file given to the maintainer as
  `raiju-test`): KDE game controller settings and Steam show one
  controller "InpMap gamepad" with sticks, triggers, D-pad, buttons and
  L4/R4/L5/R5; the touchpad keeps working. Awaited: pass/fail per point.
  Result so far: test 1 (keyboard, example) **passed**. Test 2 first run
  refused the Raiju's keyboard part because of `BTN_0` (a misc button);
  fixed: buttons that are neither keys nor gamepad/joystick buttons go to
  the pass-through device (spec §3.4 rule 3 updated); a dry run of
  `plan_route` with the real Raiju capabilities is now clean. Test 2
  repeated: **all points passed except the D-pad in Steam's controller
  test** (it worked in KDE's game controller page). Cause, verified in
  SDL's Linux joystick code ("Prefer digital D-Pad buttons, but settle for
  digital or analog hat"): the virtual gamepad had both BTN_DPAD_* and the
  new ABS_HAT0X/Y, so SDL/Steam read only the (unused) buttons. Fixed: the
  output has no D-pad axes again; a pad's D-pad axes are turned into
  BTN_DPAD_* presses by the router (shared ref counts with mappings); spec
  §3.3 and §3.4 rule 4 updated; unit and hardware tests pass. Awaited: the
  D-pad in Steam's controller test with the Raiju profile.

- **Found (2026-10-15), not an InpMap bug: Razer Raiju V3 Pro stalls when
  one of its USB interfaces is not read.** The controller has a gamepad
  interface (xpad), a keyboard/mouse interface and a touchpad interface
  (hid-multitouch); the kernel polls a HID interface only while some program
  has one of its event devices open. KDE had the Razer touchpad (and mouse)
  disabled (`kcminputrc` `Enabled=false`), so nobody read the touchpad.
  Observed: after touching the touchpad the gamepad interface delivered no
  events at all (read-only logger on the event device; no kernel, udev or
  journal messages); opening only the touchpad event device read-only
  revived the stick at once. Confirmed fix: with the touchpad enabled in
  KDE again, the stick keeps working after touching the touchpad. This also explains the earlier symptoms with
  the keyboard interface (stuck Enter released when `inpmap detect` opened
  all devices) and why `detect` seemed to "repair" things. Documented in
  usage.md §5 (troubleshooting). Keeping the other interfaces of a
  configured device open was added to the roadmap backlog (maintainer's
  decision, 2026-10-15).

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
  in usage.md; backlog item to keep sibling interfaces open. All work
  pushed.

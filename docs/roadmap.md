# InpMap roadmap

This is the product specification of InpMap: what it is for, the
requirements it has to meet, and its milestones with their status. How
InpMap behaves in detail is documented in [configuration.md](configuration.md)
(the configuration language) and [usage.md](usage.md) (the commands).

## Goal

InpMap is a configuration-driven input remapper with a mapping and macro
engine designed to work across platforms.

- **One input, several virtual devices.** A single key or button can drive
  actions on different virtual devices at once, for example a key on a
  virtual keyboard and a button on a virtual gamepad.
- **Rules in a text file**, not in a GUI: the InpMap configuration language
  (`.inpmap` files), readable, versioned and checked before any device is
  touched. (The first versions used JSON; the language replaced it.)
- **Extensible** without rewriting: macros, further device types and other
  platforms are added behind clear interfaces.

[Input Remapper](https://github.com/sezanzeb/input-remapper) serves as the
functional reference for device handling, mapping rules, press/release
semantics, macros, modifiers, conditions and virtual devices. InpMap studies
its documentation and code and defines its own semantics; it does not copy
code (Input Remapper is GPL-3.0, InpMap is MIT).

## Constraints

- Python (3.11 or newer); few dependencies, each one justified.
- The mapping engine is independent of the operating system. Linux-specific
  code (`evdev` for reading devices, `uinput` for virtual devices) stays in
  the Linux backend, behind small interfaces, so a Windows backend can be
  added.
- The runtime is separate from the command line, so the same code runs in
  the foreground, as a service and later under a GUI.
- Library APIs are verified against the installed library or its
  documentation before they are relied on.

## Requirements

### Input and output

- Read physical keyboards and gamepad buttons; press and release are
  distinct events; key repeat is handled explicitly.
- Create a virtual keyboard and a virtual gamepad that Linux and test tools
  (e.g. `evtest`) recognise. One rule may act on several virtual devices.
- **Suppression:** an input replaced by a mapping must not also reach the
  application. Linux needs an exclusive grab (`EVIOCGRAB`) for this; reading
  alone does not suppress. Unmapped input goes unchanged to the virtual
  device of its kind, so applications see the configured devices instead
  of the physical ones; what no virtual device carries (e.g. a mouse part)
  passes through on a device of its own. Which devices are grabbed, and how
  they are released on exit and on errors, is documented.

### State

- Distinguish input pressed / released and output active / released.
- If several inputs drive the same output, releasing one must not release
  the output while another still holds it (e.g. two buttons both mapped to
  `KEY_Y`: `KEY_Y` stays pressed while either is held).
- Every active output is released on exit, on device loss and on errors.

### Safety

- No running as root; access to `/dev/input/event*` and `/dev/uinput` is
  set up narrowly and documented; no blanket permission changes.
- Devices are released on normal exit; there is a safe way out (an
  emergency stop) when a configuration makes the keyboard unusable.
- An invalid configuration never produces uncontrolled input; it is
  rejected before any device is touched.
- Diagnostics are sufficient without logging what the user types.
- Exclusive grabbing can conflict with the desktop, shortcuts and other
  remappers; InpMap must not assume every device can be grabbed.

### Background operation

- Start, stop and restart through `systemd`, without a terminal or GUI,
  running the same runtime code as the foreground mode.
- Load a defined configuration; log to `journald`; handle devices that
  appear and disappear; log errors and restarts; release everything when
  stopping; minimal, documented permissions.

### Quality

- Unit tests for the core without root, hardware or a desktop session;
  hardware tests with synthetic devices; manual tests on real hardware
  ([manual-tests.md](manual-tests.md)). Unit, simulated and real hardware
  tests are always kept apart.

### Acceptance test of the first version

Pressing `X` on the physical keyboard: `X` is suppressed, the virtual
keyboard reports `Y` pressed and the virtual gamepad reports its south face
button (A) pressed. Releasing `X` releases both, and nothing stays stuck.
(Passed on real hardware.)

## Milestones

| Milestone | Content | Status |
|---|---|---|
| **V1** – Linux, no GUI | keyboard and gamepad buttons in, virtual keyboard and gamepad out, several outputs per rule, press/release, suppression and passthrough, validation, logging, CLI | done |
| **V1.1** – mappings and macros | sequences, waits, loops, parallel branches, conditions, variables, modifiers, gestures (tap, double tap, long press), clean cancellation; based on a study of Input Remapper | done |
| Configuration language | `.inpmap` replaces JSON; layers, reusable blocks, `disable`, mappings for one device or every input, sticks/triggers/D-pad as triggers | done |
| Routing by kind | unmapped input goes to the outputs of its kind (one controller per pad incl. extra buttons, `to`, refusal of devices that do not fit, mouse parts pass through), inspired by InputPlumber's composite devices | done |
| Background operation | systemd user service with profiles (`inpmap@NAME`), emergency stop | done |
| Tools | `input-config`, `detect`, `axes`, `codes`, `check`, `macro-trace`, `fmt`, `udev-rules`, `service-unit`, `syntax-file` | done |
| **Publishing** | installable without the source code (profiles in `~/.config/inpmap`, example and editor files in the package); CI; release 0.2.0 on PyPI; AUR package; demo and announcement | in progress |
| **V2** – Windows, no GUI | Windows input and output backend; reuse engine, language and model; virtual keyboard/gamepad solutions, drivers, permissions and installation documented | planned |
| **V3** – Windows GUI | graphical configuration, device selection, mapping and macro editor, status and diagnostics, profiles | planned |
| **V4** – Linux GUI | GUI on the shared engine, desktop integration, device and permission management, configuration and diagnostics | planned |

## Backlog

Not scheduled; candidates for future versions:

- mouse output, and a gamepad as a mouse (sensitivity, dead zone, curve);
- analog axes driving analog outputs (e.g. a stick with a curve);
- mappings per application;
- dual-role keys that hold back other keys until decided;
- conditions on other held keys;
- randomised "human" timing (normally distributed waits);
- a per-side modifier setting (e.g. Right Alt as a normal key while Left Alt
  stays a modifier);
- notice configured devices that are plugged in through udev's device
  notifications instead of checking every second (picked up at once, no
  work while idle; possible without root);
- device permissions guided where they are needed: `input-config` and `run`
  notice a device without access and print the exact command that grants
  it (the udev rule for that one device, or the `input` group with its
  risk stated), instead of leaving the user to find installation.md;
- keep the other interfaces of a configured device open (read and ignored,
  not grabbed) while InpMap runs: some devices (e.g. Razer Raiju V3 Pro)
  stall completely when one of their interfaces, such as a touchpad
  switched off in the desktop, is read by no program;
- a system-wide service (without a logged-in user).

Not planned: grabbing all keyboards automatically, and typing text by
character through the keyboard layout (InpMap works with key codes).

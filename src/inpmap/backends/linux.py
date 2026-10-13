"""Linux backend: virtual output devices through /dev/uinput (python-evdev).

Capability choices follow how the Linux stack classifies devices (verified
against udev ``input_id``, libinput ``evdev.c`` and SDL sources, 2026-10-13;
details in docs/STATUS.md):

* Virtual keyboard: every ``KEY_*`` code and no ``BTN_*``. Codes 1-31 make
  udev set ``ID_INPUT_KEYBOARD``; libinput (KDE Wayland) accepts it as a
  keyboard. Declaring the full key set also prepares for passthrough of
  unmapped keys. No ``EV_REP``: compositors implement key repeat themselves.
* Virtual gamepad: the standard face/shoulder/menu/stick buttons, D-pad
  buttons, two sticks and two triggers, and no ``KEY_*`` codes (those would make
  udev/libinput stop treating it as a joystick). ``ABS_X``/``ABS_Y`` are needed
  for SDL's non-udev detection path (e.g. inside containers); a complete
  standard layout lets SDL generate a gamepad mapping automatically. Axes
  stay at rest; V1 never moves them.

NO_FORCE_FEEDBACK: python-evdev enables EV_FF by default (max_effects=96).
The kernel then forwards a game's rumble upload to us and blocks the game for
up to 30 s waiting for an answer (uinput.c: wait_for_completion_timeout
30 * HZ). We do not implement force feedback, so every device is created
with max_effects=0, which leaves EV_FF disabled.
"""

from __future__ import annotations

import logging

from evdev import AbsInfo, UInput, ecodes
from evdev.uinput import UInputError

from .. import codes
from ..macros import AXIS_KINDS, AxisKind
from ..models import OutputDeviceSpec, OutputKind
from ..output import OutputError

log = logging.getLogger(__name__)

# Identity of our virtual devices. Not a registered USB vendor ID; it only
# needs to be stable and must not impersonate real hardware (SDL drivers
# special-case known controllers by VID/PID).
BUSTYPE = ecodes.BUS_USB
VENDOR = 0x0001
PRODUCT = {OutputKind.KEYBOARD: 0x0001, OutputKind.GAMEPAD: 0x0002}
VERSION = 0x0001
PHYS = "inpmap"

GAMEPAD_BUTTONS: tuple[int, ...] = (
    ecodes.BTN_SOUTH,
    ecodes.BTN_EAST,
    ecodes.BTN_NORTH,
    ecodes.BTN_WEST,
    ecodes.BTN_TL,
    ecodes.BTN_TR,
    ecodes.BTN_TL2,
    ecodes.BTN_TR2,
    ecodes.BTN_SELECT,
    ecodes.BTN_START,
    ecodes.BTN_MODE,
    ecodes.BTN_THUMBL,
    ecodes.BTN_THUMBR,
    ecodes.BTN_DPAD_UP,
    ecodes.BTN_DPAD_DOWN,
    ecodes.BTN_DPAD_LEFT,
    ecodes.BTN_DPAD_RIGHT,
)

_STICK = AbsInfo(value=0, min=-32768, max=32767, fuzz=16, flat=128, resolution=0)
_TRIGGER = AbsInfo(value=0, min=0, max=255, fuzz=0, flat=0, resolution=0)

GAMEPAD_AXES: tuple[tuple[int, AbsInfo], ...] = (
    (ecodes.ABS_X, _STICK),
    (ecodes.ABS_Y, _STICK),
    (ecodes.ABS_RX, _STICK),
    (ecodes.ABS_RY, _STICK),
    (ecodes.ABS_Z, _TRIGGER),
    (ecodes.ABS_RZ, _TRIGGER),
)
_ABS_INFO = dict(GAMEPAD_AXES)


def axis_raw(code: int, value: float) -> int:
    """Convert a fraction of the axis range to the device's raw value.

    Sticks: -1.0 -> min, 0.0 -> 0, 1.0 -> max (the asymmetric int16 range is
    scaled separately per side). Triggers: 0.0 -> min, 1.0 -> max.
    """
    info = _ABS_INFO[code]
    if AXIS_KINDS[code] is AxisKind.STICK:
        return round(value * (info.max if value >= 0 else -info.min))
    return round(info.min + value * (info.max - info.min))


KEYBOARD_KEYS: tuple[int, ...] = tuple(
    sorted({codes.code_from_name(n) for n in codes.all_names() if n.startswith("KEY_")})
)


def capabilities(kind: OutputKind, mapped_codes: frozenset[int]) -> dict[int, list]:
    """Capabilities to declare for a virtual device of ``kind``.

    ``mapped_codes`` are the codes the configuration emits; they are always
    included (the validator guarantees they fit the device kind).
    """
    if kind is OutputKind.KEYBOARD:
        return {ecodes.EV_KEY: sorted(set(KEYBOARD_KEYS) | mapped_codes)}
    if kind is OutputKind.GAMEPAD:
        return {
            ecodes.EV_KEY: sorted(set(GAMEPAD_BUTTONS) | mapped_codes),
            ecodes.EV_ABS: list(GAMEPAD_AXES),
        }
    raise ValueError(f"unsupported output kind: {kind}")


class LinuxOutputDevice:
    """A uinput device. Implements :class:`inpmap.output.OutputDevice`."""

    def __init__(self, spec: OutputDeviceSpec, uinput: UInput) -> None:
        self.spec = spec
        self._uinput = uinput

    @property
    def node(self) -> str | None:
        """The /dev/input/event* node of the created device, if known."""
        device = getattr(self._uinput, "device", None)
        return device.path if device is not None else None

    def set_key(self, code: int, pressed: bool) -> None:
        try:
            self._uinput.write(ecodes.EV_KEY, code, 1 if pressed else 0)
            self._uinput.syn()
        except OSError as exc:
            raise OutputError(f"writing to '{self.spec.name}' failed: {exc}") from exc

    def set_axis(self, code: int, value: float) -> None:
        if self.spec.kind is not OutputKind.GAMEPAD or code not in AXIS_KINDS:
            raise OutputError(f"'{self.spec.name}' has no axis {code:#x}")
        try:
            self._uinput.write(ecodes.EV_ABS, code, axis_raw(code, value))
            self._uinput.syn()
        except OSError as exc:
            raise OutputError(f"writing to '{self.spec.name}' failed: {exc}") from exc

    def close(self) -> None:
        try:
            self._uinput.close()
        except OSError as exc:
            raise OutputError(f"closing '{self.spec.name}' failed: {exc}") from exc


class LinuxOutputBackend:
    """Creates uinput devices. Implements :class:`inpmap.output.OutputBackend`."""

    def __init__(self, devnode: str = "/dev/uinput") -> None:
        self.devnode = devnode

    def create(self, spec: OutputDeviceSpec, key_codes: frozenset[int]) -> LinuxOutputDevice:
        try:
            uinput = UInput(
                events=capabilities(spec.kind, key_codes),
                name=spec.name,
                vendor=VENDOR,
                product=PRODUCT[spec.kind],
                version=VERSION,
                bustype=BUSTYPE,
                devnode=self.devnode,
                phys=PHYS,
                max_effects=0,  # no EV_FF; see NO_FORCE_FEEDBACK
            )
        except (UInputError, OSError) as exc:
            raise OutputError(
                f"cannot create virtual {spec.kind.value} '{spec.name}': {exc}. "
                f"Check that {self.devnode} exists and is writable by this user "
                "(see README, 'Device permissions')."
            ) from exc
        device = LinuxOutputDevice(spec, uinput)
        log.debug("uinput device '%s' at %s", spec.name, device.node)
        return device

"""Linux backend: virtual output devices through /dev/uinput (python-evdev).

Capability choices follow how the Linux stack classifies devices (checked
against the sources of udev ``input_id``, libinput ``evdev.c`` and SDL's
Linux joystick and gamepad code):

* Virtual keyboard: every ``KEY_*`` code and no ``BTN_*``. Codes 1-31 make
  udev set ``ID_INPUT_KEYBOARD``; libinput (KDE Wayland) accepts it as a
  keyboard. Declaring the full key set also prepares for passthrough of
  unmapped keys. No ``EV_REP``: compositors implement key repeat themselves.
* Virtual gamepad: the standard face/shoulder/menu/stick buttons, D-pad
  buttons, two sticks and two triggers, and no ``KEY_*`` codes (those would make
  udev/libinput stop treating it as a joystick). No D-pad axes: with both D-pad
  buttons and axes, SDL (and so Steam) uses only the buttons. ``ABS_X``/``ABS_Y`` are needed
  for SDL's non-udev detection path (e.g. inside containers); a complete
  standard layout lets SDL generate a gamepad mapping automatically.

NO_FORCE_FEEDBACK: python-evdev enables EV_FF by default (max_effects=96).
The kernel then forwards a game's rumble upload to us and blocks the game for
up to 30 s waiting for an answer (uinput.c: wait_for_completion_timeout
30 * HZ). We do not implement force feedback, so every device is created
with max_effects=0, which leaves EV_FF disabled.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping

from evdev import AbsInfo, UInput, ecodes
from evdev.uinput import UInputError

from ..macros import OUTPUT_AXIS_KINDS, AxisKind, Led
from ..models import OutputDeviceSpec, OutputKind
from ..output import OutputError, output_capabilities

log = logging.getLogger(__name__)

# Identity of our virtual devices. Not a registered USB vendor ID; it only
# needs to be stable and must not impersonate real hardware (SDL drivers
# special-case known controllers by VID/PID).
BUSTYPE = ecodes.BUS_USB
VENDOR = 0x0001
PRODUCT = {OutputKind.KEYBOARD: 0x0001, OutputKind.GAMEPAD: 0x0002}
VERSION = 0x0001
PHYS = "inpmap"

_STICK = AbsInfo(value=0, min=-32768, max=32767, fuzz=16, flat=128, resolution=0)
_TRIGGER = AbsInfo(value=0, min=0, max=255, fuzz=0, flat=0, resolution=0)
_ABS_INFO = {AxisKind.STICK: _STICK, AxisKind.TRIGGER: _TRIGGER}
LEDS = {
    ecodes.LED_NUML: Led.NUMLOCK,
    ecodes.LED_CAPSL: Led.CAPSLOCK,
    ecodes.LED_SCROLLL: Led.SCROLLLOCK,
}


def axis_raw(code: int, value: float) -> int:
    """Convert a fraction of the axis range to the device's raw value.

    Sticks: -1.0 -> min, 0.0 -> 0, 1.0 -> max (the asymmetric int16 range is
    scaled separately per side). Triggers: 0.0 -> min, 1.0 -> max.
    """
    kind = OUTPUT_AXIS_KINDS[code]
    info = _ABS_INFO[kind]
    if kind is AxisKind.TRIGGER:
        return round(info.min + value * (info.max - info.min))
    return round(value * (info.max if value >= 0 else -info.min))


def capabilities(kind: OutputKind, mapped_codes: frozenset[int]) -> dict[int, list]:
    """Capabilities to declare for a virtual device of ``kind``.

    ``mapped_codes`` are the codes the configuration emits; they are always
    included (the validator guarantees they fit the device kind).
    """
    caps = output_capabilities(kind, mapped_codes)
    events: dict[int, list] = {ecodes.EV_KEY: sorted(caps.keys)}
    if kind is OutputKind.KEYBOARD:
        # The desktop sets the lock LEDs here; InpMap shows them on the
        # physical keyboards routed to this output (configuration.md §3.4).
        events[ecodes.EV_LED] = sorted(LEDS)
    if caps.axes:
        events[ecodes.EV_ABS] = [(code, _ABS_INFO[k]) for code, k in sorted(caps.axes.items())]
    return events


class LinuxOutputDevice:
    """A uinput device. Implements :class:`inpmap.output.OutputDevice`."""

    def __init__(self, spec: OutputDeviceSpec, uinput: UInput) -> None:
        self.spec = spec
        self._uinput = uinput
        self._lit: set[int] = set()  # LED codes the desktop set

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
        if self.spec.kind is not OutputKind.GAMEPAD or code not in OUTPUT_AXIS_KINDS:
            raise OutputError(f"'{self.spec.name}' has no axis {code:#x}")
        try:
            self._uinput.write(ecodes.EV_ABS, code, axis_raw(code, value))
            self._uinput.syn()
        except OSError as exc:
            raise OutputError(f"writing to '{self.spec.name}' failed: {exc}") from exc

    def fileno(self) -> int | None:
        return self._uinput.fd if self.spec.kind is OutputKind.KEYBOARD else None

    def poll_leds(self) -> frozenset[Led] | None:
        if self.spec.kind is not OutputKind.KEYBOARD:
            return None
        try:
            events = list(self._uinput.read())
        except BlockingIOError:
            return None
        except OSError as exc:
            log.warning("reading LEDs of '%s' failed: %s", self.spec.name, exc)
            return None
        before = set(self._lit)
        for event in events:
            if event.type == ecodes.EV_LED and event.code in LEDS:
                if event.value:
                    self._lit.add(event.code)
                else:
                    self._lit.discard(event.code)
        if self._lit == before:
            return None
        return frozenset(LEDS[code] for code in self._lit)

    def close(self) -> None:
        try:
            self._uinput.close()
        except OSError as exc:
            raise OutputError(f"closing '{self.spec.name}' failed: {exc}") from exc


class LinuxOutputBackend:
    """Creates uinput devices. Implements :class:`inpmap.output.OutputBackend`.

    ``products`` overrides the product IDs; the hardware tests use their own,
    because Steam remembers a controller's name per vendor and product ID.
    """

    def __init__(
        self, devnode: str = "/dev/uinput", products: Mapping[OutputKind, int] = PRODUCT
    ) -> None:
        self.devnode = devnode
        self.products = dict(products)

    def create(self, spec: OutputDeviceSpec, key_codes: frozenset[int]) -> LinuxOutputDevice:
        try:
            uinput = UInput(
                events=capabilities(spec.kind, key_codes),
                name=spec.name,
                vendor=VENDOR,
                product=self.products[spec.kind],
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
                "(see docs/installation.md, 'Device permissions')."
            ) from exc
        device = LinuxOutputDevice(spec, uinput)
        log.debug("uinput device '%s' at %s", spec.name, device.node)
        return device

"""Linux backend: physical input devices via evdev, EVIOCGRAB and pass-through.

Reading an evdev node does not stop other programs from receiving its events.
Suppression therefore uses ``EVIOCGRAB``: while grabbed, the kernel delivers
the device's events only to us, so the desktop sees nothing from it. Unmapped
keys, buttons and axes go to the outputs (core: :mod:`inpmap.routing`). What
no output carries — mouse parts, extra axes — is re-emitted on a small
*pass-through* uinput device with the physical device's identity; with
``to = own`` that device mirrors the whole physical device.

Notes:
* ``EV_REP`` is not copied to the forwarding device, otherwise the kernel
  would generate a second, synthetic key repeat on top of forwarded repeats.
* Keyboard LED state (Caps/Num/Scroll Lock) is set by the desktop on the
  keyboard output (or, with ``to = own``, on the pass-through device); it is
  read back from the uinput descriptor and applied to the physical device.
* Force feedback (rumble) is not passed through; forwarders have no EV_FF.
* Face buttons: InpMap's names follow Xbox controllers (``xpad``), SDL and
  Steam, where 0x133 is the left button (BTN_FACE_LEFT) and 0x134 the top one
  (configuration.md §3.3). The kernel drivers of PlayStation and Nintendo
  controllers send them the other way round (the kernel's positional names
  BTN_NORTH/BTN_WEST),
  so for those devices the two codes are swapped on the way in and back on
  the way to their own pass-through device. SDL makes the same distinction.
* Our own virtual devices (phys starting with "inpmap", or the MAC prefix of
  an emulated DualSense Edge as uniq) are never opened as inputs, which
  prevents feedback loops.
"""

from __future__ import annotations

import errno
import logging
import os
import re
import select
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass

from evdev import InputDevice, UInput, ecodes, list_devices
from evdev.uinput import UInputError

from .. import codes
from ..axis_triggers import AxisEvent, AxisRow, normalize
from ..config import MAX_DEVICE_NAME_BYTES
from ..input import InputDeviceLost, InputError
from ..macros import Led
from ..models import AxisThreshold, InputDeviceSpec, InputEvent, KeyAction
from ..routing import DeviceCapabilities, RoutePlan
from .linux_setup import is_own_node, symlinks_by_target

log = logging.getLogger(__name__)

FORWARD_PHYS = "inpmap-forward"
FORWARD_NAME_PREFIX = "InpMap forward: "
LINK_DIRS = ("/dev/input/by-id", "/dev/input/by-path")  # same as linux_setup.LINK_DIRS

_KEY_ACTIONS = {0: KeyAction.RELEASE, 1: KeyAction.PRESS, 2: KeyAction.REPEAT}
_LEDS = {
    ecodes.LED_NUML: Led.NUMLOCK,
    ecodes.LED_CAPSL: Led.CAPSLOCK,
    ecodes.LED_SCROLLL: Led.SCROLLLOCK,
}


# Kernel drivers that report the left/top face buttons positionally.
POSITIONAL_FACE_DRIVERS = frozenset({"playstation", "sony", "nintendo"})
_FACE_LEFT = codes.CODES["BTN_FACE_LEFT"]
_FACE_UP = codes.CODES["BTN_FACE_UP"]
FACE_SWAP = {_FACE_LEFT: _FACE_UP, _FACE_UP: _FACE_LEFT}


def input_driver(path: str, sysfs: str = "/sys/class/input") -> str:
    """Name of the kernel driver behind an event node ("" if unknown)."""
    link = os.path.join(sysfs, os.path.basename(path), "device", "device", "driver")
    target = os.path.realpath(link)
    return os.path.basename(target) if os.path.exists(target) else ""


def face_swap(path: str, sysfs: str = "/sys/class/input") -> Mapping[int, int]:
    """Code translation for a device's face buttons (empty for most devices).

    Its own inverse, so the same mapping translates back.
    """
    return FACE_SWAP if input_driver(path, sysfs) in POSITIONAL_FACE_DRIVERS else {}


def is_own_device(device: InputDevice) -> bool:
    return is_own_node(device.phys or "", device.uniq or "")


def forward_name(name: str) -> str:
    """Name of the forwarding device, cut to the uinput limit."""
    full = (FORWARD_NAME_PREFIX + name).encode("utf-8")[:MAX_DEVICE_NAME_BYTES]
    return full.decode("utf-8", errors="ignore")


def _event_node_sort_key(path: str) -> tuple[str, int]:
    match = re.search(r"(\d+)$", path)
    return (path.rstrip("0123456789"), int(match.group(1)) if match else -1)


def _all_event_nodes() -> list[str]:
    try:
        names = os.listdir("/dev/input")
    except OSError:
        return []
    nodes = [f"/dev/input/{n}" for n in names if n.startswith("event")]
    return sorted(nodes, key=_event_node_sort_key)


@dataclass(frozen=True)
class DeviceInfo:
    """Diagnostic description of a physical input device."""

    path: str
    name: str
    phys: str
    links: tuple[str, ...]
    key_count: int
    gamepad_buttons: int
    own: bool


def list_input_devices() -> tuple[list[DeviceInfo], list[str]]:
    """Return (readable devices, unreadable event nodes)."""
    links = symlinks_by_target(LINK_DIRS)
    readable = set(list_devices(writable=False))
    devices: list[DeviceInfo] = []
    unreadable: list[str] = []
    for path in _all_event_nodes():
        if path not in readable:
            unreadable.append(path)
            continue
        try:
            device = InputDevice(path)
        except OSError:
            unreadable.append(path)
            continue
        try:
            keys = device.capabilities().get(ecodes.EV_KEY, [])
            devices.append(
                DeviceInfo(
                    path=path,
                    name=device.name,
                    phys=device.phys or "",
                    links=tuple(links.get(path, ())),
                    key_count=sum(1 for code in keys if not codes.is_gamepad_button(code)),
                    gamepad_buttons=sum(1 for code in keys if codes.is_gamepad_button(code)),
                    own=is_own_device(device),
                )
            )
        finally:
            device.close()
    return devices, unreadable


def wait_for_key_press(paths: Sequence[str], timeout: float) -> tuple[str | None, list[str]]:
    """Wait until a key or button is pressed on one of ``paths`` (not grabbed).

    Returns (path of that device or None after ``timeout``, paths that could
    not be opened). Events queued before the call are ignored, e.g. the
    release of the Enter key that started the wait.
    """
    devices: list[InputDevice] = []
    failed: list[str] = []
    for path in paths:
        try:
            devices.append(InputDevice(path))
        except OSError:
            failed.append(path)
    try:
        for device in devices:
            _drain(device)
        deadline = time.monotonic() + timeout
        while devices and (remaining := deadline - time.monotonic()) > 0:
            ready, _, _ = select.select(devices, [], [], remaining)
            for device in ready:
                try:
                    events = list(device.read())
                except (BlockingIOError, OSError):
                    continue
                if any(e.type == ecodes.EV_KEY and e.value == 1 for e in events):
                    return device.path, failed
        return None, failed
    finally:
        for device in devices:
            device.close()


def _drain(device: InputDevice) -> None:
    try:
        while device.read_one() is not None:
            pass
    except OSError:
        pass


def monitor_axes(
    inputs: dict[str, InputDeviceSpec],
    thresholds: dict[tuple[str, int], list[tuple[str, AxisThreshold]]],
    show: Callable[[list[AxisRow], set[int]], None],
    timeout: float | None,
) -> list[str]:
    """Show the trigger-capable axes of ``inputs`` live, without grabbing.

    ``show(rows, changed)`` is called first with all rows and then, at most
    20 times a second, with the indices of rows whose value changed. Runs
    until ``timeout`` (or Ctrl+C). Returns notes about inputs that could
    not be shown.
    """
    backend = LinuxInputBackend()
    notes: list[str] = []
    devices: dict[int, tuple[InputDevice, str]] = {}
    rows: list[AxisRow] = []
    index: dict[tuple[str, int], int] = {}
    try:
        for input_id, spec in inputs.items():
            try:
                device = InputDevice(backend.resolve_path(spec))
            except InputError as exc:
                notes.append(str(exc))
                continue
            except OSError as exc:
                notes.append(f"input '{input_id}': cannot open: {exc}")
                continue
            if _grabbed_elsewhere(device):
                notes.append(
                    f"input '{input_id}': {device.name} is grabbed by another program "
                    "(the InpMap service?); stop it to see its values"
                )
                device.close()
                continue
            devices[device.fd] = (device, input_id)
            for code, info in device.capabilities(absinfo=True).get(ecodes.EV_ABS, []):
                if code in codes.TRIGGER_AXIS_NAMES:
                    index[(input_id, code)] = len(rows)
                    rows.append(
                        AxisRow(
                            input_id,
                            code,
                            info.min,
                            info.max,
                            normalize(info.value, info.min, info.max),
                            thresholds.get((input_id, code), []),
                        )
                    )
        if not rows:
            return notes
        show(rows, set(range(len(rows))))
        deadline = None if timeout is None else time.monotonic() + timeout
        changed: set[int] = set()
        last_show = 0.0
        while deadline is None or time.monotonic() < deadline:
            wait = 0.05 if deadline is None else max(0.0, min(0.05, deadline - time.monotonic()))
            ready, _, _ = select.select(list(devices), [], [], wait)
            for fd in ready:
                device, input_id = devices[fd]
                try:
                    events = list(device.read())
                except BlockingIOError:
                    continue
                for event in events:
                    row = index.get((input_id, event.code)) if event.type == ecodes.EV_ABS else None
                    if row is not None:
                        rows[row].value = normalize(
                            event.value, rows[row].minimum, rows[row].maximum
                        )
                        changed.add(row)
            if changed and time.monotonic() - last_show >= 0.05:
                show(rows, changed)
                changed = set()
                last_show = time.monotonic()
        return notes
    finally:
        for device, _ in devices.values():
            device.close()


def listen(
    paths: Sequence[str],
    on_key: Callable[[str, str, int, bool], None],
    on_axis: Callable[[str, str, int, float], None],
    timeout: float | None,
) -> list[str]:
    """Report key presses/releases and normalised axis values of ``paths``.

    Devices are read, not grabbed. Runs until ``timeout`` (or Ctrl+C).
    Returns notes about devices that could not be read.
    """
    notes: list[str] = []
    devices: dict[int, InputDevice] = {}
    swaps: dict[int, Mapping[int, int]] = {}
    ranges: dict[tuple[str, int], tuple[int, int]] = {}
    try:
        for path in paths:
            try:
                device = InputDevice(path)
            except OSError:
                notes.append(f"{path}: cannot be read (see docs/installation.md, permissions)")
                continue
            if _grabbed_elsewhere(device):
                notes.append(
                    f"{device.name}: grabbed by another program (the InpMap service?); "
                    "stop it to detect its keys"
                )
                device.close()
                continue
            devices[device.fd] = device
            swaps[device.fd] = face_swap(path)
            for code, info in device.capabilities(absinfo=True).get(ecodes.EV_ABS, []):
                ranges[(path, code)] = (info.min, info.max)
        deadline = None if timeout is None else time.monotonic() + timeout
        while devices and (deadline is None or time.monotonic() < deadline):
            wait = 0.2 if deadline is None else max(0.0, min(0.2, deadline - time.monotonic()))
            ready, _, _ = select.select(list(devices), [], [], wait)
            for fd in ready:
                device = devices[fd]
                try:
                    events = list(device.read())
                except BlockingIOError:
                    continue
                except OSError:  # unplugged
                    del devices[fd]
                    continue
                swap = swaps[fd]
                for event in events:
                    if event.type == ecodes.EV_KEY and event.value in (0, 1):
                        code = swap.get(event.code, event.code)
                        on_key(device.path, device.name, code, event.value == 1)
                    elif event.type == ecodes.EV_ABS and (device.path, event.code) in ranges:
                        value = normalize(event.value, *ranges[(device.path, event.code)])
                        on_axis(device.path, device.name, event.code, value)
        return notes
    finally:
        for device in devices.values():
            device.close()


def _grabbed_elsewhere(device: InputDevice) -> bool:
    """Whether another program holds an exclusive grab (then no events reach us)."""
    try:
        device.grab()
    except OSError as exc:
        return exc.errno == errno.EBUSY
    device.ungrab()
    return False


@dataclass(frozen=True)
class _SyntheticEvent:
    """Raw event made up during resynchronization (forwardable like evdev's)."""

    type: int
    code: int
    value: int


def _io_error(exc: OSError, description: str, action: str) -> InputError:
    if exc.errno == errno.ENODEV:
        return InputDeviceLost(f"{description} disappeared while {action}")
    return InputError(f"{action} {description} failed: {exc}")


class LinuxInputSource:
    """An opened physical device plus its forwarding device.

    Implements :class:`inpmap.input.InputSource`.
    """

    def __init__(
        self,
        spec: InputDeviceSpec,
        device: InputDevice,
        forwarder: UInput | None = None,
        swap: Mapping[int, int] | None = None,
    ) -> None:
        """``forwarder``: an existing full pass-through device (tests); normally
        :meth:`start_passthrough` creates what the route plan needs. ``swap``:
        face button translation (default: from the device's driver)."""
        self._spec = spec
        self._device = device
        # Device code <-> InpMap code; codes InpMap sees are translated, the
        # pass-through device gets the device's own codes.
        self._swap = face_swap(device.path) if swap is None else swap
        self._forwarder = forwarder  # the pass-through device
        # (type, code) the pass-through device carries; None: everything (`to = own`)
        self._carried: frozenset[tuple[int, int]] | None = None if forwarder else frozenset()
        self._grabbed = False
        self._forwarded_held: set[int] = set()
        # Key state as seen in the event stream we consumed; used to
        # resynchronize after SYN_DROPPED.
        self._down: set[int] = set(map(self._code, self._query_keys_or_empty()))
        self._dropping = False
        self._led_warning_logged = False
        self._masked: set[int] = set()
        capabilities = device.capabilities(absinfo=True)
        self._key_codes = frozenset(map(self._code, capabilities.get(ecodes.EV_KEY, [])))
        self._absinfo = dict(capabilities.get(ecodes.EV_ABS, []))
        self._axis_ranges = {code: (info.min, info.max) for code, info in self._absinfo.items()}
        self._relative = frozenset(capabilities.get(ecodes.EV_REL, []))

    def _code(self, code: int) -> int:
        """Translate a key code between the device and InpMap (both ways)."""
        return self._swap.get(code, code)

    def _query_keys_or_empty(self) -> list[int]:
        try:
            return list(self._device.active_keys())
        except OSError:
            return []

    @property
    def spec(self) -> InputDeviceSpec:
        return self._spec

    @property
    def description(self) -> str:
        return f"'{self._device.name}' ({self._device.path})"

    def fileno(self) -> int:
        return self._device.fd

    def capabilities(self) -> DeviceCapabilities:
        return DeviceCapabilities(self._key_codes, dict(self._axis_ranges), self._relative)

    def start_passthrough(self, plan: RoutePlan) -> None:
        """Create the pass-through device the route plan needs, if any."""
        if not plan.needs_passthrough:
            return
        info = self._device.info
        identity = dict(
            name=forward_name(self._device.name),
            vendor=info.vendor,
            product=info.product,
            version=info.version,
            bustype=info.bustype,
            phys=FORWARD_PHYS,
            # Rumble is not passed through; with effects enabled, games
            # would block up to 30 s on unanswered uploads (see linux.py).
            max_effects=0,
        )
        try:
            if plan.own:
                self._forwarder = UInput.from_device(
                    self._device,
                    filtered_types=(ecodes.EV_SYN, ecodes.EV_FF, ecodes.EV_REP),
                    **identity,
                )
                self._carried = None
                return
            events: dict[int, list] = {}
            if plan.passthrough_keys:
                events[ecodes.EV_KEY] = sorted(map(self._code, plan.passthrough_keys))
            if plan.passthrough_relative:
                events[ecodes.EV_REL] = sorted(plan.passthrough_relative)
            if plan.passthrough_axes:
                events[ecodes.EV_ABS] = [
                    (c, self._absinfo[c]) for c in sorted(plan.passthrough_axes)
                ]
            self._forwarder = UInput(events, **identity)
        except (UInputError, OSError) as exc:
            raise InputError(
                f"input '{self._spec.id}': cannot create the pass-through device for "
                f"'{self._device.name}': {exc}"
            ) from exc
        self._carried = frozenset(
            (etype, code) for etype, codes_ in events.items() for code in codes_
        )

    def feedback_fileno(self) -> int | None:
        """Descriptor on which the desktop's writes to the pass-through device arrive."""
        return self._forwarder.fd if self._forwarder is not None else None

    def pump_feedback(self) -> None:
        """Apply LED changes the desktop made on the forwarder to the device.

        The desktop sees the forwarder as the keyboard, so Caps/Num/Scroll
        Lock state lands there; without this the physical LEDs would freeze.
        """
        if self._forwarder is None:
            return
        try:
            events = list(self._forwarder.read())
        except BlockingIOError:
            return
        except OSError as exc:
            log.warning("reading feedback for %s failed: %s", self.description, exc)
            return
        for event in events:
            if event.type != ecodes.EV_LED:
                continue
            try:
                self._device.set_led(event.code, event.value)
            except OSError as exc:
                if not self._led_warning_logged:
                    log.warning("cannot set LEDs on %s: %s", self.description, exc)
                    self._led_warning_logged = True

    def set_leds(self, leds: frozenset[Led]) -> None:
        available = self._device.capabilities().get(ecodes.EV_LED, [])
        for code, led in _LEDS.items():
            if code not in available:
                continue
            try:
                self._device.set_led(code, 1 if led in leds else 0)
            except OSError as exc:
                if not self._led_warning_logged:
                    log.warning("cannot set LEDs on %s: %s", self.description, exc)
                    self._led_warning_logged = True
                return

    def leds(self) -> frozenset[Led]:
        try:
            lit = self._device.leds()
        except OSError as exc:
            log.debug("reading LEDs of %s failed: %s", self.description, exc)
            return frozenset()
        return frozenset(_LEDS[code] for code in lit if code in _LEDS)

    def key_codes(self) -> frozenset[int]:
        return self._key_codes

    def held_codes(self) -> frozenset[int]:
        try:
            return frozenset(map(self._code, self._device.active_keys()))
        except OSError as exc:
            raise _io_error(exc, self.description, "querying") from exc

    def grab(self) -> None:
        try:
            self._device.grab()
        except OSError as exc:
            if exc.errno == errno.EBUSY:
                raise InputError(
                    f"{self.description} is already grabbed by another program "
                    "(e.g. the InpMap service: systemctl --user stop inpmap 'inpmap@*', "
                    "or another remapper such as input-remapper); stop it first"
                ) from exc
            raise _io_error(exc, self.description, "grabbing") from exc
        self._grabbed = True

    def axis_ranges(self) -> dict[int, tuple[int, int]]:
        return dict(self._axis_ranges)

    def read(self) -> list[tuple[InputEvent | AxisEvent | None, object]]:
        try:
            raw_events = list(self._device.read())
        except BlockingIOError:
            return []
        except OSError as exc:
            raise _io_error(exc, self.description, "reading") from exc
        result: list[tuple[InputEvent | AxisEvent | None, object]] = []
        for raw in raw_events:
            if raw.type == ecodes.EV_SYN and raw.code == ecodes.SYN_DROPPED:
                # Kernel buffer overflow: events were lost. Per the evdev
                # protocol, ignore everything up to and including the next
                # SYN_REPORT, then query the device state.
                log.warning("events dropped by the kernel on %s; resynchronizing", self.description)
                self._dropping = True
            elif self._dropping:
                if raw.type == ecodes.EV_SYN and raw.code == ecodes.SYN_REPORT:
                    self._dropping = False
                    result += self._resync()
            elif raw.type == ecodes.EV_KEY and raw.value in _KEY_ACTIONS:
                code = self._code(raw.code)
                self._track(code, raw.value)
                event = InputEvent(self._spec.id, code, _KEY_ACTIONS[raw.value])
                result.append((event, raw))
            elif raw.type == ecodes.EV_ABS and raw.code in self._axis_ranges:
                value = normalize(raw.value, *self._axis_ranges[raw.code])
                result.append((AxisEvent(self._spec.id, raw.code, value), raw))
            else:
                result.append((None, raw))
        return result

    def _track(self, code: int, value: int) -> None:
        if value == 1:
            self._down.add(code)
        elif value == 0:
            self._down.discard(code)

    def _resync(self) -> list[tuple[InputEvent | None, object]]:
        """Synthesize key events for state changes hidden by dropped events.

        Only key state is resynchronized; absolute axes of forwarded devices
        are not (they are refreshed by the next movement).
        """
        try:
            current = set(map(self._code, self._device.active_keys()))
        except OSError as exc:
            raise _io_error(exc, self.description, "resynchronizing") from exc
        result: list[tuple[InputEvent | None, object]] = []
        for code in sorted(self._down - current):
            result.append(self._synthetic_key(code, 0))
        for code in sorted(current - self._down):
            result.append(self._synthetic_key(code, 1))
        if result:
            result.append((None, _SyntheticEvent(ecodes.EV_SYN, ecodes.SYN_REPORT, 0)))
            log.info("resynchronized %d key(s) on %s", len(result) - 1, self.description)
        return result

    def _synthetic_key(self, code: int, value: int) -> tuple[InputEvent, object]:
        self._track(code, value)
        event = InputEvent(self._spec.id, code, _KEY_ACTIONS[value])
        return event, _SyntheticEvent(ecodes.EV_KEY, self._code(code), value)

    def forward(self, raw: object) -> None:
        """Re-emit an event on the pass-through device; dropped if it does not carry it."""
        if self._forwarder is None:
            return
        etype, code, value = raw.type, raw.code, raw.value  # type: ignore[attr-defined]
        if (
            self._carried is not None
            and etype != ecodes.EV_SYN
            and (etype, code) not in self._carried
        ):
            return
        if etype == ecodes.EV_KEY and self._code(code) in self._masked:
            return  # hidden while a mapping with modifiers runs
        if etype == ecodes.EV_KEY and value != 1 and code not in self._forwarded_held:
            return  # release/repeat of a key the desktop does not have down
        try:
            self._forwarder.write(etype, code, value)
        except OSError as exc:
            raise InputError(f"forwarding event from {self.description} failed: {exc}") from exc
        if etype == ecodes.EV_KEY:
            if value == 0:
                self._forwarded_held.discard(code)
            elif value == 1:
                self._forwarded_held.add(code)

    def mask(self, code: int) -> None:
        if code in self._masked:
            return
        self._masked.add(code)
        if self._code(code) in self._forwarded_held:
            self._write_key(self._code(code), 0)

    def unmask(self, code: int) -> None:
        if code not in self._masked:
            return
        self._masked.discard(code)
        if code in self._down and self._code(code) not in self._forwarded_held:
            self._write_key(self._code(code), 1)

    def _write_key(self, code: int, value: int) -> None:
        if self._forwarder is None:
            return
        try:
            self._forwarder.write(ecodes.EV_KEY, code, value)
            self._forwarder.syn()
        except OSError as exc:
            raise InputError(f"forwarding event from {self.description} failed: {exc}") from exc
        if value:
            self._forwarded_held.add(code)
        else:
            self._forwarded_held.discard(code)

    def close(self) -> None:
        errors: list[str] = []
        if self._grabbed:
            try:
                self._device.ungrab()
            except OSError as exc:
                if exc.errno != errno.ENODEV:  # a vanished device is not grabbed anymore
                    errors.append(f"ungrab: {exc}")
            self._grabbed = False
        try:
            if self._forwarder is not None and self._forwarded_held:
                for code in sorted(self._forwarded_held):
                    self._forwarder.write(ecodes.EV_KEY, code, 0)
                self._forwarder.syn()
        except OSError as exc:
            errors.append(f"releasing forwarded keys: {exc}")
        self._forwarded_held.clear()
        closers = [("device", self._device.close)]
        if self._forwarder is not None:
            closers.insert(0, ("pass-through device", self._forwarder.close))
        for name, closer in closers:
            try:
                closer()
            except OSError as exc:
                errors.append(f"closing {name}: {exc}")
        if errors:
            raise InputError(f"cleanup of {self.description}: " + "; ".join(errors))


class LinuxInputBackend:
    """Implements :class:`inpmap.input.InputBackend` with evdev."""

    def open(self, spec: InputDeviceSpec, mapped_codes: frozenset[int]) -> LinuxInputSource:
        path = self.resolve_path(spec)
        try:
            device = InputDevice(path)
        except PermissionError as exc:
            raise InputError(
                f"input '{spec.id}': no read access to {path}. The user needs read access "
                "to /dev/input/event* (see docs/installation.md, 'Device permissions')"
            ) from exc
        except OSError as exc:
            raise InputError(f"input '{spec.id}': cannot open {path}: {exc}") from exc
        try:
            return self._prepare(spec, device, mapped_codes)
        except BaseException:
            device.close()
            raise

    def wait(
        self, sources: Sequence[LinuxInputSource], timeout: float, feedback: Sequence[int] = ()
    ) -> list[LinuxInputSource]:
        if not sources and not feedback:
            # All inputs absent (e.g. unplugged): sleep instead of spinning.
            time.sleep(timeout)
            return []
        inputs = {source.fileno(): source for source in sources}
        own_feedback = {
            fd: source for source in sources if (fd := source.feedback_fileno()) is not None
        }
        ready, _, _ = select.select([*inputs, *own_feedback, *feedback], [], [], timeout)
        for fd in ready:
            if fd in own_feedback:
                own_feedback[fd].pump_feedback()
        return [inputs[fd] for fd in ready if fd in inputs]

    def _prepare(
        self, spec: InputDeviceSpec, device: InputDevice, mapped_codes: frozenset[int]
    ) -> LinuxInputSource:
        if is_own_device(device):
            raise InputError(
                f"input '{spec.id}': {device.path} is one of InpMap's own virtual devices"
            )
        swap = face_swap(device.path)
        keys = {swap.get(code, code) for code in device.capabilities().get(ecodes.EV_KEY, [])}
        missing = sorted(mapped_codes - keys)
        if missing:
            names = ", ".join(codes.code_name(code) for code in missing)
            raise InputError(
                f"input '{spec.id}': '{device.name}' ({device.path}) does not report {names}"
            )
        return LinuxInputSource(spec, device, swap=swap)

    def resolve_path(self, spec: InputDeviceSpec) -> str:
        """The event node a selector refers to (InputError if missing or ambiguous)."""
        if spec.path is not None:
            real = os.path.realpath(spec.path)
            if not os.path.exists(real):
                raise InputError(f"input '{spec.id}': {spec.path} does not exist")
            return real
        matches: list[str] = []
        for path in list_devices(writable=False):
            try:
                device = InputDevice(path)
            except OSError:
                continue
            try:
                if device.name == spec.name and not is_own_device(device):
                    matches.append(path)
            finally:
                device.close()
        if not matches:
            raise InputError(
                f"input '{spec.id}': no readable device named '{spec.name}' "
                "(run 'inpmap devices' to list devices)"
            )
        if len(matches) > 1:
            raise InputError(
                f"input '{spec.id}': {len(matches)} devices are named '{spec.name}' "
                f"({', '.join(sorted(matches, key=_event_node_sort_key))}); select one with "
                "'path', e.g. a /dev/input/by-id link shown by 'inpmap devices'"
            )
        return matches[0]

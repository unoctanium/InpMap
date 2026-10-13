"""Linux backend: physical input devices via evdev, EVIOCGRAB and forwarding.

Reading an evdev node does not stop other programs from receiving its events.
Suppression therefore uses ``EVIOCGRAB``: while grabbed, the kernel delivers
the device's events only to us, so the desktop sees nothing from it. Every
event the engine does not consume is re-emitted on a *forwarding* uinput
device that mirrors the physical device's capabilities and identity.

Notes:
* ``EV_REP`` is not copied to the forwarding device, otherwise the kernel
  would generate a second, synthetic key repeat on top of forwarded repeats.
* Keyboard LED state (Caps/Num/Scroll Lock) is set by the desktop on the
  forwarding device; it is read back from the uinput descriptor and applied
  to the physical device.
* Force feedback (rumble) is not passed through; forwarders have no EV_FF.
* Our own virtual devices (phys starting with "inpmap") are never opened as
  inputs, which prevents feedback loops.
"""

from __future__ import annotations

import errno
import logging
import os
import re
import select
import time
from collections.abc import Sequence
from dataclasses import dataclass

from evdev import InputDevice, UInput, ecodes, list_devices
from evdev.uinput import UInputError

from .. import codes
from ..config import MAX_DEVICE_NAME_BYTES
from ..input import InputDeviceLost, InputError
from ..models import InputDeviceSpec, InputEvent, KeyAction

log = logging.getLogger(__name__)

OWN_PHYS_PREFIX = "inpmap"  # output devices use "inpmap", forwarders "inpmap-forward"
FORWARD_PHYS = "inpmap-forward"
FORWARD_NAME_PREFIX = "InpMap forward: "
LINK_DIRS = ("/dev/input/by-id", "/dev/input/by-path")

_KEY_ACTIONS = {0: KeyAction.RELEASE, 1: KeyAction.PRESS, 2: KeyAction.REPEAT}


def is_own_device(device: InputDevice) -> bool:
    return (device.phys or "").startswith(OWN_PHYS_PREFIX)


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


def _symlinks_by_target() -> dict[str, list[str]]:
    links: dict[str, list[str]] = {}
    for directory in LINK_DIRS:
        try:
            entries = sorted(os.scandir(directory), key=lambda e: e.name)
        except OSError:
            continue
        for entry in entries:
            if entry.is_symlink():
                links.setdefault(os.path.realpath(entry.path), []).append(entry.path)
    return links


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
    links = _symlinks_by_target()
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

    def __init__(self, spec: InputDeviceSpec, device: InputDevice, forwarder: UInput) -> None:
        self._spec = spec
        self._device = device
        self._forwarder = forwarder
        self._grabbed = False
        self._forwarded_held: set[int] = set()
        # Key state as seen in the event stream we consumed; used to
        # resynchronize after SYN_DROPPED.
        self._down: set[int] = set(self._query_keys_or_empty())
        self._dropping = False
        self._led_warning_logged = False

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

    def feedback_fileno(self) -> int:
        """Descriptor on which the desktop's writes to the forwarder arrive."""
        return self._forwarder.fd

    def pump_feedback(self) -> None:
        """Apply LED changes the desktop made on the forwarder to the device.

        The desktop sees the forwarder as the keyboard, so Caps/Num/Scroll
        Lock state lands there; without this the physical LEDs would freeze.
        """
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

    def held_codes(self) -> frozenset[int]:
        try:
            return frozenset(self._device.active_keys())
        except OSError as exc:
            raise _io_error(exc, self.description, "querying") from exc

    def grab(self) -> None:
        try:
            self._device.grab()
        except OSError as exc:
            if exc.errno == errno.EBUSY:
                raise InputError(
                    f"{self.description} is already grabbed by another program "
                    "(e.g. another remapper such as input-remapper); stop it first"
                ) from exc
            raise _io_error(exc, self.description, "grabbing") from exc
        self._grabbed = True

    def read(self) -> list[tuple[InputEvent | None, object]]:
        try:
            raw_events = list(self._device.read())
        except BlockingIOError:
            return []
        except OSError as exc:
            raise _io_error(exc, self.description, "reading") from exc
        result: list[tuple[InputEvent | None, object]] = []
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
                self._track(raw.code, raw.value)
                event = InputEvent(self._spec.id, raw.code, _KEY_ACTIONS[raw.value])
                result.append((event, raw))
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
            current = set(self._device.active_keys())
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
        return event, _SyntheticEvent(ecodes.EV_KEY, code, value)

    def forward(self, raw: object) -> None:
        etype, code, value = raw.type, raw.code, raw.value  # type: ignore[attr-defined]
        try:
            self._forwarder.write(etype, code, value)
        except OSError as exc:
            raise InputError(f"forwarding event from {self.description} failed: {exc}") from exc
        if etype == ecodes.EV_KEY:
            if value == 0:
                self._forwarded_held.discard(code)
            elif value == 1:
                self._forwarded_held.add(code)

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
            for code in sorted(self._forwarded_held):
                self._forwarder.write(ecodes.EV_KEY, code, 0)
            if self._forwarded_held:
                self._forwarder.syn()
        except OSError as exc:
            errors.append(f"releasing forwarded keys: {exc}")
        self._forwarded_held.clear()
        for name, closer in (("forwarder", self._forwarder.close), ("device", self._device.close)):
            try:
                closer()
            except OSError as exc:
                errors.append(f"closing {name}: {exc}")
        if errors:
            raise InputError(f"cleanup of {self.description}: " + "; ".join(errors))


class LinuxInputBackend:
    """Implements :class:`inpmap.input.InputBackend` with evdev."""

    def open(self, spec: InputDeviceSpec, mapped_codes: frozenset[int]) -> LinuxInputSource:
        path = self._resolve(spec)
        try:
            device = InputDevice(path)
        except PermissionError as exc:
            raise InputError(
                f"input '{spec.id}': no read access to {path}. The user needs read access "
                "to /dev/input/event* (usually membership in the 'input' group; see README)"
            ) from exc
        except OSError as exc:
            raise InputError(f"input '{spec.id}': cannot open {path}: {exc}") from exc
        try:
            return self._prepare(spec, device, mapped_codes)
        except BaseException:
            device.close()
            raise

    def wait(self, sources: Sequence[LinuxInputSource], timeout: float) -> list[LinuxInputSource]:
        if not sources:
            # All inputs absent (e.g. unplugged): sleep instead of spinning.
            time.sleep(timeout)
            return []
        inputs = {source.fileno(): source for source in sources}
        feedback = {source.feedback_fileno(): source for source in sources}
        ready, _, _ = select.select([*inputs, *feedback], [], [], timeout)
        for fd in ready:
            if fd in feedback:
                feedback[fd].pump_feedback()
        return [inputs[fd] for fd in ready if fd in inputs]

    def _prepare(
        self, spec: InputDeviceSpec, device: InputDevice, mapped_codes: frozenset[int]
    ) -> LinuxInputSource:
        if is_own_device(device):
            raise InputError(
                f"input '{spec.id}': {device.path} is one of InpMap's own virtual devices"
            )
        keys = set(device.capabilities().get(ecodes.EV_KEY, []))
        missing = sorted(mapped_codes - keys)
        if missing:
            names = ", ".join(codes.code_name(code) for code in missing)
            raise InputError(
                f"input '{spec.id}': '{device.name}' ({device.path}) does not report {names}"
            )
        info = device.info
        try:
            forwarder = UInput.from_device(
                device,
                filtered_types=(ecodes.EV_SYN, ecodes.EV_FF, ecodes.EV_REP),
                name=forward_name(device.name),
                vendor=info.vendor,
                product=info.product,
                version=info.version,
                bustype=info.bustype,
                phys=FORWARD_PHYS,
                # Rumble is not passed through; with effects enabled, games
                # would block up to 30 s on unanswered uploads (see linux.py).
                max_effects=0,
            )
        except (UInputError, OSError) as exc:
            raise InputError(
                f"input '{spec.id}': cannot create forwarding device for '{device.name}': {exc}"
            ) from exc
        return LinuxInputSource(spec, device, forwarder)

    def _resolve(self, spec: InputDeviceSpec) -> str:
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

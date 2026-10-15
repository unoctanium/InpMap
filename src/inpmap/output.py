"""Virtual output devices: backend interface and output manager.

The manager owns the lifetime of all virtual output devices and records which
codes are currently held on each one. Its guarantee: whatever happens, closing
the manager releases every held code before the devices are destroyed.

Reference counting of overlapping mappings is *not* done here; that is the
state manager's job. The manager only sees "this code goes down / up" and
ignores redundant transitions.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol

from . import codes
from .macros import AXIS_REST, OUTPUT_AXIS_KINDS, AxisKind, Led
from .models import Config, OutputDeviceSpec, OutputKind

log = logging.getLogger(__name__)


class OutputError(Exception):
    """A virtual output device could not be created, written or closed."""


@dataclass(frozen=True)
class OutputCapabilities:
    """What a virtual output device carries (docs/configuration.md §3.3)."""

    keys: frozenset[int]
    axes: Mapping[int, AxisKind]


def output_capabilities(kind: OutputKind, mapped_codes: frozenset[int]) -> OutputCapabilities:
    """The fixed set of an output of ``kind`` plus the codes mappings send to it.

    The set does not depend on any input device, so an output stays the same
    when a device is missing at start or reconnects.
    """
    if kind is OutputKind.KEYBOARD:
        return OutputCapabilities(codes.KEYBOARD_OUTPUT_KEYS | mapped_codes, {})
    if kind is OutputKind.GAMEPAD:
        return OutputCapabilities(codes.GAMEPAD_OUTPUT_BUTTONS | mapped_codes, OUTPUT_AXIS_KINDS)
    raise ValueError(f"unsupported output kind: {kind}")


class OutputDevice(Protocol):
    """One created virtual device. Implementations raise OutputError."""

    def set_key(self, code: int, pressed: bool) -> None:
        """Emit a press or release of an EV_KEY code and synchronize."""
        ...

    def set_axis(self, code: int, value: float) -> None:
        """Set an axis to a fraction of its range (sticks and D-pad -1..1, triggers 0..1)."""
        ...

    def close(self) -> None:
        """Destroy the virtual device."""
        ...

    def fileno(self) -> int | None:
        """Descriptor that becomes readable when the desktop sets LEDs, if any."""
        ...

    def poll_leds(self) -> frozenset[Led] | None:
        """Lock LEDs the desktop has set on a keyboard output, if they changed.

        Non-blocking; None if nothing changed (or the device has no LEDs).
        """
        ...


class OutputBackend(Protocol):
    """Creates virtual devices for one platform."""

    def create(self, spec: OutputDeviceSpec, key_codes: frozenset[int]) -> OutputDevice:
        """Create a device able to emit at least ``key_codes``."""
        ...


class OutputManager:
    """Creates, drives and cleanly destroys the configured output devices."""

    def __init__(self, backend: OutputBackend, config: Config) -> None:
        self._backend = backend
        self._config = config
        self._devices: dict[str, OutputDevice] = {}
        self._held: dict[str, set[int]] = {}
        self._axes: dict[str, dict[int, float]] = {}  # axes not at rest

    @property
    def devices(self) -> Mapping[str, OutputDevice]:
        return dict(self._devices)

    def open(self) -> None:
        """Create all output devices; on failure, destroy those already created."""
        if self._devices:
            raise RuntimeError("output devices are already open")
        for device_id, spec in self._config.outputs.items():
            try:
                carried = output_capabilities(spec.kind, self._config.output_codes(device_id))
                device = self._backend.create(spec, carried.keys)
            except BaseException:
                # Cleanup boundary: also covers KeyboardInterrupt and
                # unexpected backend errors; always re-raised.
                log.error("creating output device '%s' failed; closing the others", device_id)
                self._close_devices()
                raise
            self._devices[device_id] = device
            self._held[device_id] = set()
            self._axes[device_id] = {}
            log.info("created output device '%s' (%s)", device_id, spec.name)

    def press(self, device_id: str, code: int) -> None:
        self._set(device_id, code, True)

    def release(self, device_id: str, code: int) -> None:
        self._set(device_id, code, False)

    def held(self, device_id: str) -> frozenset[int]:
        """Codes currently held on a device."""
        return frozenset(self._held.get(device_id, ()))

    def set_axis(self, device_id: str, code: int, value: float) -> None:
        """Set an axis (fraction of its range); unchanged values are skipped."""
        device = self._devices.get(device_id)
        if device is None:
            raise OutputError(f"output device '{device_id}' is not open")
        axes = self._axes[device_id]
        if axes.get(code, AXIS_REST) == value:
            return
        device.set_axis(code, value)
        if value == AXIS_REST:
            axes.pop(code, None)
        else:
            axes[code] = value

    def feedback_filenos(self) -> list[int]:
        """Descriptors on which LED changes of the outputs arrive."""
        return [fd for d in self._devices.values() if (fd := d.fileno()) is not None]

    def poll_leds(self) -> dict[str, frozenset[Led]]:
        """Lock LEDs per output whose state the desktop changed since the last call."""
        changed = {}
        for device_id, device in self._devices.items():
            leds = device.poll_leds()
            if leds is not None:
                changed[device_id] = leds
        return changed

    def axis(self, device_id: str, code: int) -> float:
        """Current value of an axis (rest if never moved)."""
        return self._axes.get(device_id, {}).get(code, AXIS_REST)

    def release_all(self) -> None:
        """Release every held code and return every moved axis to rest.

        Tries all devices even if some fail, then raises OutputError naming
        the failures.
        """
        failures: list[str] = []
        for device_id, axes in self._axes.items():
            for code in sorted(axes):
                try:
                    self._devices[device_id].set_axis(code, AXIS_REST)
                except OutputError as exc:
                    failures.append(f"{device_id} axis {code:#x}: {exc}")
                    log.error("resetting axis %#x on '%s' failed: %s", code, device_id, exc)
            axes.clear()
        for device_id, held in self._held.items():
            for code in sorted(held):
                try:
                    self._devices[device_id].set_key(code, False)
                except OutputError as exc:
                    failures.append(f"{device_id} {codes.code_name(code)}: {exc}")
                    log.error(
                        "releasing %s on '%s' failed: %s", codes.code_name(code), device_id, exc
                    )
            # Even on failure, forget the code: retrying a device that just
            # failed is pointless, and close() destroys it next.
            held.clear()
        if failures:
            raise OutputError("failed to release: " + "; ".join(failures))

    def close(self) -> None:
        """Release all held codes, then destroy all devices.

        Always attempts every step; raises OutputError afterwards if any
        step failed.
        """
        errors: list[str] = []
        try:
            self.release_all()
        except OutputError as exc:
            errors.append(str(exc))
        errors += self._close_devices()
        if errors:
            raise OutputError("; ".join(errors))

    def __enter__(self) -> OutputManager:
        self.open()
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def _set(self, device_id: str, code: int, pressed: bool) -> None:
        device = self._devices.get(device_id)
        if device is None:
            raise OutputError(f"output device '{device_id}' is not open")
        held = self._held[device_id]
        if (code in held) == pressed:
            log.debug(
                "ignoring redundant %s of %s on '%s'",
                "press" if pressed else "release",
                codes.code_name(code),
                device_id,
            )
            return
        device.set_key(code, pressed)
        # Only record the new state once the device accepted it.
        if pressed:
            held.add(code)
        else:
            held.discard(code)

    def _close_devices(self) -> list[str]:
        errors: list[str] = []
        for device_id, device in self._devices.items():
            try:
                device.close()
                log.info("closed output device '%s'", device_id)
            except OutputError as exc:
                errors.append(f"closing '{device_id}': {exc}")
                log.error("closing output device '%s' failed: %s", device_id, exc)
        self._devices.clear()
        self._held.clear()
        self._axes.clear()
        return errors

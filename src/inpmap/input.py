"""Physical input devices: backend interface.

A backend opens the configured physical devices as :class:`InputSource`
objects. Each source yields pairs of (normalized key event or None, raw
event). The engine only sees the normalized event; what no mapping consumes
goes to the outputs (:mod:`inpmap.routing`), and what no output carries is
handed back to the source unchanged via :meth:`InputSource.forward`, for its
pass-through device. Raw events are opaque to the core.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING, Protocol

from .axis_triggers import AxisEvent
from .macros import Led
from .models import InputDeviceSpec, InputEvent

if TYPE_CHECKING:  # routing imports this module
    from .routing import DeviceCapabilities, RoutePlan


class InputError(Exception):
    """A physical input device could not be found, opened, grabbed or read."""


class InputDeviceLost(InputError):
    """A physical input device disappeared while in use."""


class InputSource(Protocol):
    """One opened physical input device and its pass-through device."""

    @property
    def spec(self) -> InputDeviceSpec: ...

    @property
    def description(self) -> str:
        """Human-readable identification for logs (name and node)."""
        ...

    def held_codes(self) -> frozenset[int]:
        """Keys/buttons currently held down on the physical device."""
        ...

    def key_codes(self) -> frozenset[int]:
        """All keys/buttons the device can report."""
        ...

    def axis_ranges(self) -> dict[int, tuple[int, int]]:
        """(minimum, maximum) of each absolute axis the device reports."""
        ...

    def capabilities(self) -> DeviceCapabilities:
        """Everything the device reports, for :func:`inpmap.routing.plan_route`."""
        ...

    def start_passthrough(self, plan: RoutePlan) -> None:
        """Create the pass-through device the plan needs (none, partial, or a full copy)."""
        ...

    def leds(self) -> frozenset[Led]:
        """Lock LEDs currently lit on the device (empty if it has none)."""
        ...

    def set_leds(self, leds: frozenset[Led]) -> None:
        """Show these lock LEDs on the device and switch the others off (if it has LEDs)."""
        ...

    def grab(self) -> None:
        """Take exclusive access: other programs stop receiving its events."""
        ...

    def read(self) -> list[tuple[InputEvent | AxisEvent | None, object]]:
        """Read pending events without blocking.

        Returns (normalized key event, normalized axis value (AxisEvent) or
        None, raw event) pairs. Raises InputDeviceLost if the device
        disappeared.
        """
        ...

    def forward(self, raw: object) -> None:
        """Pass a raw event to the desktop on the pass-through device.

        Events the pass-through device does not carry are dropped.
        """
        ...

    def mask(self, code: int) -> None:
        """Hide a passed-through key from the desktop for now.

        If the key is currently down on the forwarding device, release it
        there; until :meth:`unmask`, its physical events are not forwarded.
        """
        ...

    def unmask(self, code: int) -> None:
        """Stop hiding a key; press it again if it is still physically held."""
        ...

    def close(self) -> None:
        """Release forwarded keys, ungrab, and free all resources.

        Must attempt every step; raises InputError afterwards if any failed.
        """
        ...


class InputBackend(Protocol):
    def open(self, spec: InputDeviceSpec, mapped_codes: frozenset[int]) -> InputSource:
        """Find and open a device (not grabbed yet).

        Raises InputError if the device is missing, ambiguous, inaccessible,
        or cannot report every code in ``mapped_codes``.
        """
        ...

    def wait(
        self, sources: Sequence[InputSource], timeout: float, feedback: Sequence[int] = ()
    ) -> list[InputSource]:
        """Block up to ``timeout`` seconds; return sources with pending events.

        Also returns early when one of the ``feedback`` descriptors (LED
        changes on the outputs) becomes readable.
        """
        ...

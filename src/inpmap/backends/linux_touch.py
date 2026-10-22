"""Linux backend: the fingers of a multi-touch touchpad as touch events.

Linux reports touchpads with the multi-touch protocol B
(Documentation/input/multi-touch-protocol.rst): each finger has a slot,
``ABS_MT_SLOT`` selects the slot the following values belong to,
``ABS_MT_TRACKING_ID`` >= 0 puts a finger down and -1 lifts it,
``ABS_MT_POSITION_X``/``_Y`` move it, and ``SYN_REPORT`` ends a frame.
:class:`TouchDecoder` turns that into one :class:`TouchEvent` per changed
frame. Pressure, contact size and the single-finger copy in ``ABS_X``/``ABS_Y``
are not used.

Kept free of evdev objects so that it can be tested with plain numbers.
"""

from __future__ import annotations

import itertools
from collections.abc import Mapping
from dataclasses import dataclass

from ..models import TouchContact, TouchEvent

ABS_MT_SLOT = 0x2F
ABS_MT_POSITION_X = 0x35
ABS_MT_POSITION_Y = 0x36
ABS_MT_TRACKING_ID = 0x39
MULTITOUCH_AXES = frozenset(range(0x2F, 0x3E))  # ABS_MT_SLOT .. ABS_MT_TOOL_Y


@dataclass
class _Finger:
    tracking_id: int = -1  # -1: no finger in this slot
    x: int = 0
    y: int = 0
    order: int = 0  # when it touched, for the order of the contacts


class TouchDecoder:
    """Follows the slots of one touchpad.

    ``ranges`` are the device's axis ranges (needs ``ABS_MT_POSITION_X`` and
    ``_Y``); ``slot`` is the slot selected when the device was opened.
    """

    def __init__(
        self, device_id: str, ranges: Mapping[int, tuple[int, int]], slot: int = 0
    ) -> None:
        self._device = device_id
        self._x_range = ranges[ABS_MT_POSITION_X]
        self._y_range = ranges[ABS_MT_POSITION_Y]
        self._slot = slot
        self._fingers: dict[int, _Finger] = {}
        self._order = itertools.count()
        self._changed = False

    @staticmethod
    def handles(code: int) -> bool:
        """Whether an EV_ABS code belongs to the touches (all ABS_MT_* codes)."""
        return code in MULTITOUCH_AXES

    def axis(self, code: int, value: int) -> None:
        """Take one ABS_MT_* value."""
        if code == ABS_MT_SLOT:
            self._slot = value
            return
        finger = self._fingers.setdefault(self._slot, _Finger())
        if code == ABS_MT_TRACKING_ID:
            if value >= 0 and finger.tracking_id < 0:
                finger.order = next(self._order)
            self._changed |= (value >= 0) != (finger.tracking_id >= 0)
            finger.tracking_id = value
        elif code == ABS_MT_POSITION_X:
            finger.x = value
            self._changed |= finger.tracking_id >= 0
        elif code == ABS_MT_POSITION_Y:
            finger.y = value
            self._changed |= finger.tracking_id >= 0

    def frame(self) -> TouchEvent | None:
        """At SYN_REPORT: the fingers now down, if anything changed."""
        if not self._changed:
            return None
        self._changed = False
        down = sorted(
            ((slot, f) for slot, f in self._fingers.items() if f.tracking_id >= 0),
            key=lambda item: item[1].order,
        )
        return TouchEvent(
            self._device,
            tuple(
                TouchContact(slot, _fraction(f.x, *self._x_range), _fraction(f.y, *self._y_range))
                for slot, f in down
            ),
        )

    def reset(self) -> TouchEvent | None:
        """Forget every finger (after the kernel dropped events).

        Returns an event without fingers if any was down. A finger that
        stays on the surface is ignored until it is lifted and put down
        again: its slot can only be told apart from a stale one by a new
        tracking ID.
        """
        was_down = any(f.tracking_id >= 0 for f in self._fingers.values())
        self._fingers.clear()
        self._changed = False
        return TouchEvent(self._device, ()) if was_down else None


def _fraction(value: int, low: int, high: int) -> float:
    if high <= low:
        return 0.0
    return max(0.0, min(1.0, (value - low) / (high - low)))

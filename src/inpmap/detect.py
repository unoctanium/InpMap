"""`inpmap detect`: show presses as they would be written as triggers.

Backend-independent: the Linux backend reports raw key events and
normalised axis values; this module decides what a line says. Pressing a
key prints e.g. ``kbd.KEY_F7 modifiers(ctrl)``; an axis prints one line
each time it passes the middle of its range (``pad.ABS_RZ above 0.5``,
``pad.ABS_HAT0Y below -0.5``).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from . import codes
from .axis_triggers import HYSTERESIS
from .models import MODIFIER_KEYS, Modifier

THRESHOLD = 0.5
DPAD = {("ABS_HAT0Y", -1): "D-pad up", ("ABS_HAT0Y", 1): "D-pad down",
        ("ABS_HAT0X", -1): "D-pad left", ("ABS_HAT0X", 1): "D-pad right"}  # fmt: skip
WIDTH = 32


@dataclass
class Detector:
    """Turns events into lines.

    ``names`` maps a device path to its input name in the profile (devices
    not in the profile are shown without a name). ``modifiers`` are the
    modifier groups of the profile (default: all four).
    """

    names: dict[str, str]
    profile: str | None = None
    modifiers: frozenset[Modifier] = frozenset(Modifier)
    _held: set[tuple[str, int]] = field(default_factory=set)  # modifier keys held
    _sides: dict[tuple[str, int], int] = field(default_factory=dict)  # axis: -1, 0, 1

    def key(self, path: str, device_name: str, code: int, pressed: bool) -> str | None:
        group = self._modifier_group(code)
        if group is not None:
            (self._held.add if pressed else self._held.discard)((path, code))
            return None
        if not pressed:
            return None
        trigger = codes.code_name(code)
        held = sorted(
            {g.value for p, c in self._held if (g := self._modifier_group(c)) is not None},
            key=[m.value for m in Modifier].index,
        )
        if held:
            trigger += f" modifiers({', '.join(held)})"
        return self._line(path, device_name, trigger)

    def axis(self, path: str, device_name: str, code: int, value: float) -> str | None:
        name = codes.TRIGGER_AXIS_NAMES.get(code)
        if name is None:
            return None
        key = (path, code)
        before = self._sides.get(key, 0)
        limit = THRESHOLD - HYSTERESIS if before else THRESHOLD
        side = 1 if value > limit else -1 if value < -limit else 0
        if before and side == 0 and abs(value) > THRESHOLD - HYSTERESIS:
            side = before  # still within the hysteresis
        self._sides[key] = side
        if side == 0 or side == before:
            return None
        trigger = f"{name} {'above' if side > 0 else 'below'} {THRESHOLD * side:g}"
        hint = DPAD.get((name, side))
        return self._line(path, device_name, trigger, hint)

    def _modifier_group(self, code: int) -> Modifier | None:
        for group, keys in MODIFIER_KEYS.items():
            if code in keys and group in self.modifiers:
                return group
        return None

    def _line(self, path: str, device_name: str, trigger: str, hint: str | None = None) -> str:
        input_name = self.names.get(path)
        if input_name is not None:
            trigger = f"{input_name}.{trigger}"
        notes = [hint] if hint else []
        if input_name is None and self.profile is not None:
            notes.append(f"not in {self.profile}; add it with: inpmap input-config {self.profile}")
        text = f"{trigger:<{WIDTH}} {device_name}"
        return text + (f"   ({'; '.join(notes)})" if notes else "")

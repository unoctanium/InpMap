"""Axes of input devices as triggers (docs/configuration.md §5.5).

A threshold on an axis (``pad.ABS_RZ above 0.5``) behaves like a button.
Each distinct (axis, direction, value) gets a *virtual key code* above the
real key codes, so the engine handles it exactly like a key: modifiers,
devices, macros, gestures all work unchanged. This module turns axis
values into presses and releases of those virtual keys.

Backend-independent: backends report axis values already normalised with
:func:`normalize`.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from .codes import TRIGGER_AXIS_NAMES
from .models import AxisThreshold, InputEvent, KeyAction

# Virtual key codes for thresholds start above every real key code
# (KEY_MAX is 0x2ff).
VIRTUAL_CODE_BASE = 0x10000

# A pressed threshold is released only when the value is this far back.
HYSTERESIS = 0.05


def pressed(threshold: AxisThreshold, value: float, was_pressed: bool) -> bool:
    """Whether ``threshold`` is pressed at ``value`` (with hysteresis)."""
    if threshold.above:
        limit = threshold.value - HYSTERESIS if was_pressed else threshold.value
        return value > limit
    limit = threshold.value + HYSTERESIS if was_pressed else threshold.value
    return value < limit


@dataclass(frozen=True)
class AxisEvent:
    """A normalised axis value from a physical input device."""

    device: str
    code: int
    value: float


def normalize(raw: int, minimum: int, maximum: int) -> float:
    """Map a raw axis value to -1.0 .. 1.0 (range around 0) or 0.0 .. 1.0 (range from 0)."""
    if minimum < 0 < maximum:
        return raw / maximum if raw >= 0 else raw / -minimum
    if maximum <= minimum:
        return 0.0
    return (raw - minimum) / (maximum - minimum)


def problem(threshold: AxisThreshold, minimum: int, maximum: int) -> str | None:
    """Why ``threshold`` can never fire on an axis with this range, if it cannot."""
    centered = minimum < 0 < maximum
    if not centered and (not threshold.above or threshold.value <= 0):
        return (
            f"{threshold.describe()} can never fire: the axis only reports 0.0 to 1.0 "
            f"(range {minimum}..{maximum})"
        )
    return None


class AxisTriggers:
    """Turns axis values into presses/releases of the thresholds' virtual keys."""

    def __init__(self, thresholds: dict[int, AxisThreshold]) -> None:
        self._by_axis: dict[int, list[tuple[int, AxisThreshold]]] = {}
        for code, threshold in sorted(thresholds.items()):
            self._by_axis.setdefault(threshold.axis, []).append((code, threshold))
        self._pressed: set[tuple[str, int]] = set()  # (device, virtual code)

    def update(self, event: AxisEvent) -> list[InputEvent]:
        """Key events for the thresholds of this axis whose state changed."""
        result = []
        for code, threshold in self._by_axis.get(event.code, ()):
            key = (event.device, code)
            was = key in self._pressed
            now = pressed(threshold, event.value, was)
            if now != was:
                (self._pressed.add if now else self._pressed.discard)(key)
                action = KeyAction.PRESS if now else KeyAction.RELEASE
                result.append(InputEvent(event.device, code, action))
        return result

    def forget_device(self, device: str) -> None:
        """Drop the state of a lost device (the engine releases its outputs)."""
        self._pressed = {key for key in self._pressed if key[0] != device}


def axes_of(thresholds: Iterable[AxisThreshold]) -> frozenset[int]:
    return frozenset(t.axis for t in thresholds)


@dataclass
class AxisRow:
    """One line of `inpmap axes`: an axis of an input device and its thresholds."""

    input_id: str
    code: int
    minimum: int
    maximum: int
    value: float
    thresholds: list[tuple[str, AxisThreshold]]  # (mapping name, threshold)

    def text(self) -> str:
        name = TRIGGER_AXIS_NAMES.get(self.code, f"ABS_{self.code:#x}")
        marks = []
        for mapping, threshold in self.thresholds:
            hit = self.value > threshold.value if threshold.above else self.value < threshold.value
            direction = "above" if threshold.above else "below"
            marks.append(f"{mapping}: {direction} {threshold.value:g} {'ON' if hit else 'off'}")
        line = (
            f"{self.input_id:<10} {name:<12} {self.value:+.2f}   ({self.minimum}..{self.maximum})"
        )
        return line + ("   " + ", ".join(marks) if marks else "")

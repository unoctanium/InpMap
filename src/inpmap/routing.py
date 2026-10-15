"""Where an input's unmapped input goes (docs/configuration.md §3.4).

When InpMap opens a physical device, :func:`plan_route` decides for every
key, button and axis the device reports where it goes when no mapping uses
it: to an output (keys to the keyboard output, gamepad buttons and axes to
the gamepad output), to the device's pass-through device (mouse parts and
harmless extra axes such as a volume wheel, until there is a mouse output),
or nowhere — then the device is refused and never grabbed, so it keeps
working as if InpMap were not running (§3.4 rule 2).

This module is pure: it sees capability sets, not evdev objects.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field

from . import codes
from .input import InputError
from .macros import OUTPUT_AXIS_KINDS, AxisKind
from .models import Config, InputDeviceSpec, OutputKind
from .output import output_capabilities

# Mouse buttons BTN_LEFT .. BTN_TASK.
MOUSE_BUTTONS = range(0x110, 0x118)
# Digitizer buttons BTN_TOOL_PEN .. BTN_TOOL_QUADTAP (incl. BTN_TOUCH):
# touchpads, touchscreens and tablets.
_TOUCH_BUTTONS = range(0x140, 0x150)
# ABS_PRESSURE .. ABS_TOOL_WIDTH and ABS_MT_SLOT .. ABS_MT_TOOL_Y.
_TOUCH_AXES = (*range(0x18, 0x1D), *range(0x2F, 0x3E))
_JOYSTICK_AXES = frozenset(codes.TRIGGER_AXIS_NAMES)
_MAX_NAMES = 5


class InputRefused(InputError):
    """A device whose unmapped input would have nowhere to go; it is not grabbed."""


@dataclass(frozen=True)
class DeviceCapabilities:
    """What a physical device reports."""

    keys: frozenset[int] = frozenset()  # EV_KEY codes
    axes: Mapping[int, tuple[int, int]] = field(default_factory=dict)  # EV_ABS: (min, max)
    relative: frozenset[int] = frozenset()  # EV_REL codes


@dataclass(frozen=True)
class AxisRoute:
    """An axis of the device going to an axis of the same code on an output."""

    output: str
    kind: AxisKind
    minimum: int
    maximum: int

    def value(self, raw: int) -> float:
        """The device's raw value as a fraction of the output axis' range."""
        low, high = self.minimum, self.maximum
        if high <= low:
            return 0.0
        if self.kind is AxisKind.TRIGGER:
            return _clamp((raw - low) / (high - low), 0.0, 1.0)
        if low < 0 < high:  # centred: 0 stays 0, each side scaled on its own
            value = raw / high if raw >= 0 else raw / -low
        else:  # e.g. 0 .. 255 with the centre at 128
            value = 2.0 * (raw - low) / (high - low) - 1.0
        value = _clamp(value, -1.0, 1.0)
        if self.kind is AxisKind.HAT:
            return -1.0 if value < -0.5 else 1.0 if value > 0.5 else 0.0
        return value


@dataclass(frozen=True)
class RoutePlan:
    """Where each part of one device goes when no mapping uses it."""

    own: bool = False  # `to = own`: everything passes through on its own device
    keys: Mapping[int, str] = field(default_factory=dict)  # key/button -> output
    axes: Mapping[int, AxisRoute] = field(default_factory=dict)
    passthrough_keys: frozenset[int] = frozenset()  # mouse buttons
    passthrough_axes: frozenset[int] = frozenset()  # e.g. ABS_VOLUME
    passthrough_relative: frozenset[int] = frozenset()  # EV_REL

    @property
    def needs_passthrough(self) -> bool:
        """Whether the device needs a pass-through device of its own."""
        return self.own or bool(
            self.passthrough_keys or self.passthrough_axes or self.passthrough_relative
        )


def plan_route(spec: InputDeviceSpec, config: Config, caps: DeviceCapabilities) -> RoutePlan:
    """Decide where the device's unmapped input goes; InputRefused if it cannot.

    A code that a mapping names for this device (or for every input) never
    needs a target: when such a mapping does not fire (e.g. because of held
    modifiers), the event is dropped. Axes that mappings use as triggers are
    always consumed.
    """
    if spec.own:
        return RoutePlan(own=True)
    if any(code in _TOUCH_BUTTONS for code in caps.keys) or any(
        code in _TOUCH_AXES for code in caps.axes
    ):
        raise InputRefused(
            f"input '{spec.id}' is a touchpad, touchscreen or tablet, which no output can "
            f"carry; add `to = own` to its input block"
        )
    mapped = config.input_codes(spec.id) | config.shared_codes()
    watched = config.watched_axes(spec.id)
    keyboard = spec.target(OutputKind.KEYBOARD)
    gamepad = spec.target(OutputKind.GAMEPAD)
    gamepad_buttons = (
        output_capabilities(OutputKind.GAMEPAD, config.output_codes(gamepad)).keys
        if gamepad
        else frozenset()
    )

    keys: dict[int, str] = {}
    passthrough_keys: set[int] = set()
    # Names, for the message when the device is refused.
    no_keyboard: list[str] = []
    no_gamepad: list[str] = []
    unknown: list[str] = []
    for code in sorted(caps.keys):
        if code in MOUSE_BUTTONS:
            passthrough_keys.add(code)
        elif code in codes.KEYBOARD_OUTPUT_KEYS:
            if keyboard:
                keys[code] = keyboard
            elif code not in mapped:
                no_keyboard.append(codes.code_name(code))
        elif code in gamepad_buttons:
            keys[code] = gamepad  # type: ignore[assignment]  # gamepad_buttons implies gamepad
        elif code not in mapped:
            (no_gamepad if codes.is_gamepad_button(code) else unknown).append(codes.code_name(code))

    axes: dict[int, AxisRoute] = {}
    passthrough_axes: set[int] = set()
    centred_on_trigger: list[str] = []
    for code, (low, high) in sorted(caps.axes.items()):
        if code in watched:
            continue
        kind = OUTPUT_AXIS_KINDS.get(code)
        if kind is not None and gamepad:
            if kind is AxisKind.TRIGGER and low < 0 < high:
                centred_on_trigger.append(_axis_name(code))  # e.g. a right stick on ABS_Z
            else:
                axes[code] = AxisRoute(gamepad, kind, low, high)
        elif kind is not None or code in _JOYSTICK_AXES:
            no_gamepad.append(_axis_name(code))
        else:
            passthrough_axes.add(code)

    problems = _problems(no_keyboard, no_gamepad, centred_on_trigger, unknown, gamepad)
    if problems:
        raise InputRefused(
            f"input '{spec.id}' is not taken over, its unmapped input would have nowhere "
            f"to go: {'; '.join(problems)}"
        )
    return RoutePlan(
        keys=keys,
        axes=axes,
        passthrough_keys=frozenset(passthrough_keys),
        passthrough_axes=frozenset(passthrough_axes),
        passthrough_relative=caps.relative,
    )


def _problems(
    no_keyboard: list[str],
    no_gamepad: list[str],
    centred_on_trigger: list[str],
    unknown: list[str],
    gamepad: str | None,
) -> list[str]:
    problems = []
    if no_keyboard:
        problems.append(
            f"it has keys ({_names(no_keyboard)}) but there is no keyboard output; "
            "add: output keyboard { type = keyboard }"
        )
    if no_gamepad:
        fix = (
            "they are not part of the virtual gamepad; use `to = own` for this device"
            if gamepad
            else "add: output gamepad { type = gamepad }, or use `to = own` for this device"
        )
        problems.append(f"it has gamepad or joystick parts ({_names(no_gamepad)}); {fix}")
    if centred_on_trigger:
        problems.append(
            f"{_names(centred_on_trigger)} is centred like a stick but is a trigger on the "
            "virtual gamepad; use `to = own` for this device"
        )
    if unknown:
        problems.append(f"it has buttons no output carries ({_names(unknown)}); use `to = own`")
    return problems


def _axis_name(code: int) -> str:
    return codes.TRIGGER_AXIS_NAMES.get(code, f"axis {code:#x}")


def _names(names: list[str]) -> str:
    if len(names) > _MAX_NAMES:
        names = [*names[:_MAX_NAMES], f"… {len(names) - _MAX_NAMES} more"]
    return ", ".join(names)


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))

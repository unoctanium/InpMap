"""Where an input's unmapped input goes (docs/configuration.md §3.4).

:func:`plan_route` decides it per device; :class:`Router` carries it out.

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

import logging
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Protocol

from . import codes
from .axes import AxisStacks
from .input import InputError
from .macros import OUTPUT_AXIS_KINDS, AxisKind, KeyRef
from .models import Config, InputDeviceSpec, InputEvent, KeyAction, OutputKind
from .output import OutputError, output_capabilities

log = logging.getLogger(__name__)

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

    def value(self, normalized: float) -> float:
        """The output axis value for a device value normalized by
        :func:`inpmap.axis_triggers.normalize` (-1..1 for a range around 0,
        else 0..1)."""
        if self.maximum <= self.minimum:
            return 0.0
        centred = self.minimum < 0 < self.maximum
        if self.kind is AxisKind.TRIGGER:  # never centred (plan_route refuses that)
            return _clamp(normalized, 0.0, 1.0)
        # e.g. a stick reporting 0 .. 255 with the centre at 128
        value = _clamp(normalized if centred else 2.0 * normalized - 1.0, -1.0, 1.0)
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


class RouterHost(Protocol):
    """What the router needs from the engine: shared holders on the outputs."""

    axes: AxisStacks

    def press_key(self, key: KeyRef) -> None: ...

    def release_key(self, key: KeyRef) -> None: ...


class Router:
    """Sends the unmapped input of grabbed devices to the outputs (§3.4).

    Keys and buttons become holders in the engine's reference counts, so a
    button held on a pad and by a mapping stays down until both let go
    (§7.3). Axes set the base value of the output axis, which mappings
    override while they hold it. Key repeat is not sent: desktops repeat
    held keys of the virtual keyboard themselves.
    """

    def __init__(self, host: RouterHost) -> None:
        self._host = host
        self._plans: dict[str, RoutePlan] = {}
        self._down: dict[str, set[int]] = {}  # physically held routed keys
        self._held: dict[str, set[int]] = {}  # keys this input holds on an output
        self._masked: dict[str, set[int]] = {}  # hidden while a mapping runs (§5.2)

    def attach(self, input_id: str, plan: RoutePlan) -> None:
        self._plans[input_id] = plan
        self._down[input_id] = set()
        self._held[input_id] = set()
        self._masked[input_id] = set()

    def routes(self, input_id: str) -> bool:
        """Whether this input's unmapped input goes to the outputs."""
        plan = self._plans.get(input_id)
        return plan is not None and not plan.own

    def key(self, event: InputEvent) -> bool:
        """Route an unmapped key event. False: it belongs on the pass-through device.

        Keys without a target (a mapping uses them, but did not fire) are
        dropped and count as handled.
        """
        plan = self._plans[event.device]
        if event.code in plan.passthrough_keys:
            return False
        if event.code not in plan.keys:
            log.debug("dropping unmapped %s of '%s'", codes.code_name(event.code), event.device)
            return True
        down = self._down[event.device]
        if event.action is KeyAction.PRESS:
            down.add(event.code)
            if event.code not in self._masked[event.device]:
                self._hold(event.device, event.code)
        elif event.action is KeyAction.RELEASE:
            down.discard(event.code)
            self._let_go(event.device, event.code)
        return True

    def axis(self, input_id: str, code: int, normalized: float) -> bool:
        """Route an axis value (normalized, see :meth:`AxisRoute.value`).

        False: it belongs on the pass-through device.
        """
        plan = self._plans[input_id]
        route = plan.axes.get(code)
        if route is None:
            return code not in plan.passthrough_axes
        self._host.axes.set_base((route.output, code), input_id, route.value(normalized))
        return True

    def mask(self, input_id: str, code: int) -> None:
        """Hide a held key from the output while a mapping with modifiers runs."""
        self._masked[input_id].add(code)
        self._let_go(input_id, code)

    def unmask(self, input_id: str, code: int) -> None:
        self._masked[input_id].discard(code)
        if code in self._down[input_id]:
            self._hold(input_id, code)

    def detach(self, input_id: str) -> None:
        """Release everything the input holds and forget its axis values.

        Raises OutputError after trying everything if a write failed.
        """
        plan = self._plans.pop(input_id, None)
        if plan is None:
            return
        failures: list[str] = []
        for code in sorted(self._held.pop(input_id)):
            try:
                self._host.release_key(KeyRef(plan.keys[code], code))
            except OutputError as exc:
                failures.append(str(exc))
        for code, route in plan.axes.items():
            try:
                self._host.axes.clear_base((route.output, code), input_id)
            except OutputError as exc:
                failures.append(str(exc))
        del self._down[input_id], self._masked[input_id]
        if failures:
            raise OutputError("; ".join(failures))

    def detach_all(self) -> None:
        failures: list[str] = []
        for input_id in list(self._plans):
            try:
                self.detach(input_id)
            except OutputError as exc:
                failures.append(str(exc))
        if failures:
            raise OutputError("; ".join(failures))

    def _hold(self, input_id: str, code: int) -> None:
        held = self._held[input_id]
        if code in held:
            return
        held.add(code)  # before writing: a failed press is still released later
        self._host.press_key(KeyRef(self._plans[input_id].keys[code], code))

    def _let_go(self, input_id: str, code: int) -> None:
        held = self._held[input_id]
        if code not in held:
            return
        held.discard(code)
        self._host.release_key(KeyRef(self._plans[input_id].keys[code], code))

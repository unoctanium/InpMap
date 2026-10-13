"""Parsing and validation of macro outputs (see docs/configuration.md §6).

Used by :mod:`inpmap.config`; reports problems through the configuration
validator so all errors of a file are collected together, each with its JSON
path.
"""

from __future__ import annotations

from collections.abc import Callable
from enum import Enum
from typing import TYPE_CHECKING

from . import codes
from .macros import (
    DEFAULT_MAX_RUN_MS,
    MAX_REPEAT,
    AddVar,
    Count,
    Duration,
    HoldAxis,
    HoldKeys,
    IfEq,
    IfLed,
    IfSingle,
    IfTap,
    KeyRef,
    Led,
    Macro,
    MoveAxis,
    OnRelease,
    OnRetrigger,
    Parallel,
    Press,
    RandomRange,
    Release,
    Repeat,
    SetVar,
    Step,
    Tap,
    Toggle,
    VarRef,
    Wait,
    WhileHeld,
    WithKeys,
    walk,
)
from .models import OutputDeviceSpec

if TYPE_CHECKING:
    from .config import _Validator

_MACRO_KEYS = {
    "steps",
    "release_steps",
    "device",
    "on_release",
    "on_retrigger",
    "key_pause_ms",
    "max_run_ms",
}

# Step key -> optional companion fields (required ones in _REQUIRED_FIELDS).
_STEP_FIELDS: dict[str, set[str]] = {
    "tap": {"device", "pause_ms"},
    "press": {"device", "pause_ms"},
    "release": {"device", "pause_ms"},
    "hold_keys": {"device"},
    "with_keys": {"device", "steps"},
    "axis": {"device", "to", "over_ms"},
    "hold_axis": {"device", "value", "attack_ms", "release_ms"},
    "wait_ms": set(),
    "repeat": {"steps"},
    "while_held": set(),
    "toggle": set(),
    "parallel": set(),
    "if_tap": set(),
    "if_single": set(),
    "if_eq": set(),
    "if_led": set(),
    "set": set(),
    "add": set(),
}
_REQUIRED_FIELDS = {
    "with_keys": ("steps",),
    "axis": ("to",),
    "hold_axis": ("value",),
    "repeat": ("steps",),
}

_NO_DEVICE = object()  # marker: the step's own device reference was invalid


def is_number(value: object) -> bool:
    """int or float, but not bool (which is an int subclass in Python)."""
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def value_type(value: object) -> str | None:
    """Variable type of a JSON value: bool, int, float, string, or None."""
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, int):
        return "int"
    if isinstance(value, float):
        return "float"
    if isinstance(value, str):
        return "string"
    return None


def macro_devices(macro: Macro) -> set[str]:
    """Output devices a macro writes to."""
    devices = {key.device for key in macro.key_refs()}
    devices |= {
        step.device
        for step in walk(macro.steps + macro.release_steps)
        if isinstance(step, (MoveAxis, HoldAxis))
    }
    return devices


class MacroParser:
    """Parses one ``{"macro": {...}}`` output entry."""

    def __init__(self, validator: _Validator, outputs: dict[str, OutputDeviceSpec]) -> None:
        self.v = validator
        self.outputs = outputs
        self.default_device: OutputDeviceSpec | None = None

    # -- macro ----------------------------------------------------------------

    def macro_output(self, raw: dict, where: str) -> Macro | None:
        v = self.v
        v.check_keys(raw, where, {"macro"}, required=("macro",))
        where = f"{where}.macro"
        body = raw["macro"]
        if not v.check_object(body, where):
            return None
        before = len(v.problems)
        v.check_keys(body, where, _MACRO_KEYS, required=("steps",))
        if "device" in body:
            self.default_device = v.output_device_ref(
                body["device"], f"{where}.device", self.outputs
            )
        on_release = self.choice(body.get("on_release", "finish"), OnRelease, f"{where}.on_release")
        on_retrigger = self.choice(
            body.get("on_retrigger", "ignore"), OnRetrigger, f"{where}.on_retrigger"
        )
        key_pause = v.milliseconds(
            body.get("key_pause_ms", v.settings.key_pause_ms), f"{where}.key_pause_ms"
        )
        max_run = body.get("max_run_ms", DEFAULT_MAX_RUN_MS)
        if max_run is not None and (not is_number(max_run) or max_run <= 0):
            v.error(f"{where}.max_run_ms", "must be a number of milliseconds > 0, or null")
        steps = self.steps(body.get("steps"), f"{where}.steps", required=True, allow_toggle=True)
        release_steps = (
            self.steps(body["release_steps"], f"{where}.release_steps", required=False)
            if "release_steps" in body
            else ()
        )
        if len(v.problems) > before:
            return None
        assert on_release is not None and on_retrigger is not None and key_pause is not None
        macro = Macro(
            steps=steps,
            release_steps=release_steps,
            on_release=on_release,
            on_retrigger=on_retrigger,
            key_pause_ms=key_pause,
            max_run_ms=None if max_run is None else float(max_run),
        )
        self.check_releases(macro, where)
        return macro if len(v.problems) == before else None

    def choice(self, value: object, enum: type[Enum], where: str):
        valid = [member.value for member in enum]
        if value not in valid:
            self.v.error(where, f"must be one of: {', '.join(valid)}, got {value!r}")
            return None
        return enum(value)

    def check_releases(self, macro: Macro, where: str) -> None:
        pressed: set[KeyRef] = set()
        releases: list[KeyRef] = []
        for step in walk(macro.steps + macro.release_steps):
            if isinstance(step, Release):
                releases += step.keys
            elif isinstance(step, (Tap, Press, HoldKeys, WithKeys)):
                pressed |= set(step.keys)
        for key in releases:
            if key not in pressed:
                self.v.error(
                    where,
                    f"releases {key.device} {codes.code_name(key.code)}, "
                    "which this macro never presses",
                )

    # -- step lists -------------------------------------------------------------

    def steps(
        self, raw: object, where: str, *, required: bool, allow_toggle: bool = False
    ) -> tuple[Step, ...]:
        if not isinstance(raw, list):
            self.v.error(where, "must be a JSON array of steps")
            return ()
        if required and not raw:
            self.v.error(where, "must contain at least one step")
        result: list[Step] = []
        for index, item in enumerate(raw):
            step = self.step(item, f"{where}[{index}]")
            if step is not None:
                result.append(step)
        if any(isinstance(s, Toggle) for s in result) and not (allow_toggle and len(raw) == 1):
            self.v.error(where, "'toggle' must be the only step of a macro's 'steps'")
        return tuple(result)

    def step(self, raw: object, where: str) -> Step | None:
        v = self.v
        if not v.check_object(raw, where):
            return None
        assert isinstance(raw, dict)
        kinds = [key for key in raw if key in _STEP_FIELDS]
        if len(kinds) != 1:
            if kinds:
                v.error(where, f"a step has exactly one step key, found: {', '.join(kinds)}")
            else:
                v.error(where, f"unknown step; expected one of: {', '.join(_STEP_FIELDS)}")
            return None
        kind = kinds[0]
        before = len(v.problems)
        v.check_keys(
            raw,
            where,
            {kind} | _STEP_FIELDS[kind],
            required=(kind, *_REQUIRED_FIELDS.get(kind, ())),
        )
        if len(v.problems) > before:
            return None
        parse: Callable[[dict, str], Step | None] = getattr(self, f"_step_{kind}")
        step = parse(raw, where)
        return step if len(v.problems) == before else None

    # -- key steps --------------------------------------------------------------

    def _step_tap(self, raw: dict, where: str) -> Step | None:
        return self._key_step(raw, where, "tap", Tap)

    def _step_press(self, raw: dict, where: str) -> Step | None:
        return self._key_step(raw, where, "press", Press)

    def _step_release(self, raw: dict, where: str) -> Step | None:
        return self._key_step(raw, where, "release", Release)

    def _key_step(self, raw: dict, where: str, kind: str, cls: type) -> Step | None:
        keys = self.keys(raw[kind], f"{where}.{kind}", self.step_device(raw, where))
        pause = self.duration(raw["pause_ms"], f"{where}.pause_ms") if "pause_ms" in raw else None
        if keys is None:
            return None
        return cls(keys, pause)

    def _step_hold_keys(self, raw: dict, where: str) -> Step | None:
        keys = self.keys(raw["hold_keys"], f"{where}.hold_keys", self.step_device(raw, where))
        return HoldKeys(keys) if keys else None

    def _step_with_keys(self, raw: dict, where: str) -> Step | None:
        keys = self.keys(raw["with_keys"], f"{where}.with_keys", self.step_device(raw, where))
        steps = self.steps(raw["steps"], f"{where}.steps", required=True)
        return WithKeys(keys, steps) if keys else None

    def step_device(self, raw: dict, where: str):
        if "device" not in raw:
            return self.default_device
        spec = self.v.output_device_ref(raw["device"], f"{where}.device", self.outputs)
        return spec if spec is not None else _NO_DEVICE

    def keys(self, value: object, where: str, default) -> tuple[KeyRef, ...] | None:
        items = value if isinstance(value, list) else [value]
        if not items:
            self.v.error(where, "must name at least one key")
            return None
        keys: list[KeyRef] = []
        for index, item in enumerate(items):
            item_where = f"{where}[{index}]" if isinstance(value, list) else where
            key = self.key(item, item_where, default)
            if key is not None:
                keys.append(key)
        return tuple(keys) if len(keys) == len(items) else None

    def key(self, item: object, where: str, default) -> KeyRef | None:
        v = self.v
        device = default
        name = item
        if isinstance(item, dict):
            v.check_keys(item, where, {"code", "device"}, required=("code",))
            name = item.get("code")
            if "device" in item:
                device = v.output_device_ref(item["device"], f"{where}.device", self.outputs)
                if device is None:
                    return None
        elif not isinstance(item, str):
            v.error(where, 'must be a key name or {"code": ..., "device": ...}')
            return None
        if device is _NO_DEVICE:
            return None  # the step's device reference was already reported
        if device is None:
            v.error(where, "no output device: add 'device' to the key, the step or the macro")
            return None
        code = v.key_for_device(name, where, device)
        return KeyRef(device.id, code) if code is not None else None

    # -- axis steps -------------------------------------------------------------

    def axis_target(self, raw: dict, where: str, kind_key: str):
        device = self.step_device(raw, where)
        if device is _NO_DEVICE:
            return None
        if device is None:
            self.v.error(where, "no output device: add 'device' to the step or the macro")
            return None
        axis = self.v.axis_code(raw[kind_key], f"{where}.{kind_key}", device)
        return (device, axis) if axis is not None else None

    def _step_axis(self, raw: dict, where: str) -> Step | None:
        target = self.axis_target(raw, where, "axis")
        over = self.duration(raw.get("over_ms", 0), f"{where}.over_ms")
        if target is None:
            return None
        device, (code, kind) = target
        to = self.v.axis_value(raw["to"], f"{where}.to", kind)
        if to is None or over is None:
            return None
        return MoveAxis(device.id, code, to, over)

    def _step_hold_axis(self, raw: dict, where: str) -> Step | None:
        target = self.axis_target(raw, where, "hold_axis")
        attack = self.duration(raw.get("attack_ms", 0), f"{where}.attack_ms")
        release = self.duration(raw.get("release_ms", 0), f"{where}.release_ms")
        if target is None:
            return None
        device, (code, kind) = target
        value = self.v.axis_value(raw["value"], f"{where}.value", kind)
        if value is None or attack is None or release is None:
            return None
        return HoldAxis(device.id, code, value, attack, release)

    # -- timing and flow -----------------------------------------------------------

    def _step_wait_ms(self, raw: dict, where: str) -> Step | None:
        duration = self.duration(raw["wait_ms"], f"{where}.wait_ms")
        return Wait(duration) if duration is not None else None

    def _step_repeat(self, raw: dict, where: str) -> Step | None:
        count = self.count(raw["repeat"], f"{where}.repeat")
        steps = self.steps(raw["steps"], f"{where}.steps", required=True)
        return Repeat(count, steps) if count is not None else None

    def _step_while_held(self, raw: dict, where: str) -> Step | None:
        return WhileHeld(self.steps(raw["while_held"], f"{where}.while_held", required=True))

    def _step_toggle(self, raw: dict, where: str) -> Step | None:
        return Toggle(self.steps(raw["toggle"], f"{where}.toggle", required=True))

    def _step_parallel(self, raw: dict, where: str) -> Step | None:
        value = raw["parallel"]
        if not isinstance(value, list) or not value:
            self.v.error(f"{where}.parallel", "must be a non-empty array of step arrays")
            return None
        branches = tuple(
            self.steps(branch, f"{where}.parallel[{i}]", required=True)
            for i, branch in enumerate(value)
        )
        return Parallel(branches)

    # -- conditions ---------------------------------------------------------------

    def condition(self, raw: dict, kind: str, where: str, extra: set[str], required=()):
        body = raw[kind]
        where = f"{where}.{kind}"
        if not self.v.check_object(body, where):
            return None, where, (), ()
        self.v.check_keys(body, where, {"then", "else"} | extra, required=required)
        then = self.steps(body.get("then", []), f"{where}.then", required=False)
        otherwise = self.steps(body.get("else", []), f"{where}.else", required=False)
        return body, where, then, otherwise

    def timeout(self, value: object, where: str) -> float | None:
        if not is_number(value) or value <= 0:
            self.v.error(where, "must be a number of milliseconds > 0")
            return None
        return float(value)

    def _step_if_tap(self, raw: dict, where: str) -> Step | None:
        body, where, then, otherwise = self.condition(raw, "if_tap", where, {"timeout_ms"})
        if body is None:
            return None
        timeout = self.timeout(body.get("timeout_ms", 300), f"{where}.timeout_ms")
        return IfTap(then, otherwise, timeout) if timeout is not None else None

    def _step_if_single(self, raw: dict, where: str) -> Step | None:
        body, where, then, otherwise = self.condition(raw, "if_single", where, {"timeout_ms"})
        if body is None:
            return None
        timeout = None
        if "timeout_ms" in body:
            timeout = self.timeout(body["timeout_ms"], f"{where}.timeout_ms")
        return IfSingle(then, otherwise, timeout)

    def _step_if_eq(self, raw: dict, where: str) -> Step | None:
        body, where, then, otherwise = self.condition(
            raw, "if_eq", where, {"var", "value"}, required=("var", "value")
        )
        if body is None or "var" not in body or "value" not in body:
            return None
        var = self.var_ref(body["var"], f"{where}.var", None)
        if var is None:
            return None
        value = self.typed_value(var, body["value"], f"{where}.value")
        return IfEq(var, value, then, otherwise)

    def _step_if_led(self, raw: dict, where: str) -> Step | None:
        body, where, then, otherwise = self.condition(
            raw, "if_led", where, {"led"}, required=("led",)
        )
        if body is None or "led" not in body:
            return None
        led = self.choice(body["led"], Led, f"{where}.led")
        return IfLed(led, then, otherwise) if led is not None else None

    # -- variables ----------------------------------------------------------------

    def var_body(self, raw: dict, kind: str, where: str):
        body = raw[kind]
        where = f"{where}.{kind}"
        if not self.v.check_object(body, where):
            return None, where
        self.v.check_keys(body, where, {"var", "value"}, required=("var", "value"))
        if "var" not in body or "value" not in body:
            return None, where
        return body, where

    def _step_set(self, raw: dict, where: str) -> Step | None:
        body, where = self.var_body(raw, "set", where)
        if body is None:
            return None
        var = self.var_ref(body["var"], f"{where}.var", None)
        if var is None:
            return None
        return SetVar(var, self.typed_value(var, body["value"], f"{where}.value"))

    def _step_add(self, raw: dict, where: str) -> Step | None:
        body, where = self.var_body(raw, "add", where)
        if body is None:
            return None
        var = self.var_ref(body["var"], f"{where}.var", {"int", "float"})
        if var is None:
            return None
        value = self.typed_value(var, body["value"], f"{where}.value")
        return AddVar(var, value) if is_number(value) else None

    def var_ref(self, name: object, where: str, types: set[str] | None) -> str | None:
        variables = self.v.variables
        if not isinstance(name, str) or name not in variables:
            known = ", ".join(sorted(variables)) or "none declared"
            self.v.error(where, f"unknown variable {name!r} (declared: {known})")
            return None
        kind = value_type(variables[name])
        if types is not None and kind not in types:
            self.v.error(where, f"variable '{name}' is a {kind}, expected {' or '.join(types)}")
            return None
        return name

    def typed_value(self, var: str, value: object, where: str) -> object:
        expected = value_type(self.v.variables[var])
        given = value_type(value)
        if expected == "float" and given == "int":
            return float(value)  # type: ignore[arg-type]
        if given != expected:
            self.v.error(where, f"variable '{var}' is a {expected}, got {given or 'null'}")
        return value

    # -- durations and counts --------------------------------------------------------

    def duration(self, value: object, where: str) -> Duration | None:
        v = self.v
        if is_number(value):
            if value < 0:
                v.error(where, "must not be negative")
                return None
            return float(value)
        if isinstance(value, dict) and "var" in value:
            v.check_keys(value, where, {"var"}, required=("var",))
            name = self.var_ref(value["var"], f"{where}.var", {"int", "float"})
            return VarRef(name) if name else None
        if isinstance(value, dict) and ("min" in value or "max" in value):
            v.check_keys(value, where, {"min", "max"}, required=("min", "max"))
            low, high = value.get("min"), value.get("max")
            if not (is_number(low) and is_number(high)) or low < 0 or high < 0:
                v.error(where, "'min' and 'max' must be numbers of milliseconds >= 0")
                return None
            if low > high:
                v.error(where, "'min' must not be greater than 'max'")
                return None
            return RandomRange(float(low), float(high))
        v.error(where, 'must be milliseconds, {"min": .., "max": ..} or {"var": ..}')
        return None

    def count(self, value: object, where: str) -> Count | None:
        if isinstance(value, dict) and "var" in value:
            self.v.check_keys(value, where, {"var"}, required=("var",))
            name = self.var_ref(value["var"], f"{where}.var", {"int"})
            return VarRef(name) if name else None
        if not isinstance(value, int) or isinstance(value, bool) or not 0 <= value <= MAX_REPEAT:
            self.v.error(where, f'must be an integer from 0 to {MAX_REPEAT} or {{"var": ..}}')
            return None
        return value

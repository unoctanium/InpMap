"""Validate configuration data and convert it into the model.

The configuration language compiler (:mod:`inpmap.dsl.compiler`) produces
plain data (dicts and lists) that this module validates; it maps every
problem back to the source line and column. Keeping this data layer means
all validation rules live in one place, independent of the file syntax.

Validation is strict: unknown keys, unknown device references, unknown or
mismatched codes and duplicates are rejected before any device is touched.
All problems are collected and reported together.

Version policy: ``version`` is a required integer. Only versions in
:data:`SUPPORTED_VERSIONS` are accepted. Incompatible changes will bump the
version; older versions are then either migrated explicitly or rejected
with a message naming the supported versions.
"""

from __future__ import annotations

import difflib
import re
from collections.abc import Iterable

from . import codes
from .axis_triggers import VIRTUAL_CODE_BASE
from .config_macros import MacroParser, is_number, macro_devices, value_type
from .macros import (
    AXIS_NAMES,
    DEFAULT_KEY_PAUSE_MS,
    GAMEPAD_AXES,
    AxisKind,
    Macro,
    axis_range,
)
from .models import (
    MODIFIER_KEYS,
    AxisOutput,
    AxisThreshold,
    Config,
    InputDeviceSpec,
    InputTrigger,
    MappingRule,
    Modifier,
    ModifierRequirement,
    OutputAction,
    OutputDeviceSpec,
    OutputKind,
    OutputMode,
    Settings,
    Side,
)

SUPPORTED_VERSIONS = frozenset({1})

# uinput stores device names in a fixed buffer of UINPUT_MAX_NAME_SIZE (80)
# bytes including the terminating NUL.
MAX_DEVICE_NAME_BYTES = 79

_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.+-]{0,63}$")

_REQUIRED_TOP_KEYS = ("inputs", "mappings", "outputs", "version")
_TOP_KEYS = {*_REQUIRED_TOP_KEYS, "settings", "variables"}
_SETTINGS_KEYS = {"key_pause_ms", "modifiers"}
_AXIS_OUTPUT_KEYS = {"device", "type", "code", "value", "attack_ms", "release_ms"}
_VARIABLE_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,63}$")
_INPUT_DEVICE_KEYS = {"name", "path"}
_OUTPUT_DEVICE_KEYS = {"type", "name"}
_MAPPING_KEYS = {
    "id",
    "description",
    "input",
    "outputs",
    "consume",
    "keep_modifiers",
    "disable",
}
_EVENT_KEYS = {"device", "type", "code"}

# Event "type" -> required code-name prefix. Both are EV_KEY in Linux; the
# distinction documents intent and catches KEY_/BTN_ mix-ups.
_EVENT_TYPES = {"key": "KEY_", "button": "BTN_"}

# Which event type each virtual output kind accepts.
_OUTPUT_EVENT_TYPE = {OutputKind.KEYBOARD: "key", OutputKind.GAMEPAD: "button"}


class ConfigError(Exception):
    """The configuration could not be loaded or is invalid."""

    def __init__(self, source: str, problems: list[str]) -> None:
        self.source = source
        self.problems = problems
        super().__init__(str(self))

    def __str__(self) -> str:
        lines = [f"{self.source}: invalid configuration"]
        lines += [f"  - {problem}" for problem in self.problems]
        return "\n".join(lines)


def parse_config(data: object, source: str = "<config>") -> Config:
    """Validate already-decoded JSON data and convert it to models."""
    return _Validator(source).config(data)


class _Validator:
    def __init__(self, source: str) -> None:
        self.source = source
        self.problems: list[str] = []
        # Virtual key code of each distinct axis threshold, in order of appearance.
        self.axis_codes: dict[AxisThreshold, int] = {}

    def error(self, where: str, message: str) -> None:
        self.problems.append(f"{where}: {message}")

    def fail_if_problems(self) -> None:
        if self.problems:
            raise ConfigError(self.source, self.problems)

    # -- generic helpers -------------------------------------------------

    def check_keys(self, obj: dict, where: str, allowed: set[str], required: Iterable[str]) -> None:
        for key in sorted(set(obj) - allowed):
            hint = _suggest(key, allowed)
            self.error(where, f"unknown key '{key}'{hint}")
        for key in required:
            if key not in obj:
                self.error(where, f"missing required key '{key}'")

    def check_id(self, value: object, where: str) -> bool:
        if not isinstance(value, str) or not _ID_PATTERN.match(value):
            self.error(
                where,
                f"invalid id {value!r}: use 1-64 letters, digits, '_', '-' or '.', "
                "starting with a letter or digit",
            )
            return False
        return True

    def check_object(self, value: object, where: str) -> bool:
        if not isinstance(value, dict):
            self.error(where, f"must be a JSON object, got {_json_type(value)}")
            return False
        return True

    # -- top level -------------------------------------------------------

    def config(self, data: object) -> Config:
        if not self.check_object(data, "top level"):
            self.fail_if_problems()
        assert isinstance(data, dict)
        self.check_keys(data, "top level", _TOP_KEYS, required=_REQUIRED_TOP_KEYS)

        version = data.get("version")
        # bool is a subclass of int; reject `true` explicitly.
        if "version" in data and (type(version) is not int or version not in SUPPORTED_VERSIONS):
            supported = ", ".join(str(v) for v in sorted(SUPPORTED_VERSIONS))
            self.error("version", f"unsupported version {version!r} (supported: {supported})")
            # Nothing else can be interpreted reliably under an unknown schema.
            self.fail_if_problems()

        inputs = self.input_devices(data.get("inputs", {}))
        outputs = self.output_devices(data.get("outputs", {}))
        for device_id in sorted(set(inputs) & set(outputs)):
            self.error(
                f"outputs.{device_id}",
                f"device id '{device_id}' is used for both an input and an output",
            )
        self.settings = self.parse_settings(data.get("settings", {}))
        self.variables = self.parse_variables(data.get("variables", {}))
        mappings = self.mappings(data.get("mappings", []), inputs, outputs)
        self.check_unused_devices(inputs, outputs, mappings)

        self.fail_if_problems()
        assert isinstance(version, int)
        return Config(
            version=version,
            inputs=inputs,
            outputs=outputs,
            mappings=mappings,
            settings=self.settings,
            variables=self.variables,
        )

    def parse_settings(self, value: object) -> Settings:
        if not self.check_object(value, "settings"):
            return Settings()
        assert isinstance(value, dict)
        self.check_keys(value, "settings", _SETTINGS_KEYS, required=())
        pause = value.get("key_pause_ms", DEFAULT_KEY_PAUSE_MS)
        if not is_number(pause) or pause < 0:
            self.error("settings.key_pause_ms", "must be a number >= 0")
            pause = DEFAULT_KEY_PAUSE_MS
        modifiers = frozenset(Modifier)
        if "modifiers" in value:
            names = value["modifiers"]
            valid = [m.value for m in Modifier]
            if not isinstance(names, list) or any(n not in valid for n in names):
                self.error(
                    "settings.modifiers", f"must be a list of: {', '.join(valid)}, got {names!r}"
                )
            elif len(set(names)) != len(names):
                self.error("settings.modifiers", "lists a modifier twice")
            else:
                modifiers = frozenset(Modifier(n) for n in names)
        return Settings(key_pause_ms=float(pause), modifiers=modifiers)

    def parse_variables(self, value: object) -> dict[str, object]:
        result: dict[str, object] = {}
        if not self.check_object(value, "variables"):
            return result
        assert isinstance(value, dict)
        for name, initial in value.items():
            where = f"variables.{name}"
            if not _VARIABLE_NAME.match(name):
                self.error(
                    where,
                    "invalid variable name: use letters, digits and '_', not starting with a digit",
                )
            elif value_type(initial) is None:
                self.error(
                    where,
                    "initial value must be an integer, a number, a string or true/false, "
                    f"got {_json_type(initial)}",
                )
            else:
                result[name] = initial
        return result

    # -- devices ---------------------------------------------------------

    def input_devices(self, value: object) -> dict[str, InputDeviceSpec]:
        result: dict[str, InputDeviceSpec] = {}
        if not self.check_object(value, "inputs"):
            return result
        assert isinstance(value, dict)
        for device_id, spec in value.items():
            where = f"inputs.{device_id}"
            id_ok = self.check_id(device_id, where)
            if not self.check_object(spec, where):
                continue
            self.check_keys(spec, where, _INPUT_DEVICE_KEYS, required=())
            selectors = [key for key in ("name", "path") if key in spec]
            if len(selectors) != 1:
                self.error(where, "specify exactly one of 'name' or 'path'")
                continue
            selector = selectors[0]
            selected = spec[selector]
            if not isinstance(selected, str) or not selected.strip():
                self.error(f"{where}.{selector}", "must be a non-empty string")
                continue
            if selector == "path" and not selected.startswith("/"):
                self.error(f"{where}.path", f"must be an absolute path, got '{selected}'")
                continue
            if id_ok:
                result[device_id] = InputDeviceSpec(id=device_id, **{selector: selected})
        return result

    def output_devices(self, value: object) -> dict[str, OutputDeviceSpec]:
        result: dict[str, OutputDeviceSpec] = {}
        if not self.check_object(value, "outputs"):
            return result
        assert isinstance(value, dict)
        names: dict[str, str] = {}
        for device_id, spec in value.items():
            where = f"outputs.{device_id}"
            id_ok = self.check_id(device_id, where)
            if not self.check_object(spec, where):
                continue
            self.check_keys(spec, where, _OUTPUT_DEVICE_KEYS, required=("type",))
            kind = self.output_kind(spec.get("type"), f"{where}.type") if "type" in spec else None
            name = spec.get("name", f"InpMap {device_id}")
            if not isinstance(name, str) or not name.strip():
                self.error(f"{where}.name", "must be a non-empty string")
                continue
            if len(name.encode("utf-8")) > MAX_DEVICE_NAME_BYTES:
                self.error(
                    f"{where}.name",
                    f"must be at most {MAX_DEVICE_NAME_BYTES} bytes (uinput limit)",
                )
                continue
            if name in names:
                self.error(f"{where}.name", f"name '{name}' is already used by '{names[name]}'")
                continue
            names[name] = device_id
            if id_ok and kind is not None:
                result[device_id] = OutputDeviceSpec(id=device_id, kind=kind, name=name)
        return result

    def output_kind(self, value: object, where: str) -> OutputKind | None:
        valid = [kind.value for kind in OutputKind]
        if value not in valid:
            self.error(
                where, f"unknown device type {value!r} (expected one of: {', '.join(valid)})"
            )
            return None
        return OutputKind(value)

    # -- mappings --------------------------------------------------------

    def mappings(
        self,
        value: object,
        inputs: dict[str, InputDeviceSpec],
        outputs: dict[str, OutputDeviceSpec],
    ) -> tuple[MappingRule, ...]:
        if not isinstance(value, list):
            self.error("mappings", f"must be a JSON array, got {_json_type(value)}")
            return ()
        if not value:
            self.error("mappings", "must contain at least one mapping")
        rules: list[MappingRule] = []
        seen_ids: set[str] = set()
        trigger_owner: dict[tuple, str] = {}
        for index, raw in enumerate(value):
            rule = self.mapping(index, raw, inputs, outputs)
            if rule is None:
                continue
            where = _mapping_where(index, rule.id)
            if rule.id in seen_ids:
                self.error(where, f"duplicate mapping id '{rule.id}'")
                continue
            seen_ids.add(rule.id)
            key = rule.trigger.match_key
            if key in trigger_owner:
                self.error(
                    f"{where}.input",
                    f"{rule.trigger.device or 'every input'} {trigger_name(rule.trigger)}"
                    f"{_describe_modifiers(rule.trigger)} is already mapped by "
                    f"'{trigger_owner[key]}'; list all outputs in one mapping",
                )
                continue
            trigger_owner[key] = rule.id
            rules.append(rule)
        return tuple(rules)

    def mapping(
        self,
        index: int,
        raw: object,
        inputs: dict[str, InputDeviceSpec],
        outputs: dict[str, OutputDeviceSpec],
    ) -> MappingRule | None:
        where = f"mappings[{index}]"
        if not self.check_object(raw, where):
            return None
        assert isinstance(raw, dict)
        rule_id = raw.get("id")
        id_ok = self.check_id(rule_id, f"{where}.id") if "id" in raw else False
        if id_ok:
            where = _mapping_where(index, rule_id)
        disabled = raw.get("disable", False)
        if not isinstance(disabled, bool):
            self.error(f"{where}.disable", "must be true or false")
            disabled = False
        required = ("id", "input") if disabled else ("id", "input", "outputs")
        self.check_keys(raw, where, _MAPPING_KEYS, required=required)
        if disabled and "outputs" in raw:
            self.error(f"{where}.outputs", "a disabled mapping has no outputs")
        problems_before = len(self.problems)

        description = raw.get("description")
        if description is not None and not isinstance(description, str):
            self.error(f"{where}.description", "must be a string")

        consume = raw.get("consume", True)
        if not isinstance(consume, bool):
            self.error(f"{where}.consume", "must be true or false")
        elif not consume:
            # Passing the original event through as well needs a passthrough
            # output path that does not exist yet; refuse instead of ignoring.
            self.error(f"{where}.consume", "'false' is not supported yet")

        trigger = (
            self.trigger(raw.get("input"), f"{where}.input", inputs) if "input" in raw else None
        )
        if disabled:
            parsed: tuple | None = ((), (), ())
        elif "outputs" in raw:
            parsed = self.mapping_outputs(raw.get("outputs"), f"{where}.outputs", outputs)
        else:
            parsed = None

        keep_modifiers = raw.get("keep_modifiers", False)
        if not isinstance(keep_modifiers, bool):
            self.error(f"{where}.keep_modifiers", "must be true or false")
        elif keep_modifiers and trigger is not None and not trigger.modifiers:
            self.error(f"{where}.keep_modifiers", "only possible when the input requires modifiers")

        if len(self.problems) > problems_before or not id_ok or trigger is None or parsed is None:
            return None
        assert isinstance(rule_id, str)
        keys, axes, macros = parsed
        return MappingRule(
            id=rule_id,
            trigger=trigger,
            outputs=keys,
            consume=consume,
            description=description,
            axes=axes,
            macros=macros,
            keep_modifiers=keep_modifiers,
            disabled=disabled,
        )

    def trigger(
        self, raw: object, where: str, inputs: dict[str, InputDeviceSpec]
    ) -> InputTrigger | None:
        if isinstance(raw, dict) and raw.get("type") == "axis":
            return self.axis_trigger(raw, where, inputs)
        # Without "device" the trigger applies to every input (§5.1).
        event = self.event(raw, where, optional_keys={"modifiers"}, device_optional=True)
        if event is None:
            return None
        device, _event_type, code = event
        assert isinstance(raw, dict)
        modifiers = self.trigger_modifiers(raw.get("modifiers", []), f"{where}.modifiers")
        if code is not None and _modifier_of(code, self.settings.modifiers) is not None:
            self.error(
                f"{where}.code",
                f"{codes.code_name(code)} is a modifier key and cannot be a trigger; "
                "remove it from settings.modifiers to map it as a normal key",
            )
            return None
        if device is not None and device not in inputs:
            self.error(f"{where}.device", self.unknown_device(device, "input", inputs))
            return None
        if code is None or modifiers is None:
            return None
        required, any_modifiers = modifiers
        return InputTrigger(
            device=device, code=code, modifiers=required, any_modifiers=any_modifiers
        )

    def axis_trigger(
        self, raw: dict, where: str, inputs: dict[str, InputDeviceSpec]
    ) -> InputTrigger | None:
        """{"device"?, "type": "axis", "code": "ABS_RZ", "above"|"below": value, "modifiers"?}."""
        self.check_keys(
            raw, where, {"device", "type", "code", "above", "below", "modifiers"}, ["code"]
        )
        device = raw.get("device")
        if device is not None and device not in inputs:
            self.error(f"{where}.device", self.unknown_device(str(device), "input", inputs))
            return None
        name = raw.get("code")
        axis = codes.TRIGGER_AXES.get(name) if isinstance(name, str) else None
        if axis is None:
            known = ", ".join(codes.TRIGGER_AXES)
            self.error(f"{where}.code", f"{name!r} cannot be a trigger (axes: {known})")
            return None
        directions = [key for key in ("above", "below") if key in raw]
        if len(directions) != 1:
            self.error(where, "an axis trigger needs exactly one of 'above' or 'below'")
            return None
        direction = directions[0]
        value = raw[direction]
        if (
            isinstance(value, bool)
            or not isinstance(value, int | float)
            or not -1.0 < value < 1.0
            or value == 0
        ):
            self.error(
                f"{where}.{direction}", "must be a number between -1.0 and 1.0, other than 0"
            )
            return None
        modifiers = self.trigger_modifiers(raw.get("modifiers", []), f"{where}.modifiers")
        if modifiers is None:
            return None
        threshold = AxisThreshold(axis, direction == "above", float(value))
        code = self.axis_codes.setdefault(threshold, VIRTUAL_CODE_BASE + len(self.axis_codes))
        required, any_modifiers = modifiers
        return InputTrigger(
            device=device,
            code=code,
            modifiers=required,
            any_modifiers=any_modifiers,
            axis=threshold,
        )

    def trigger_modifiers(
        self, value: object, where: str
    ) -> tuple[frozenset[ModifierRequirement], bool] | None:
        """Parse a trigger's modifier requirement: a list of names or "ignore"."""
        if value == "ignore":
            return frozenset(), True
        if not isinstance(value, list):
            self.error(where, 'must be a list of modifier names or "ignore"')
            return None
        requirements: list[ModifierRequirement] = []
        for name in value:
            requirement = _MODIFIER_NAMES.get(name) if isinstance(name, str) else None
            if name == "ignore":
                self.error(where, "'ignore' cannot be combined with other modifiers")
                return None
            if requirement is None:
                known = ", ".join(_MODIFIER_NAMES)
                self.error(where, f"unknown modifier {name!r} (expected one of: {known})")
                return None
            if requirement.modifier not in self.settings.modifiers:
                self.error(
                    where,
                    f"'{requirement.modifier.value}' is not a modifier in this configuration "
                    "(see settings.modifiers)",
                )
                return None
            if any(r.modifier is requirement.modifier for r in requirements):
                self.error(where, f"'{requirement.modifier.value}' is listed twice")
                return None
            requirements.append(requirement)
        return frozenset(requirements), False

    def mapping_outputs(
        self, raw: object, where: str, outputs: dict[str, OutputDeviceSpec]
    ) -> tuple[tuple[OutputAction, ...], tuple[AxisOutput, ...], tuple[Macro, ...]] | None:
        """Parse a mapping's outputs: key outputs, axis outputs and macros."""
        if not isinstance(raw, list) or not raw:
            self.error(where, "must be a non-empty JSON array")
            return None
        actions: list[OutputAction] = []
        axes: list[AxisOutput] = []
        macros: list[Macro] = []
        ok = True
        for index, item in enumerate(raw):
            item_where = f"{where}[{index}]"
            if isinstance(item, dict) and "macro" in item:
                macro = MacroParser(self, outputs).macro_output(item, item_where)
                if macro is None:
                    ok = False
                else:
                    macros.append(macro)
            elif isinstance(item, dict) and item.get("type") == "axis":
                axis = self.axis_output(item, item_where, outputs)
                if axis is None:
                    ok = False
                elif any((a.device, a.code) == (axis.device, axis.code) for a in axes):
                    self.error(item_where, f"duplicate axis {axis.device} {AXIS_NAMES[axis.code]}")
                    ok = False
                else:
                    axes.append(axis)
            else:
                action = self.action(item, item_where, outputs)
                if action is None:
                    ok = False
                elif any((a.device, a.code) == (action.device, action.code) for a in actions):
                    self.error(
                        item_where,
                        f"duplicate output {action.device} {codes.code_name(action.code)}",
                    )
                    ok = False
                else:
                    actions.append(action)
        return (tuple(actions), tuple(axes), tuple(macros)) if ok else None

    def axis_output(
        self, raw: dict, where: str, outputs: dict[str, OutputDeviceSpec]
    ) -> AxisOutput | None:
        before = len(self.problems)
        self.check_keys(raw, where, _AXIS_OUTPUT_KEYS, required=("device", "type", "code", "value"))
        spec = self.output_device_ref(raw.get("device"), f"{where}.device", outputs)
        axis = self.axis_code(raw.get("code"), f"{where}.code", spec) if spec else None
        value = self.axis_value(raw.get("value"), f"{where}.value", axis[1]) if axis else None
        attack = self.milliseconds(raw.get("attack_ms", 0), f"{where}.attack_ms")
        release = self.milliseconds(raw.get("release_ms", 0), f"{where}.release_ms")
        if len(self.problems) > before or spec is None or axis is None or value is None:
            return None
        assert attack is not None and release is not None
        return AxisOutput(spec.id, axis[0], value, attack, release)

    # -- helpers shared with the macro parser -------------------------------

    def output_device_ref(
        self, value: object, where: str, outputs: dict[str, OutputDeviceSpec]
    ) -> OutputDeviceSpec | None:
        if not isinstance(value, str):
            self.error(where, "must be an output device id")
            return None
        spec = outputs.get(value)
        if spec is None:
            self.error(where, self.unknown_device(value, "output", outputs))
        return spec

    def key_for_device(self, value: object, where: str, spec: OutputDeviceSpec) -> int | None:
        """Resolve a KEY_*/BTN_* name that must suit the output device."""
        event_type = _OUTPUT_EVENT_TYPE[spec.kind]
        code = self.code(value, where, event_type)
        if code is None:
            return None
        if spec.kind is OutputKind.GAMEPAD and not codes.is_gamepad_button(code):
            self.error(where, _not_gamepad_button(code))
            return None
        return code

    def axis_code(
        self, value: object, where: str, spec: OutputDeviceSpec
    ) -> tuple[int, AxisKind] | None:
        if spec.kind is not OutputKind.GAMEPAD:
            self.error(where, f"axes need a gamepad device; '{spec.id}' is a {spec.kind.value}")
            return None
        if value not in GAMEPAD_AXES:
            self.error(
                where, f"unknown axis {value!r} (expected one of: {', '.join(GAMEPAD_AXES)})"
            )
            return None
        assert isinstance(value, str)
        return GAMEPAD_AXES[value]

    def axis_value(self, value: object, where: str, kind: AxisKind) -> float | None:
        low, high = axis_range(kind)
        if not is_number(value) or not low <= value <= high:
            self.error(where, f"must be a number from {low:g} to {high:g} for a {kind.value}")
            return None
        return float(value)

    def milliseconds(self, value: object, where: str) -> float | None:
        if not is_number(value) or value < 0:
            self.error(where, "must be a number of milliseconds >= 0")
            return None
        return float(value)

    def action(
        self, raw: object, where: str, outputs: dict[str, OutputDeviceSpec]
    ) -> OutputAction | None:
        event = self.event(raw, where, optional_keys={"mode"})
        if event is None:
            return None
        device, event_type, code = event
        assert isinstance(raw, dict)
        mode = self.output_mode(raw.get("mode", OutputMode.HOLD.value), f"{where}.mode")
        spec = outputs.get(device)
        if spec is None:
            self.error(f"{where}.device", self.unknown_device(device, "output", outputs))
            return None
        if code is None:
            return None
        expected_type = _OUTPUT_EVENT_TYPE[spec.kind]
        if event_type != expected_type:
            self.error(
                f"{where}.type",
                f"{spec.kind.value} device '{device}' accepts type '{expected_type}', "
                f"not '{event_type}'",
            )
            return None
        if spec.kind is OutputKind.GAMEPAD and not codes.is_gamepad_button(code):
            self.error(f"{where}.code", _not_gamepad_button(code))
            return None
        if mode is None:
            return None
        return OutputAction(device=device, code=code, mode=mode)

    def output_mode(self, value: object, where: str) -> OutputMode | None:
        valid = [mode.value for mode in OutputMode]
        if value not in valid:
            self.error(where, f"unknown mode {value!r} (expected one of: {', '.join(valid)})")
            return None
        return OutputMode(value)

    def event(
        self,
        raw: object,
        where: str,
        optional_keys: set[str] | None = None,
        device_optional: bool = False,
    ) -> tuple[str | None, str, int | None] | None:
        """Validate a {device, type, code} object.

        Returns (device, type, code) when device and type are usable; code is
        None if only the code was invalid, so device errors are still reported.
        """
        if not self.check_object(raw, where):
            return None
        assert isinstance(raw, dict)
        allowed = _EVENT_KEYS | (optional_keys or set())
        required = sorted(_EVENT_KEYS - ({"device"} if device_optional else set()))
        self.check_keys(raw, where, allowed, required=required)
        device = raw.get("device")
        event_type = raw.get("type")
        if "device" in raw and not isinstance(device, str):
            self.error(f"{where}.device", "must be a string")
        if "type" in raw and event_type not in _EVENT_TYPES:
            self.error(
                f"{where}.type",
                f"unsupported event type {event_type!r} "
                f"(expected one of: {', '.join(_EVENT_TYPES)})",
            )
        device_ok = isinstance(device, str) or (device_optional and "device" not in raw)
        if not device_ok or event_type not in _EVENT_TYPES:
            return None
        code = self.code(raw.get("code"), f"{where}.code", event_type) if "code" in raw else None
        return device, event_type, code

    def code(self, value: object, where: str, event_type: str) -> int | None:
        prefix = _EVENT_TYPES[event_type]
        if not isinstance(value, str):
            self.error(where, f"must be a code name string such as '{prefix}...'")
            return None
        code = codes.code_from_name(value)
        if code is None:
            candidates = [n for n in codes.all_names() if n.startswith(prefix)]
            hint = _suggest(value.upper(), candidates)
            self.error(where, f"unknown {event_type} code '{value}'{hint}")
            return None
        if not value.startswith(prefix):
            self.error(where, f"'{value}' is not a {event_type} code (expected a {prefix}* name)")
            return None
        return code

    def unknown_device(self, device: str, role: str, known: dict) -> str:
        names = ", ".join(sorted(known)) or "none defined"
        return f"unknown {role} device '{device}' (defined {role}s: {names})"

    def check_unused_devices(
        self,
        inputs: dict[str, InputDeviceSpec],
        outputs: dict[str, OutputDeviceSpec],
        mappings: tuple[MappingRule, ...],
    ) -> None:
        # Only meaningful when all mappings parsed; otherwise a device may
        # look unused merely because its mapping had an error.
        if self.problems:
            return
        used_inputs = {rule.trigger.device for rule in mappings}
        if None in used_inputs or any(rule.trigger.modifiers for rule in mappings):
            # Mappings without a device apply to every input; and any input
            # may provide modifiers (e.g. a keyboard configured only for Ctrl
            # used with gamepad buttons).
            used_inputs = set(inputs)
        used_outputs = set()
        for rule in mappings:
            used_outputs |= {action.device for action in rule.outputs}
            used_outputs |= {axis.device for axis in rule.axes}
            for macro in rule.macros:
                used_outputs |= macro_devices(macro)
        for device_id in sorted(set(inputs) - used_inputs):
            self.error(f"inputs.{device_id}", "not used by any mapping")
        for device_id in sorted(set(outputs) - used_outputs):
            # A virtual device without capabilities cannot be created usefully.
            self.error(f"outputs.{device_id}", "not used by any mapping")


def _mapping_where(index: int, rule_id: object) -> str:
    return f"mappings[{index}] ('{rule_id}')"


_MODIFIER_NAMES: dict[str, ModifierRequirement] = {
    **{m.value: ModifierRequirement(m, Side.EITHER) for m in Modifier},
    **{f"left_{m.value}": ModifierRequirement(m, Side.LEFT) for m in Modifier},
    **{f"right_{m.value}": ModifierRequirement(m, Side.RIGHT) for m in Modifier},
}


def _modifier_of(code: int, active: frozenset[Modifier]) -> Modifier | None:
    """The active modifier group a key code belongs to, if any."""
    for modifier, keys in MODIFIER_KEYS.items():
        if code in keys and modifier in active:
            return modifier
    return None


def _describe_modifiers(trigger: InputTrigger) -> str:
    if trigger.any_modifiers:
        return " (any modifiers)"
    if trigger.modifiers:
        return " with " + "+".join(sorted(r.name for r in trigger.modifiers))
    return ""


def _not_gamepad_button(code: int) -> str:
    return (
        f"{codes.code_name(code)} is not a gamepad/joystick button "
        "(e.g. use BTN_SOUTH, BTN_EAST, BTN_START, BTN_DPAD_UP)"
    )


def _suggest(value: str, candidates: Iterable[str]) -> str:
    matches = difflib.get_close_matches(value, list(candidates), n=1)
    return f" (did you mean '{matches[0]}'?)" if matches else ""


def _json_type(value: object) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, (int, float)):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "array"
    if isinstance(value, dict):
        return "object"
    return type(value).__name__


def trigger_name(trigger: InputTrigger) -> str:
    """``KEY_X`` or ``ABS_RZ above 0.5``, for messages."""
    return trigger.axis.describe() if trigger.axis else codes.code_name(trigger.code)

"""Load and validate the JSON configuration.

Validation is strict: unknown keys, unknown device references, unknown or
mismatched codes and duplicates are rejected before any device is touched.
All problems are collected and reported together.

Schema version policy: ``version`` is a required integer. Only versions in
:data:`SUPPORTED_VERSIONS` are accepted. Incompatible format changes will bump
the version; older versions are then either migrated explicitly or rejected
with a message naming the supported versions.
"""

from __future__ import annotations

import difflib
import json
import re
from collections.abc import Iterable
from pathlib import Path

from . import codes
from .models import (
    Config,
    InputDeviceSpec,
    InputTrigger,
    MappingRule,
    OutputAction,
    OutputDeviceSpec,
    OutputKind,
)

SUPPORTED_VERSIONS = frozenset({1})

# uinput stores device names in a fixed buffer of UINPUT_MAX_NAME_SIZE (80)
# bytes including the terminating NUL.
MAX_DEVICE_NAME_BYTES = 79

_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")

_TOP_KEYS = {"version", "inputs", "outputs", "mappings"}
_INPUT_DEVICE_KEYS = {"name", "path"}
_OUTPUT_DEVICE_KEYS = {"type", "name"}
_MAPPING_KEYS = {"id", "description", "input", "outputs", "consume"}
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


def load_config(path: str | Path) -> Config:
    """Read, parse and validate a configuration file."""
    path = Path(path)
    source = str(path)
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ConfigError(source, [f"cannot read file: {exc.strerror or exc}"]) from exc
    except UnicodeDecodeError as exc:
        raise ConfigError(source, [f"file is not valid UTF-8: {exc}"]) from exc
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ConfigError(
            source, [f"invalid JSON at line {exc.lineno}, column {exc.colno}: {exc.msg}"]
        ) from exc
    return parse_config(data, source=source)


def parse_config(data: object, source: str = "<config>") -> Config:
    """Validate already-decoded JSON data and convert it to models."""
    return _Validator(source).config(data)


class _Validator:
    def __init__(self, source: str) -> None:
        self.source = source
        self.problems: list[str] = []

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
        self.check_keys(data, "top level", _TOP_KEYS, required=sorted(_TOP_KEYS))

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
        mappings = self.mappings(data.get("mappings", []), inputs, outputs)
        self.check_unused_devices(inputs, outputs, mappings)

        self.fail_if_problems()
        assert isinstance(version, int)
        return Config(version=version, inputs=inputs, outputs=outputs, mappings=mappings)

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
        trigger_owner: dict[tuple[str, int], str] = {}
        for index, raw in enumerate(value):
            rule = self.mapping(index, raw, inputs, outputs)
            if rule is None:
                continue
            where = _mapping_where(index, rule.id)
            if rule.id in seen_ids:
                self.error(where, f"duplicate mapping id '{rule.id}'")
                continue
            seen_ids.add(rule.id)
            key = (rule.trigger.device, rule.trigger.code)
            if key in trigger_owner:
                self.error(
                    f"{where}.input",
                    f"{rule.trigger.device} {codes.code_name(rule.trigger.code)} is already "
                    f"mapped by '{trigger_owner[key]}'; list all outputs in one mapping",
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
        self.check_keys(raw, where, _MAPPING_KEYS, required=("id", "input", "outputs"))
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
        actions = (
            self.actions(raw.get("outputs"), f"{where}.outputs", outputs)
            if "outputs" in raw
            else None
        )

        if len(self.problems) > problems_before or not id_ok or trigger is None or actions is None:
            return None
        assert isinstance(rule_id, str)
        return MappingRule(
            id=rule_id,
            trigger=trigger,
            outputs=actions,
            consume=consume,
            description=description,
        )

    def trigger(
        self, raw: object, where: str, inputs: dict[str, InputDeviceSpec]
    ) -> InputTrigger | None:
        event = self.event(raw, where)
        if event is None:
            return None
        device, _event_type, code = event
        if device not in inputs:
            self.error(f"{where}.device", self.unknown_device(device, "input", inputs))
            return None
        if code is None:
            return None
        return InputTrigger(device=device, code=code)

    def actions(
        self, raw: object, where: str, outputs: dict[str, OutputDeviceSpec]
    ) -> tuple[OutputAction, ...] | None:
        if not isinstance(raw, list) or not raw:
            self.error(where, "must be a non-empty JSON array")
            return None
        actions: list[OutputAction] = []
        ok = True
        for index, item in enumerate(raw):
            action = self.action(item, f"{where}[{index}]", outputs)
            if action is None:
                ok = False
            elif action in actions:
                self.error(
                    f"{where}[{index}]",
                    f"duplicate output {action.device} {codes.code_name(action.code)}",
                )
                ok = False
            else:
                actions.append(action)
        return tuple(actions) if ok else None

    def action(
        self, raw: object, where: str, outputs: dict[str, OutputDeviceSpec]
    ) -> OutputAction | None:
        event = self.event(raw, where)
        if event is None:
            return None
        device, event_type, code = event
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
            self.error(
                f"{where}.code",
                f"{codes.code_name(code)} is not a gamepad/joystick button "
                "(e.g. use BTN_SOUTH, BTN_EAST, BTN_START, BTN_DPAD_UP)",
            )
            return None
        return OutputAction(device=device, code=code)

    def event(self, raw: object, where: str) -> tuple[str, str, int | None] | None:
        """Validate a {device, type, code} object.

        Returns (device, type, code) when device and type are usable; code is
        None if only the code was invalid, so device errors are still reported.
        """
        if not self.check_object(raw, where):
            return None
        assert isinstance(raw, dict)
        self.check_keys(raw, where, _EVENT_KEYS, required=sorted(_EVENT_KEYS))
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
        if not isinstance(device, str) or event_type not in _EVENT_TYPES:
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
        used_outputs = {action.device for rule in mappings for action in rule.outputs}
        for device_id in sorted(set(inputs) - used_inputs):
            self.error(f"inputs.{device_id}", "not used by any mapping")
        for device_id in sorted(set(outputs) - used_outputs):
            # A virtual device without capabilities cannot be created usefully.
            self.error(f"outputs.{device_id}", "not used by any mapping")


def _mapping_where(index: int, rule_id: object) -> str:
    return f"mappings[{index}] ('{rule_id}')"


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

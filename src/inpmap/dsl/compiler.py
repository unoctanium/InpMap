"""Compile the configuration language into the validated model (docs/configuration.md).

The parse tree is translated into the configuration data structure that
:func:`inpmap.config.parse_config` validates, so every validation rule and
the whole runtime are shared. The compiler adds what only the language has:
device inference, modifier aliases, gestures, non-blocking ``hold``/``axis``
(translated into ``parallel``), typed variables incl. durations, options,
and line/column positions — validator messages are mapped back to the
source position of the element they refer to.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from lark import Token, Tree

from ..config import ConfigError, parse_config
from ..macros import GAMEPAD_AXES
from ..models import Config
from .parser import DslSyntaxError, parse

LANGUAGE_VERSIONS = frozenset({1})
DEFAULT_GESTURE_WINDOW_MS = 300.0
LEDS = ("capslock", "numlock", "scrolllock")
OUTPUT_ALIASES = {
    "ctrl": "KEY_LEFTCTRL",
    "shift": "KEY_LEFTSHIFT",
    "alt": "KEY_LEFTALT",
    "meta": "KEY_LEFTMETA",
}
MODIFIER_NAMES = {
    "ctrl",
    "shift",
    "alt",
    "meta",
    *(f"{side}_{m}" for side in ("left", "right") for m in ("ctrl", "shift", "alt", "meta")),
}
# Words with a meaning in the language; not allowed as user-chosen names.
RESERVED = {
    *"""version settings let input output map as hold tap press release with wait
    random repeat while held toggle parallel branch on double_tap long_press if
    else single not and within after axis move to over cancel restart keep
    modifiers ignore key_pause max_run none true false disable above below layer off
    block call own""".split(),
    *LEDS,
    *MODIFIER_NAMES,
}
CONFUSING_BUTTONS = {
    "BTN_X": "BTN_X is the top button (labelled Y on Xbox controllers); BTN_NORTH says so",
    "BTN_Y": "BTN_Y is the left button (labelled X on Xbox controllers); BTN_WEST says so",
}
OPTION_STATEMENTS = {"opt_cancel", "opt_restart", "opt_keep", "opt_kv"}
# Statements that only make sense for a whole mapping (§6.11 rule 3).
BLOCK_FORBIDDEN = {
    **dict.fromkeys(OPTION_STATEMENTS, "a mapping option"),
    "on_release": "'on release'",
    "toggle": "'toggle'",
    "disable": "'disable'",
}


@dataclass
class LoadResult:
    config: Config
    warnings: list[str]


def load(path: str | Path) -> LoadResult:
    """Read, compile and validate a configuration file in the language."""
    path = Path(path)
    source = str(path)
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ConfigError(source, [f"cannot read file: {exc.strerror or exc}"]) from exc
    except UnicodeDecodeError as exc:
        raise ConfigError(source, [f"file is not valid UTF-8: {exc}"]) from exc
    return compile_text(text, source)


def compile_text(text: str, source: str = "<config>") -> LoadResult:
    try:
        tree = parse(text, source)
    except DslSyntaxError as exc:
        raise ConfigError(source, [str(exc)]) from None
    compiler = _Compiler(source)
    data = compiler.compile(tree)
    if compiler.errors:
        raise ConfigError(source, compiler.errors)
    try:
        config = parse_config(data, source)
    except ConfigError as exc:
        # dict.fromkeys: a block's problem is found once per call (§6.11 rule 6)
        located = list(dict.fromkeys(compiler.locate(p) for p in exc.problems))
        raise ConfigError(source, located) from None
    return LoadResult(config, compiler.warnings)


def _pos(node: Tree | Token) -> tuple[int, int]:
    if isinstance(node, Token):
        return node.line or 1, node.column or 1
    meta = node.meta
    return getattr(meta, "line", 1), getattr(meta, "column", 1)


def _unescape(literal: str) -> str:
    body = literal[1:-1]
    return re.sub(r"\\(.)", lambda m: {"n": "\n", "t": "\t"}.get(m.group(1), m.group(1)), body)


def _duration_ms(text: str) -> float:
    if text.endswith("ms"):
        return float(text[:-2])
    return float(text[:-1]) * 1000


class _Compiler:
    def __init__(self, source: str) -> None:
        self.source = source
        self.errors: list[str] = []
        self.warnings: list[str] = []
        self.positions: dict[str, tuple[int, int]] = {}
        self.inputs: dict[str, Tree] = {}
        self.outputs: dict[str, str] = {}  # name -> type (or "" if unknown)
        self.var_types: dict[str, str] = {}
        self.layer_names: set[str] = set()
        self.blocks: dict[str, Tree] = {}  # name -> block_def
        self.cyclic_blocks: set[str] = set()
        self.called_blocks: set[str] = set()

    # -- messages and positions ----------------------------------------------

    # Messages are recorded once: a block's statements are compiled once per
    # call, but their problems belong to the block's lines (§6.11 rule 6).
    def error(self, node: Tree | Token, message: str) -> None:
        line, column = _pos(node)
        text = f"{self.source}:{line}:{column}: {message}"
        if text not in self.errors:
            self.errors.append(text)

    def warn(self, node: Tree | Token, message: str) -> None:
        line, column = _pos(node)
        text = f"{self.source}:{line}:{column}: warning: {message}"
        if text not in self.warnings:
            self.warnings.append(text)

    def record(self, path: str, node: Tree | Token) -> None:
        self.positions.setdefault(path, _pos(node))

    def locate(self, problem: str) -> str:
        """Turn a validator message "path: text" into "FILE:LINE:COLUMN: text"."""
        path, sep, message = problem.partition(": ")
        if not sep:
            return f"{self.source}: {problem}"
        normalized = re.sub(r" \('[^']*'\)", "", path)
        best = None
        for known in self.positions:
            if normalized == known or normalized.startswith((known + ".", known + "[")):
                if best is None or len(known) > len(best):
                    best = known
        if best is None:
            return f"{self.source}: {problem}"
        line, column = self.positions[best]
        return f"{self.source}:{line}:{column}: {message}"

    def check_name(self, token: Token, what: str) -> bool:
        if str(token) in RESERVED:
            self.error(token, f"'{token}' is a reserved word and cannot be used as {what}")
            return False
        return True

    # -- top level ----------------------------------------------------------------

    def compile(self, tree: Tree) -> dict:
        statements = tree.children
        data: dict = {"inputs": {}, "outputs": {}, "mappings": []}
        if not statements or statements[0].data != "version":
            node = statements[0] if statements else Token("NAME", "", line=1, column=1)
            self.error(node, "the file must start with 'version 1'")
        maps: list[tuple[Tree, str | None]] = []
        layers: dict[str, Tree] = {}
        self.collect_blocks(statements)
        for stmt in statements:
            kind = stmt.data
            if kind == "version":
                self.compile_version(stmt, data)
            elif kind == "settings":
                data["settings"] = self.compile_settings(stmt)
            elif kind == "let_stmt":
                self.compile_let(stmt, data.setdefault("variables", {}))
            elif kind == "input_def":
                self.compile_device(stmt, data["inputs"], "inputs")
            elif kind == "output_def":
                self.compile_device(stmt, data["outputs"], "outputs")
            elif kind == "map_def":
                maps.append((stmt, None))
            elif kind == "layer_def":
                name_token, *layer_maps = stmt.children
                name = str(name_token)
                if not self.check_name(name_token, "a layer name"):
                    continue
                if name in layers:
                    self.error(
                        name_token,
                        f"layer '{name}' is already defined at line {_pos(layers[name])[0]}",
                    )
                    continue
                if not layer_maps:
                    self.error(stmt, f"layer '{name}' has no mappings")
                layers[name] = stmt
                maps += [(m, name) for m in layer_maps]
        self.layer_names = set(layers)
        if layers:
            data["layers"] = list(layers)
        for name, props in data["outputs"].items():
            self.outputs[name] = props.get("type", "") if isinstance(props, dict) else ""
        seen: dict[tuple, int] = {}
        for index, (stmt, layer) in enumerate(maps):
            mapping = self.compile_map(stmt, index, layer)
            if mapping is None:
                continue
            trigger = mapping["input"]
            modifiers = trigger.get("modifiers", [])
            key = (
                layer,
                trigger.get("device"),
                trigger["code"],
                trigger.get("above"),
                trigger.get("below"),
                modifiers if isinstance(modifiers, str) else tuple(sorted(modifiers)),
            )
            if key in seen:
                ref = stmt.children[0]
                self.error(ref, f"this input is already mapped at line {seen[key]}")
                continue
            seen[key] = _pos(stmt)[0]
            data["mappings"].append(mapping)
        for name, block in self.blocks.items():
            if name not in self.called_blocks and name not in self.cyclic_blocks:
                self.warn(block.children[0], f"block '{name}' is never called")
        return data

    # -- reusable blocks (§6.11) ------------------------------------------------------

    def collect_blocks(self, statements: list[Tree]) -> None:
        for stmt in statements:
            if stmt.data != "block_def":
                continue
            name_token, body = stmt.children
            name = str(name_token)
            if not self.check_name(name_token, "a block name"):
                continue
            if name in self.blocks:
                line = _pos(self.blocks[name])[0]
                self.error(name_token, f"block '{name}' is already defined at line {line}")
                continue
            self.blocks[name] = stmt
            for node in body.iter_subtrees_topdown():
                if node.data in BLOCK_FORBIDDEN:
                    self.error(node, f"{BLOCK_FORBIDDEN[node.data]} is not allowed in a block")
        self.find_cycles()

    def find_cycles(self) -> None:
        calls = {
            name: [
                str(n.children[0]) for n in block.children[1].iter_subtrees() if n.data == "call"
            ]
            for name, block in self.blocks.items()
        }

        def reaches(start: str, target: str, seen: set[str]) -> bool:
            for callee in calls.get(start, []):
                if callee == target or (
                    callee not in seen and reaches(callee, target, seen | {callee})
                ):
                    return True
            return False

        for name, block in self.blocks.items():
            if reaches(name, name, {name}):
                self.cyclic_blocks.add(name)
                self.error(
                    block.children[0],
                    f"block '{name}' calls itself (directly or through other blocks)",
                )

    def expand_calls(self, statements: list[Tree]) -> list[Tree]:
        """Replace `call NAME` by the block's statements, as if written there."""
        result: list[Tree] = []
        for stmt in statements:
            if stmt.data != "call":
                result.append(stmt)
                continue
            token = stmt.children[0]
            name = str(token)
            if name not in self.blocks:
                known = ", ".join(sorted(self.blocks)) or "none defined"
                self.error(token, f"unknown block '{name}' (blocks: {known})")
            elif name not in self.cyclic_blocks:
                self.called_blocks.add(name)
                result += self.expand_calls(list(self.blocks[name].children[1].children))
        return result

    def compile_version(self, stmt: Tree, data: dict) -> None:
        if "version" in data:
            self.error(stmt, "'version' appears twice")
            return
        token = stmt.children[0]
        value = float(token)
        if value not in LANGUAGE_VERSIONS:
            supported = ", ".join(str(v) for v in sorted(LANGUAGE_VERSIONS))
            self.error(token, f"unsupported version {token} (supported: {supported})")
        data["version"] = 1
        self.record("version", stmt)

    def compile_settings(self, stmt: Tree) -> dict:
        settings: dict = {}
        for prop in stmt.children[0].children:
            name, values = self.prop(prop)
            if name == "key_pause":
                ms = self.single_duration(values, prop, "key_pause")
                if ms is not None:
                    settings["key_pause_ms"] = ms
                    self.record("settings.key_pause_ms", prop)
            elif name == "modifiers":
                names = [v for kind, v in values if kind == "name"]
                if len(names) != len(values):
                    self.error(prop, "modifiers: list modifier names, e.g. ctrl, shift")
                settings["modifiers"] = names
                self.record("settings.modifiers", prop)
            else:
                self.error(prop, f"unknown setting '{name}' (known: key_pause, modifiers)")
        return settings

    def compile_let(self, stmt: Tree, variables: dict) -> None:
        name_token, value_tree = stmt.children
        name = str(name_token)
        if not self.check_name(name_token, "a variable name"):
            return
        if name in self.var_types:
            self.error(name_token, f"variable '{name}' is declared twice")
            return
        kind, value = self.value(value_tree)
        if kind == "name":
            self.error(
                value_tree,
                f"initial value of '{name}' must be a number, duration, "
                f"string or true/false, not the name '{value}'",
            )
            return
        self.var_types[name] = kind
        variables[name] = value
        self.record(f"variables.{name}", stmt)

    def compile_device(self, stmt: Tree, target: dict, section: str) -> None:
        name_token, props = stmt.children
        name = str(name_token)
        if not self.check_name(name_token, "a device name"):
            return
        if name in self.inputs or name in self.outputs or name in target:
            self.error(name_token, f"device '{name}' is declared twice")
            return
        entry: dict = {}
        for prop in props.children:
            key, values = self.prop(prop)
            if key == "to" and section == "inputs":
                # `to = keyboard, gamepad2` or `to = own` (§3.4)
                if any(kind != "name" for kind, _ in values):
                    self.error(prop, "'to' takes output names or 'own'")
                    continue
                entry[key] = [value for _, value in values]
                self.record(f"{section}.{name}.{key}", prop)
                continue
            if len(values) != 1:
                self.error(prop, f"'{key}' takes one value")
                continue
            kind, value = values[0]
            if kind not in ("string", "name"):
                self.error(prop, f"'{key}' must be a name or a string")
                continue
            entry[key] = value
            self.record(f"{section}.{name}.{key}", prop)
        target[name] = entry
        self.record(f"{section}.{name}", stmt)
        if section == "inputs":
            self.inputs[name] = stmt
        else:
            self.outputs[name] = entry.get("type", "")

    # -- values -----------------------------------------------------------------

    def value(self, tree: Tree) -> tuple[str, object]:
        token = tree.children[0]
        text = str(token)
        if tree.data == "v_number":
            return ("float", float(text)) if "." in text else ("int", int(text))
        if tree.data == "v_duration":
            return "duration", _duration_ms(text)
        if tree.data == "v_string":
            return "string", _unescape(text)
        if text in ("true", "false"):
            return "bool", text == "true"
        return "name", text

    def prop(self, prop: Tree) -> tuple[str, list[tuple[str, object]]]:
        name_tree, *values = prop.children
        return str(name_tree.children[0]), [self.value(v) for v in values]

    def single_duration(self, values: list, node: Tree, what: str) -> float | None:
        if len(values) != 1 or values[0][0] != "duration":
            self.error(node, f"'{what}' must be a duration such as 10ms")
            return None
        return values[0][1]

    def duration(self, tree: Tree) -> object | None:
        """Duration node -> ms number, {"min","max"} or {"var"}."""
        if tree.data == "dur_literal":
            return _duration_ms(str(tree.children[0]))
        if tree.data == "dur_random":
            low, high = (self.duration(child) for child in tree.children)
            if not isinstance(low, float) or not isinstance(high, float):
                self.error(tree, "random() takes two duration literals, e.g. random(40ms, 60ms)")
                return None
            return {"min": low, "max": high}
        name = str(tree.children[0])
        if self.var_types.get(name) != "duration":
            self.error(tree, self.var_problem(name, "a duration variable"))
            return None
        return {"var": name}

    def var_problem(self, name: str, expected: str) -> str:
        if name not in self.var_types:
            known = ", ".join(sorted(self.var_types)) or "none declared"
            return f"unknown variable '{name}' (declared: {known})"
        return f"'{name}' is a {self.var_types[name]} variable, expected {expected}"

    def typed(self, name: str, tree: Tree) -> object | None:
        """Value for assignment/comparison with variable ``name`` (types must match)."""
        if name not in self.var_types:
            self.error(tree, self.var_problem(name, "a variable"))
            return None
        expected = self.var_types[name]
        kind, value = self.value(tree)
        if expected == "float" and kind == "int":
            return float(value)  # type: ignore[arg-type]
        if kind != expected:
            self.error(tree, f"'{name}' is a {expected} variable, got a {kind} value")
            return None
        return value

    # -- references -----------------------------------------------------------------

    def output_ref(self, ref: Tree, path: str) -> dict | None:
        """A key/button reference -> {"code", "device"}."""
        tokens = [str(t) for t in ref.children]
        device = tokens[0] if len(tokens) == 2 else None
        name = tokens[-1]
        code = OUTPUT_ALIASES.get(name, name)
        self.check_confusing(ref, code)
        if device is None:
            device = self.infer_device(ref, code)
            if device is None:
                return None
        elif device not in self.outputs:
            self.error(ref, self.unknown_output(device))
            return None
        self.record(path, ref)
        return {"code": code, "device": device}

    def axis_ref(self, ref: Tree) -> tuple[str, str] | None:
        tokens = [str(t) for t in ref.children]
        code = tokens[-1]
        if code not in GAMEPAD_AXES:
            self.error(ref, f"unknown axis '{code}' (expected one of: {', '.join(GAMEPAD_AXES)})")
            return None
        if len(tokens) == 2:
            if tokens[0] not in self.outputs:
                self.error(ref, self.unknown_output(tokens[0]))
                return None
            return tokens[0], code
        device = self.infer_device(ref, code)
        return (device, code) if device else None

    def infer_device(self, node: Tree, code: str) -> str | None:
        if code.startswith("KEY_"):
            kind = "keyboard"
        elif code.startswith(("BTN_", "ABS_")):
            kind = "gamepad"
        else:
            self.error(node, f"'{code}' is not a key, button or axis name")
            return None
        candidates = [name for name, kind_ in self.outputs.items() if kind_ == kind]
        if len(candidates) == 1:
            return candidates[0]
        if not candidates:
            self.error(node, f"no {kind} output is declared for {code}")
        else:
            self.error(
                node,
                f"{code} could go to {' or '.join(sorted(candidates))}; "
                f"write e.g. {sorted(candidates)[0]}.{code}",
            )
        return None

    def unknown_output(self, name: str) -> str:
        known = ", ".join(sorted(self.outputs)) or "none declared"
        return f"unknown output device '{name}' (declared outputs: {known})"

    def check_confusing(self, node: Tree, code: str) -> None:
        if code in CONFUSING_BUTTONS:
            self.warn(node, CONFUSING_BUTTONS[code])

    def keys(self, keys: Tree, path: str) -> list[dict] | None:
        result = []
        for index, ref in enumerate(keys.children):
            key = self.output_ref(ref, f"{path}[{index}]")
            if key is None:
                return None
            result.append(key)
        return result

    # -- mappings ------------------------------------------------------------------

    def compile_map(self, stmt: Tree, index: int, layer: str | None = None) -> dict | None:
        ref, *rest = stmt.children
        block = rest[-1]
        modifiers = next((c for c in rest if isinstance(c, Tree) and c.data == "modifiers"), None)
        threshold = next((c for c in rest if isinstance(c, Tree) and c.data == "threshold"), None)
        as_name = next((c for c in rest if isinstance(c, Tree) and c.data == "as_name"), None)
        path = f"mappings[{index}]"
        self.record(path, stmt)

        trigger = self.trigger(ref, modifiers, f"{path}.input", threshold)
        if trigger is None:
            return None
        if as_name is not None:
            name_token = as_name.children[0]
            if not self.check_name(name_token, "a mapping name"):
                return None
            mapping_id = str(name_token)
        else:
            mapping_id = self.default_id(ref, trigger, threshold)
            if layer is not None:
                mapping_id = f"{layer}:{mapping_id}"  # §5.6 rule 7

        statements = self.expand_calls(list(block.children))
        if not statements and not block.children:
            self.error(block, "this mapping does nothing; add statements")
            return None
        if not statements:
            return None
        if any(s.data == "disable" for s in statements):
            if len(statements) > 1:
                first = next(s for s in statements if s.data == "disable")
                self.error(first, "'disable' must be the only statement of its mapping")
                return None
            return self.in_layer({"id": mapping_id, "input": trigger, "disable": True}, layer)
        options, body, release_stmt = self.split_options(statements)
        mapping: dict = {"id": mapping_id, "input": trigger}
        if options.pop("keep_modifiers", False):
            mapping["keep_modifiers"] = True

        if (
            not options
            and release_stmt is None
            and body
            and all(s.data in ("hold", "axis") for s in body)
        ):
            outputs = self.plain_outputs(body, f"{path}.outputs")
            if outputs is None:
                return None
            mapping["outputs"] = outputs
            return self.in_layer(mapping, layer)

        toggles = [s for s in body if s.data == "toggle"]
        if toggles and len(body) > 1:
            self.error(toggles[0], "'toggle' must be the only statement of its mapping")
        macro_path = f"{path}.outputs[0].macro"
        self.record(f"{path}.outputs[0]", block)
        self.record(macro_path, block)
        steps = self.steps(body, f"{macro_path}.steps", top=True)
        if not body:
            steps = [{"wait_ms": 0}]  # only `on release` statements
        macro: dict = {"steps": steps, **options}
        if release_stmt is not None:
            macro["release_steps"] = self.steps(
                list(release_stmt.children[0].children), f"{macro_path}.release_steps"
            )
        mapping["outputs"] = [{"macro": macro}]
        return self.in_layer(mapping, layer)

    @staticmethod
    def in_layer(mapping: dict, layer: str | None) -> dict:
        if layer is not None:
            mapping["layer"] = layer
        return mapping

    def trigger(
        self, ref: Tree, modifiers: Tree | None, path: str, threshold: Tree | None = None
    ) -> dict | None:
        tokens = [str(t) for t in ref.children]
        device: str | None = None  # without a device: every input (§5.1)
        if len(tokens) == 2:
            device, code = tokens
            if device not in self.inputs:
                known = ", ".join(sorted(self.inputs)) or "none declared"
                self.error(ref, f"unknown input device '{device}' (declared inputs: {known})")
                return None
        else:
            code = tokens[0]
        if code in OUTPUT_ALIASES:
            self.error(ref, f"'{code}' is a modifier and cannot be a trigger")
            return None
        if code.startswith("ABS_"):
            if threshold is None:
                self.error(ref, f"an axis needs 'above' or 'below', e.g. {code} above 0.5")
                return None
            direction, value = threshold.children
            trigger: dict = {"type": "axis", "code": code, str(direction): float(str(value))}
            self.record(f"{path}.{direction}", threshold)
        elif threshold is not None:
            self.error(threshold, "'above' and 'below' are only for axes (ABS_*)")
            return None
        elif code.startswith(("KEY_", "BTN_")):
            self.check_confusing(ref, code)
            trigger = {"type": "key" if code.startswith("KEY_") else "button", "code": code}
        else:
            self.error(ref, f"a trigger must be a KEY_*, BTN_* or ABS_* name, got '{code}'")
            return None
        if device is not None:
            trigger["device"] = device
        self.record(path, ref)
        self.record(f"{path}.code", ref)
        if modifiers is not None:
            names = [str(t) for t in modifiers.children]
            trigger["modifiers"] = "ignore" if names == ["ignore"] else names
            self.record(f"{path}.modifiers", modifiers)
        return trigger

    def default_id(self, ref: Tree, trigger: dict, threshold: Tree | None = None) -> str:
        text = ".".join(str(t) for t in ref.children)
        if threshold is not None:
            text += "".join(f"_{t}" for t in threshold.children)  # pad.ABS_RZ_above_0.5
        modifiers = trigger.get("modifiers")
        if modifiers == "ignore":
            return f"{text}+ignore"
        if modifiers:
            return "+".join([text, *modifiers])
        return text

    def split_options(self, statements: list[Tree]) -> tuple[dict, list[Tree], Tree | None]:
        options: dict = {}
        body: list[Tree] = []
        release_stmt: Tree | None = None
        for stmt in statements:
            if stmt.data in OPTION_STATEMENTS:
                if body or release_stmt is not None:
                    self.error(stmt, "options must come before all statements of the mapping")
                    continue
                self.option(stmt, options)
            elif stmt.data == "on_release":
                if release_stmt is not None:
                    self.error(stmt, "only one 'on release' block per mapping")
                release_stmt = stmt
            else:
                body.append(stmt)
        return options, body, release_stmt

    def option(self, stmt: Tree, options: dict) -> None:
        if stmt.data == "opt_cancel":
            options["on_release"] = "cancel"
        elif stmt.data == "opt_restart":
            options["on_retrigger"] = "restart"
        elif stmt.data == "opt_keep":
            options["keep_modifiers"] = True
        else:
            name_token, value_tree = stmt.children
            name = str(name_token)
            kind, value = self.value(value_tree)
            if name == "key_pause" and kind == "duration":
                options["key_pause_ms"] = value
            elif name == "max_run" and kind == "duration":
                options["max_run_ms"] = value
            elif name == "max_run" and (kind, value) == ("name", "none"):
                options["max_run_ms"] = None
            elif name in ("key_pause", "max_run"):
                self.error(
                    value_tree,
                    f"'{name}' needs a duration such as 10ms"
                    + (" or 'none'" if name == "max_run" else ""),
                )
            else:
                self.error(
                    name_token,
                    f"unknown option '{name}' (options: cancel on release, "
                    "restart on press, keep modifiers, key_pause, max_run); "
                    "to assign a variable write 'name = value'",
                )

    def plain_outputs(self, body: list[Tree], path: str) -> list[dict] | None:
        outputs: list[dict] = []
        for stmt in body:
            if stmt.data == "hold":
                for ref in stmt.children[0].children:
                    key = self.output_ref(ref, f"{path}[{len(outputs)}]")
                    if key is None:
                        return None
                    kind = "key" if key["code"].startswith("KEY_") else "button"
                    outputs.append({"device": key["device"], "type": kind, "code": key["code"]})
            else:
                axis = self.axis_values(stmt, f"{path}[{len(outputs)}]")
                if axis is None:
                    return None
                device, code, value, attack, release = axis
                outputs.append(
                    {
                        "device": device,
                        "type": "axis",
                        "code": code,
                        "value": value,
                        "attack_ms": attack,
                        "release_ms": release,
                    }
                )
        return outputs

    def axis_values(self, stmt: Tree, path: str) -> tuple | None:
        """`axis REF { … }` or `axis REF V (attack D, release D)`."""
        ref, *rest = stmt.children
        target = self.axis_ref(ref)
        if target is None:
            return None
        self.record(path, stmt)
        value: object = None
        timing = {"attack": 0.0, "release": 0.0}
        if rest and isinstance(rest[0], Tree) and rest[0].data == "props":
            for prop in rest[0].children:
                name, values = self.prop(prop)
                if name == "target" and len(values) == 1 and values[0][0] in ("int", "float"):
                    value = float(values[0][1])  # type: ignore[arg-type]
                elif name in timing:
                    ms = self.single_duration(values, prop, name)
                    if ms is not None:
                        timing[name] = ms
                else:
                    self.error(prop, f"unknown axis property '{name}' (target, attack, release)")
            if value is None:
                self.error(stmt, "axis needs 'target = <number>'")
                return None
        else:
            value = float(str(rest[0]))
            if len(rest) > 1:
                for option in rest[1].children:
                    name = str(option.children[0])
                    if name not in timing:
                        self.error(option, f"unknown axis option '{name}' (attack, release)")
                        continue
                    ms = self.duration(option.children[1])
                    if not isinstance(ms, float):
                        self.error(option, f"'{name}' needs a duration literal")
                        continue
                    timing[name] = ms
        return target[0], target[1], value, timing["attack"], timing["release"]

    # -- step lists ------------------------------------------------------------------

    def steps(self, statements: list[Tree], path: str, top: bool = False) -> list[dict]:
        statements = self.expand_calls(statements)
        result: list[dict] = []
        index = 0
        while index < len(statements):
            stmt = statements[index]
            step_path = f"{path}[{len(result)}]"
            if stmt.data == "gesture":
                end = index
                while end < len(statements) and statements[end].data == "gesture":
                    end += 1
                step = self.gestures(statements[index:end], step_path)
                index = end
            elif stmt.data in ("hold", "axis", "hold_layer") and index + 1 < len(statements):
                # Non-blocking: hold in one branch, the rest runs alongside.
                held = self.step(stmt, f"{step_path}.parallel[0][0]")
                rest = self.steps(statements[index + 1 :], f"{step_path}.parallel[1]")
                self.record(step_path, stmt)
                step = {"parallel": [[held], rest]} if held is not None else None
                index = len(statements)
            else:
                if stmt.data in OPTION_STATEMENTS:
                    self.error(stmt, "options are only allowed at the start of a mapping")
                    step = None
                elif stmt.data == "on_release":
                    self.error(stmt, "'on release' is only allowed directly in a mapping")
                    step = None
                elif stmt.data == "toggle" and not top:
                    self.error(stmt, "'toggle' must be the only statement of its mapping")
                    step = None
                else:
                    step = self.step(stmt, step_path)
                index += 1
            if step is not None:
                result.append(step)
        return result

    def block_steps(self, block: Tree, path: str) -> list[dict]:
        return self.steps(list(block.children), path)

    def step(self, stmt: Tree, path: str) -> dict | None:
        self.record(path, stmt)
        kind = stmt.data
        handler = getattr(self, f"step_{kind}", None)
        if handler is None:  # pragma: no cover - grammar and compiler disagree
            self.error(stmt, f"unsupported statement '{kind}'")
            return None
        return handler(stmt, path)

    def key_options(self, stmt: Tree, step: dict, path: str) -> None:
        if len(stmt.children) < 2:
            return
        for option in stmt.children[1].children:
            name = str(option.children[0])
            if name != "pause":
                self.error(option, f"unknown option '{name}' (only 'pause' is allowed here)")
                continue
            duration = self.duration(option.children[1])
            if duration is not None:
                step["pause_ms"] = duration
                self.record(f"{path}.pause_ms", option)

    def key_step(self, stmt: Tree, path: str, verb: str) -> dict | None:
        keys = self.keys(stmt.children[0], f"{path}.{verb}")
        if keys is None:
            return None
        step: dict = {verb: keys}
        self.key_options(stmt, step, path)
        return step

    def step_tap(self, stmt: Tree, path: str) -> dict | None:
        return self.key_step(stmt, path, "tap")

    def step_press(self, stmt: Tree, path: str) -> dict | None:
        return self.key_step(stmt, path, "press")

    def step_release(self, stmt: Tree, path: str) -> dict | None:
        return self.key_step(stmt, path, "release")

    def step_hold(self, stmt: Tree, path: str) -> dict | None:
        keys = self.keys(stmt.children[0], f"{path}.hold_keys")
        return {"hold_keys": keys} if keys is not None else None

    def step_with(self, stmt: Tree, path: str) -> dict | None:
        keys = self.keys(stmt.children[0], f"{path}.with_keys")
        steps = self.block_steps(stmt.children[1], f"{path}.steps")
        return {"with_keys": keys, "steps": steps} if keys is not None else None

    def step_axis(self, stmt: Tree, path: str) -> dict | None:
        axis = self.axis_values(stmt, path)
        if axis is None:
            return None
        device, code, value, attack, release = axis
        return {
            "hold_axis": code,
            "device": device,
            "value": value,
            "attack_ms": attack,
            "release_ms": release,
        }

    def step_move(self, stmt: Tree, path: str) -> dict | None:
        ref, number, *over = stmt.children
        target = self.axis_ref(ref)
        if target is None:
            return None
        step: dict = {"axis": target[1], "device": target[0], "to": float(str(number))}
        if over:
            duration = self.duration(over[0])
            if duration is not None:
                step["over_ms"] = duration
        return step

    def step_wait(self, stmt: Tree, path: str) -> dict | None:
        duration = self.duration(stmt.children[0])
        return {"wait_ms": duration} if duration is not None else None

    def step_repeat(self, stmt: Tree, path: str) -> dict | None:
        count_token, block = stmt.children
        text = str(count_token)
        if count_token.type == "NAME":
            if self.var_types.get(text) != "int":
                self.error(count_token, self.var_problem(text, "an int variable"))
                return None
            count: object = {"var": text}
        elif "." in text or text.startswith("-"):
            self.error(count_token, f"repeat needs a whole number from 0 to 10000, got {text}")
            return None
        else:
            count = int(text)
        return {"repeat": count, "steps": self.block_steps(block, f"{path}.steps")}

    def step_while_held(self, stmt: Tree, path: str) -> dict | None:
        return {"while_held": self.block_steps(stmt.children[0], f"{path}.while_held")}

    def step_toggle(self, stmt: Tree, path: str) -> dict | None:
        return {"toggle": self.block_steps(stmt.children[0], f"{path}.toggle")}

    def step_disable(self, stmt: Tree, path: str) -> dict | None:
        self.error(stmt, "'disable' must be the only statement of its mapping")
        return None

    def step_hold_layer(self, stmt: Tree, path: str) -> dict | None:
        name = self.layer_ref(stmt.children[0])
        return {"layer": name, "action": "hold"} if name else None

    def step_layer_switch(self, stmt: Tree, path: str) -> dict | None:
        name_token, action = stmt.children
        name = self.layer_ref(name_token)
        return {"layer": name, "action": str(action.children[0])} if name else None

    def layer_ref(self, token: Token) -> str | None:
        name = str(token)
        if name not in self.layer_names:
            known = ", ".join(sorted(self.layer_names)) or "none defined"
            self.error(token, f"unknown layer '{name}' (layers: {known})")
            return None
        return name

    def step_parallel(self, stmt: Tree, path: str) -> dict | None:
        branches = [
            self.block_steps(branch.children[0], f"{path}.parallel[{i}]")
            for i, branch in enumerate(stmt.children)
        ]
        if not branches:
            self.error(stmt, "parallel needs at least one branch")
            return None
        return {"parallel": branches}

    def step_assign(self, stmt: Tree, path: str) -> dict | None:
        name_token, value_tree = stmt.children
        value = self.typed(str(name_token), value_tree)
        if value is None:
            return None
        return {"set": {"var": str(name_token), "value": value}}

    def step_augassign(self, stmt: Tree, path: str) -> dict | None:
        name_token, op, value_tree = stmt.children
        name = str(name_token)
        kind = self.var_types.get(name)
        if kind not in ("int", "float", "duration"):
            self.error(name_token, self.var_problem(name, "an int, float or duration variable"))
            return None
        value = self.typed(name, value_tree)
        if value is None:
            return None
        return {"add": {"var": name, "value": -value if str(op) == "-=" else value}}

    # -- conditions -------------------------------------------------------------------

    def step_if_stmt(self, stmt: Tree, path: str) -> dict | None:
        cond, block, *rest = stmt.children
        return self.conditional(cond, block, rest, path)

    def conditional(self, cond: Tree, block: Tree, rest: list[Tree], path: str) -> dict | None:
        """Compile `if cond { block } else-if… else…` into a condition step."""
        negate = False
        while cond.data == "cond_not":
            negate = not negate
            cond = cond.children[0]
        head = self.condition_head(cond)
        if head is None:
            return None
        kind, fields, swap = head
        if negate:
            swap = not swap
        then_key, else_key = ("else", "then") if swap else ("then", "else")
        body: dict = dict(fields)
        body[then_key] = self.block_steps(block, f"{path}.{kind}.{then_key}")
        if rest:
            first, *more = rest
            if first.data == "else_block":
                body[else_key] = self.block_steps(first.children[0], f"{path}.{kind}.{else_key}")
            else:  # else_if
                nested_path = f"{path}.{kind}.{else_key}[0]"
                self.record(nested_path, first)
                nested = self.conditional(first.children[0], first.children[1], more, nested_path)
                body[else_key] = [nested] if nested is not None else []
        return {kind: body}

    def condition_head(self, cond: Tree) -> tuple[str, dict, bool] | None:
        """(step kind, fields, swap branches) for one condition."""
        if cond.data in ("cond_tap", "cond_single"):
            kind = "if_tap" if cond.data == "cond_tap" else "if_single"
            fields: dict = {}
            if cond.children:
                timeout = self.duration(cond.children[0].children[1])
                if not isinstance(timeout, float):
                    self.error(cond, "'within' needs a duration literal")
                    return None
                fields["timeout_ms"] = timeout
            return kind, fields, False
        if cond.data in ("cond_eq", "cond_ne"):
            name_token, value_tree = cond.children
            name = str(name_token)
            if name not in self.var_types:
                self.error(name_token, self.var_problem(name, "a variable"))
                return None
            value = self.typed(name, value_tree)
            if value is None:
                return None
            return "if_eq", {"var": name, "value": value}, cond.data == "cond_ne"
        if cond.data == "cond_layer":
            layer = self.layer_ref(cond.children[0])
            return ("if_layer", {"layer": layer}, False) if layer else None
        name_token = cond.children[0]
        name = str(name_token)
        if name in LEDS:
            return "if_led", {"led": name}, False
        if self.var_types.get(name) == "bool":
            return "if_eq", {"var": name, "value": True}, False
        if name in self.var_types:
            self.error(
                name_token,
                f"'{name}' is a {self.var_types[name]} variable; compare it, e.g. 'if {name} == …'",
            )
        else:
            self.error(
                name_token,
                f"unknown condition '{name}' (a bool variable, tap, single, "
                "capslock, numlock or scrolllock)",
            )
        return None

    def gestures(self, statements: list[Tree], path: str) -> dict | None:
        handlers: dict[str, Tree] = {}
        windows: set[float] = set()
        for stmt in statements:
            name_tree, *rest = stmt.children
            name = str(name_tree.children[0])
            block = rest[-1]
            if name not in ("tap", "double_tap", "long_press"):
                self.error(stmt, f"unknown gesture '{name}' (tap, double_tap, long_press)")
                return None
            if name in handlers:
                self.error(stmt, f"'on {name}' appears twice in this group")
                return None
            handlers[name] = block
            if len(rest) == 2:
                window = rest[0]
                word = str(window.children[0])
                expected = "after" if name == "long_press" else "within"
                if word != expected:
                    self.error(window, f"use '{expected}' with 'on {name}'")
                    return None
                ms = self.duration(window.children[1])
                if not isinstance(ms, float):
                    self.error(window, f"'{word}' needs a duration literal")
                    return None
                windows.add(ms)
        if len(windows) > 1:
            self.error(statements[0], "all handlers of a gesture group must use the same window")
            return None
        window_ms = windows.pop() if windows else DEFAULT_GESTURE_WINDOW_MS
        self.record(path, statements[0])

        def body(name: str, body_path: str) -> list[dict]:
            return self.block_steps(handlers[name], body_path) if name in handlers else []

        outer_then = f"{path}.if_tap.then"
        if "double_tap" in handlers:
            inner = {
                "if_tap": {
                    "then": body("double_tap", f"{outer_then}[0].if_tap.then"),
                    "else": body("tap", f"{outer_then}[0].if_tap.else"),
                    "timeout_ms": window_ms,
                }
            }
            then_steps = [inner]
        else:
            then_steps = body("tap", outer_then)
        return {
            "if_tap": {
                "then": then_steps,
                "else": body("long_press", f"{path}.if_tap.else"),
                "timeout_ms": window_ms,
            }
        }

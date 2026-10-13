"""`inpmap input-config`: choose input devices interactively and add them to a file.

Backend-independent: devices come in as :class:`Device` values (on Linux
from sysfs, see backends/linux_setup.py), identification by key press and
terminal I/O are passed in as functions, so everything here is testable
without devices.

The configuration file is edited as text: new ``input`` blocks are inserted
after the last existing one (or after ``version``), and nothing else is
touched, so the user's formatting and comments stay as they are.
"""

from __future__ import annotations

import os
import re
import tempfile
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from pathlib import Path

from . import codes
from .dsl.compiler import RESERVED
from .dsl.parser import parse

KIND_ORDER = ("keyboard", "gamepad", "mouse", "touchpad", "other")
_NAME_PATTERN = re.compile(r"[A-Za-z_][A-Za-z0-9_]*\Z")
_SUGGESTED = {"keyboard": "kbd", "gamepad": "pad", "mouse": "mouse", "touchpad": "touchpad"}


def _code(name: str) -> int:
    code = codes.code_from_name(name)
    assert code is not None, name
    return code


KEY_A, BTN_LEFT = _code("KEY_A"), _code("BTN_LEFT")
ABS_X, ABS_MT_POSITION_X, REL_X = 0x00, 0x35, 0x00


@dataclass(frozen=True)
class Device:
    """One event node of a physical input device."""

    node: str  # "event7"
    name: str
    group: tuple[str, ...]  # same value for all nodes of one physical device
    kind: str  # one of KIND_ORDER
    key_count: int
    links: tuple[str, ...] = ()  # stable links, /dev/input/by-id first
    vendor: str = ""
    product: str = ""
    group_title: str = ""  # name of the physical device, if known

    @property
    def path(self) -> str:
        return f"/dev/input/{self.node}"


def classify(keys: frozenset[int], abs_axes: frozenset[int], rel: frozenset[int]) -> str:
    """Rough device type, in the order Input Remapper uses (first match wins)."""
    if abs_axes and ABS_MT_POSITION_X in abs_axes:
        return "touchpad"
    if ABS_X in abs_axes and any(codes.is_gamepad_button(code) for code in keys):
        return "gamepad"
    if BTN_LEFT in keys and REL_X in rel:
        return "mouse"
    if KEY_A in keys:
        return "keyboard"
    return "other"


def group_key(bustype: str, vendor: str, product: str, uniq: str, phys: str) -> tuple[str, ...]:
    """Identity of the physical device a node belongs to.

    Like Input Remapper: the part of ``phys`` before "/input" is the same for
    all interfaces of one USB device; ``uniq`` (serial, Bluetooth address)
    separates identical devices that share a ``phys`` prefix.
    """
    return (bustype, vendor, product, uniq, phys.split("/input")[0])


@dataclass
class Group:
    title: str
    devices: list[Device]


def group_devices(devices: Iterable[Device]) -> list[Group]:
    """Group nodes per physical device, in order of their first node number."""
    groups: dict[tuple[str, ...], list[Device]] = {}
    for device in sorted(devices, key=lambda d: _node_number(d.node)):
        groups.setdefault(device.group, []).append(device)
    return [
        Group(members[0].group_title or group_title(d.name for d in members), members)
        for members in groups.values()
    ]


def _node_number(node: str) -> int:
    digits = re.sub(r"\D", "", node)
    return int(digits) if digits else -1


def group_title(names: Iterable[str]) -> str:
    """The name most others extend ("Pad" for "Pad Keyboard", "Pad Mouse"), else the shortest."""
    unique = sorted(set(names), key=len)

    def extended_by(name: str) -> int:
        return sum(1 for other in unique if other != name and other.startswith(name))

    best = max(unique, key=extended_by)
    return best if extended_by(best) else unique[0]


def selector_for(device: Device, all_devices: Iterable[Device]) -> tuple[str, str]:
    """("path", link) or ("name", name): the most stable way to find the device.

    A /dev/input/by-id link survives replugging into another port; a name
    works if no other device has it; a by-path link depends on the port.
    """
    by_id = [link for link in device.links if "/by-id/" in link]
    if by_id:
        return "path", by_id[0]
    if sum(1 for other in all_devices if other.name == device.name) == 1:
        return "name", device.name
    if device.links:
        return "path", device.links[0]
    return "path", device.path


def suggest_name(kind: str, taken: Iterable[str]) -> str:
    base = _SUGGESTED.get(kind, "dev")
    taken = set(taken)
    if base not in taken:
        return base
    number = 2
    while f"{base}{number}" in taken:
        number += 1
    return f"{base}{number}"


def name_problem(name: str, taken: Iterable[str]) -> str | None:
    if not _NAME_PATTERN.match(name):
        return f"'{name}' is not a valid name (letters, digits and _, not starting with a digit)"
    if name in RESERVED:
        return f"'{name}' is a reserved word"
    if name in set(taken):
        return f"'{name}' is already used"
    return None


# -- the configuration file ------------------------------------------------------------------


@dataclass(frozen=True)
class ExistingInput:
    name: str
    selector: str  # "path" or "name"
    value: str


@dataclass
class ConfigFile:
    """The text of an existing file (or None for a new one) and its inputs."""

    path: str
    text: str | None
    inputs: list[ExistingInput] = field(default_factory=list)
    insert_at: int = 0  # character offset where new input blocks go

    @classmethod
    def load(cls, path: str) -> ConfigFile:
        """Read and parse ``path``; a missing file means a new configuration.

        Raises DslSyntaxError if the existing file cannot be parsed, and
        ValueError if it has no `version` statement to insert after.
        """
        try:
            text = Path(path).read_text(encoding="utf-8")
        except FileNotFoundError:
            return cls(path, None)
        tree = parse(text, path)
        inputs: list[ExistingInput] = []
        anchor = None
        for stmt in tree.children:
            if stmt.data == "version" and anchor is None:
                anchor = stmt
            elif stmt.data == "input_def":
                anchor = stmt
                inputs.append(_existing_input(stmt))
        if anchor is None:
            raise ValueError(f"{path}: the file must start with 'version 1'")
        return cls(path, text, inputs, _after_line(text, anchor.meta.end_pos))

    def mark(self, devices: list[Device]) -> dict[str, str]:
        """node -> input name, for devices the file already selects."""
        marks: dict[str, str] = {}
        for existing in self.inputs:
            for device in devices:
                if existing.selector == "path":
                    if os.path.basename(os.path.realpath(existing.value)) == device.node:
                        marks[device.node] = existing.name
                elif existing.value == device.name:
                    marks[device.node] = existing.name
        return marks

    def with_inputs(self, blocks: list[str]) -> str:
        """The file text with the new input blocks added."""
        if self.text is None:
            return new_file_text(blocks)
        insertion = "".join(f"\n{block}\n" for block in blocks)
        return self.text[: self.insert_at] + insertion + self.text[self.insert_at :]


def _existing_input(stmt) -> ExistingInput:
    name = str(stmt.children[0])
    for prop in stmt.children[1].children:
        key = str(prop.children[0].children[0])
        if key in ("path", "name") and len(prop.children) == 2:
            value_tree = prop.children[1]
            if value_tree.data == "v_string":
                literal = str(value_tree.children[0])
                return ExistingInput(name, key, _unquote(literal))
    return ExistingInput(name, "", "")


def _unquote(literal: str) -> str:
    body = literal[1:-1]
    return re.sub(r"\\(.)", lambda m: {"n": "\n", "t": "\t"}.get(m.group(1), m.group(1)), body)


def _after_line(text: str, offset: int) -> int:
    """Offset just after the line that contains ``offset`` (keeps trailing comments)."""
    newline = text.find("\n", offset)
    return len(text) if newline == -1 else newline + 1


def input_block(name: str, selector: tuple[str, str]) -> str:
    key, value = selector
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'input {name} {{\n    {key} = "{escaped}"\n}}'


def new_file_text(blocks: list[str]) -> str:
    body = "\n\n".join(blocks)
    return (
        "# InpMap configuration, created by `inpmap input-config`.\n"
        "# Reference: docs/configuration.md\n"
        "version 1\n\n"
        f"{body}\n\n"
        "output keyboard { type = keyboard }\n"
        "output gamepad { type = gamepad }\n\n"
        "# Write your mappings here, for example:\n"
        "# map KEY_CAPSLOCK { tap KEY_ESC }\n"
    )


def write_atomically(path: str, text: str) -> str | None:
    """Write ``text`` to ``path`` via a temporary file; keep the old file as .bak.

    Returns the backup path, or None if the file did not exist.
    """
    target = Path(path)
    backup = None
    if target.exists():
        backup = str(target) + ".bak"
        Path(backup).write_bytes(target.read_bytes())
    directory = target.parent if str(target.parent) else Path(".")
    handle, temporary = tempfile.mkstemp(prefix=f".{target.name}.", dir=directory)
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as out:
            out.write(text)
        if target.exists():
            os.chmod(temporary, target.stat().st_mode & 0o777)
        os.replace(temporary, target)
    except BaseException:
        if os.path.exists(temporary):
            os.unlink(temporary)
        raise
    return backup


# -- the interactive session -------------------------------------------------------------------

HELP = (
    "Type a number to select or deselect a device, optionally with a name (e.g. '3 pad').\n"
    "i = identify a device by pressing a key on it, l = list again,\n"
    "w = write the selected devices into the file and quit, q = quit without changes."
)


@dataclass
class Session:
    """State and commands of one `inpmap input-config` run.

    ``identify`` waits for a key press on one of the given devices and
    returns it (or None); ``check`` returns the problems of a text (empty
    if it is valid).
    """

    file: ConfigFile
    devices: list[Device]
    say: Callable[[str], None]
    identify: Callable[[list[Device]], Device | None]
    check: Callable[[str], list[str]]
    numbered: list[Device] = field(default_factory=list)
    marks: dict[str, str] = field(default_factory=dict)
    selected: dict[str, str] = field(default_factory=dict)  # node -> new input name

    def __post_init__(self) -> None:
        self.numbered = [d for group in group_devices(self.devices) for d in group.devices]
        self.marks = self.file.mark(self.devices)

    # Returns False when the session ends.
    def command(self, line: str) -> bool:
        words = line.split()
        if not words:
            return True
        head = words[0].lower()
        if head == "q":
            self.say("No changes written.")
            return False
        if head == "w":
            return not self.write()
        if head == "l":
            self.show()
        elif head == "i":
            self.identify_one()
        elif head in ("?", "h", "help"):
            self.say(HELP)
        elif words[0].isdigit():
            self.toggle(int(words[0]), words[1] if len(words) > 1 else None)
        else:
            self.say(f"Unknown command '{line.strip()}'.\n{HELP}")
        return True

    def show(self) -> None:
        number = 0
        lines = []
        for group in group_devices(self.devices):
            ids = f" ({group.devices[0].vendor}:{group.devices[0].product})"
            lines.append(f"  {group.title}{ids if group.devices[0].vendor else ''}")
            for device in group.devices:
                number += 1
                lines.append(f"    {number:>3}  {self._mark(device):<12} {self._line(device)}")
        self.say("\n".join(lines) if lines else "  (no input devices with keys or buttons)")

    def _mark(self, device: Device) -> str:
        if device.node in self.marks:
            return f"[{self.marks[device.node]}]"
        if device.node in self.selected:
            return f"+ {self.selected[device.node]}"
        return ""

    @staticmethod
    def _line(device: Device) -> str:
        unit = "buttons" if device.kind == "gamepad" else "keys"
        return f"{device.kind:<9} {device.key_count:>4} {unit:<8} {device.name}"

    def toggle(self, number: int, name: str | None) -> None:
        if not 1 <= number <= len(self.numbered):
            self.say(f"There is no device {number}.")
            return
        device = self.numbered[number - 1]
        if device.node in self.marks:
            self.say(f"{number} is already in the file as '{self.marks[device.node]}'.")
            return
        if device.node in self.selected and name is None:
            del self.selected[device.node]
            self.say(f"{number} deselected.")
            return
        taken = [e.name for e in self.file.inputs] + [
            n for node, n in self.selected.items() if node != device.node
        ]
        if name is None:
            name = suggest_name(device.kind, taken)
        problem = name_problem(name, taken)
        if problem:
            self.say(problem)
            return
        self.selected[device.node] = name
        self.say(f"{number} selected as '{name}': {device.name}")

    def identify_one(self) -> None:
        candidates = [d for d in self.numbered if d.node not in self.marks]
        self.say("Press a key or button on the device you want (Ctrl+C to cancel) ...")
        device = self.identify(candidates)
        if device is None:
            self.say("No key press recognised.")
            return
        number = self.numbered.index(device) + 1
        self.say(f"That was {number}: {device.name} ({device.kind}).")
        if device.node not in self.selected:
            self.toggle(number, None)

    def write(self) -> bool:
        """Write the selection; True if the session is over."""
        if not self.selected:
            self.say("Nothing selected; nothing to write. (q quits)")
            return False
        blocks = [
            input_block(self.selected[d.node], selector_for(d, self.devices))
            for d in self.numbered
            if d.node in self.selected
        ]
        text = self.file.with_inputs(blocks)
        backup = write_atomically(self.file.path, text)
        added = "\n\n".join(blocks)
        self.say(f"Added to {self.file.path}:\n\n{_indent(added)}\n")
        if backup:
            self.say(f"The previous version is in {backup}.")
        problems = self.check(text)
        if not problems:
            self.say("Check: OK.")
        elif self.file.text is None:
            self.say("Now add your mappings, then run `inpmap check` on the file.")
        else:
            self.say("`inpmap check` reports:\n" + "\n".join(f"  {p}" for p in problems))
        return True


def _indent(text: str) -> str:
    return "\n".join(f"    {line}" if line else "" for line in text.splitlines())


def run_session(session: Session, ask: Callable[[str], str]) -> None:
    """Show the devices, then process commands until w or q (or end of input)."""
    session.say(f"Input devices for {session.file.path} (grouped by physical device):\n")
    session.show()
    session.say("\n" + HELP)
    while True:
        try:
            line = ask("> ")
        except EOFError:
            session.say("No changes written.")
            return
        if not session.command(line):
            return

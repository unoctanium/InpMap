"""Linux setup helpers: list devices from sysfs, generate narrowly scoped udev rules.

The rules use systemd-logind's ``uaccess`` tag, which grants an ACL to the
user of the active local session only (the mechanism Steam and KDE Connect
use for /dev/uinput). Input devices are matched by their kernel name plus USB
vendor/product IDs, so only the configured devices become accessible, not
every keyboard. ``uaccess`` is applied by 73-seat-late.rules, so the rules
file must sort before it (70-...).

Device attributes are read from sysfs, which is world-readable, so rules can
be generated before the user has any device access.
"""

from __future__ import annotations

import os
import struct
from dataclasses import dataclass, field

from ..config import Config
from ..input import InputError
from ..input_config import Device, classify, group_key, group_title
from ..models import InputDeviceSpec

SYSFS_INPUT = "/sys/class/input"
LINK_DIRS = ("/dev/input/by-id", "/dev/input/by-path")
# sysfs capability bitmaps are printed as kernel `unsigned long` words.
_WORD_BITS = struct.calcsize("L") * 8
RULES_PATH = "/etc/udev/rules.d/70-inpmap.rules"
UINPUT_RULE = 'KERNEL=="uinput", SUBSYSTEM=="misc", TAG+="uaccess", OPTIONS+="static_node=uinput"'
OWN_PHYS_PREFIX = "inpmap"
_UNSAFE_CHARS = set('"\\\n\r*?[]')


@dataclass(frozen=True)
class SysfsInput:
    node: str  # e.g. "event7"
    name: str
    vendor: str  # 4 hex digits as in sysfs
    product: str
    phys: str
    bustype: str = ""  # 4 hex digits
    uniq: str = ""  # serial or Bluetooth address, often empty
    keys: frozenset[int] = field(default=frozenset())  # EV_KEY codes
    abs: frozenset[int] = field(default=frozenset())
    rel: frozenset[int] = field(default=frozenset())


def parse_bitmap(text: str) -> frozenset[int]:
    """Decode a sysfs capability bitmap ("1f 0 fffe", most significant word first)."""
    bits: set[int] = set()
    for index, word in enumerate(reversed(text.split())):
        value = int(word, 16)
        bits.update(index * _WORD_BITS + bit for bit in range(_WORD_BITS) if value >> bit & 1)
    return frozenset(bits)


def _read(path: str) -> str:
    with open(path, encoding="utf-8", errors="replace") as handle:
        return handle.read().strip()


def _read_optional(path: str) -> str:
    try:
        return _read(path)
    except FileNotFoundError:
        return ""


def read_sysfs_inputs(root: str = SYSFS_INPUT) -> list[SysfsInput]:
    """List event devices with their identifying attributes."""
    result: list[SysfsInput] = []
    try:
        nodes = sorted(n for n in os.listdir(root) if n.startswith("event"))
    except OSError:
        return result
    for node in nodes:
        base = os.path.join(root, node, "device")

        def caps(kind: str, base: str = base) -> frozenset[int]:
            return parse_bitmap(_read_optional(os.path.join(base, "capabilities", kind)))

        try:
            result.append(
                SysfsInput(
                    node=node,
                    name=_read(os.path.join(base, "name")),
                    vendor=_read(os.path.join(base, "id", "vendor")),
                    product=_read(os.path.join(base, "id", "product")),
                    phys=_read_optional(os.path.join(base, "phys")),
                    bustype=_read_optional(os.path.join(base, "id", "bustype")),
                    uniq=_read_optional(os.path.join(base, "uniq")),
                    keys=caps("key"),
                    abs=caps("abs"),
                    rel=caps("rel"),
                )
            )
        except (OSError, ValueError):
            continue  # device vanished while listing, or unreadable attributes
    return result


def devices_for_input_config(
    inputs: list[SysfsInput] | None = None, links: dict[str, list[str]] | None = None
) -> list[Device]:
    """Devices with keys or buttons, for `inpmap input-config` (no device access needed)."""
    inputs = read_sysfs_inputs() if inputs is None else inputs
    links = symlinks_by_target() if links is None else links

    def key(info: SysfsInput) -> tuple[str, ...]:
        return group_key(info.bustype, info.vendor, info.product, info.uniq, info.phys)

    # Titles from all nodes of a device, also those without keys: the node
    # carrying the plain product name often has none (e.g. a gamepad's
    # motion sensor node).
    names: dict[tuple[str, ...], list[str]] = {}
    for info in inputs:
        names.setdefault(key(info), []).append(info.name)
    devices = []
    for info in inputs:
        if not info.keys or info.phys.startswith(OWN_PHYS_PREFIX):
            continue
        node_links = links.get(f"/dev/input/{info.node}", [])
        devices.append(
            Device(
                node=info.node,
                name=info.name,
                group=key(info),
                group_title=group_title(names[key(info)]),
                kind=classify(info.keys, info.abs, info.rel),
                key_count=len(info.keys),
                links=tuple(sorted(node_links, key=lambda link: "/by-id/" not in link)),
                vendor=info.vendor,
                product=info.product,
            )
        )
    return devices


def symlinks_by_target(dirs: tuple[str, ...] = LINK_DIRS) -> dict[str, list[str]]:
    """Stable links (by-id, by-path) per real device node path."""
    links: dict[str, list[str]] = {}
    for directory in dirs:
        try:
            entries = sorted(os.scandir(directory), key=lambda e: e.name)
        except OSError:
            continue
        for entry in entries:
            if entry.is_symlink():
                links.setdefault(os.path.realpath(entry.path), []).append(entry.path)
    return links


def resolve(spec: InputDeviceSpec, inputs: list[SysfsInput]) -> SysfsInput:
    """Find the currently connected device a config selector refers to."""
    if spec.path is not None:
        node = os.path.basename(os.path.realpath(spec.path))
        for info in inputs:
            if info.node == node:
                return info
        raise InputError(
            f"input '{spec.id}': {spec.path} is not connected; plug it in to generate its rule"
        )
    matches = [i for i in inputs if i.name == spec.name and not i.phys.startswith(OWN_PHYS_PREFIX)]
    if not matches:
        raise InputError(
            f"input '{spec.id}': no connected device named '{spec.name}'; "
            "plug it in to generate its rule"
        )
    return matches[0]


def device_rule(info: SysfsInput) -> str:
    if _UNSAFE_CHARS & set(info.name):
        raise InputError(
            f"device name {info.name!r} contains characters that cannot be used in a udev "
            "match; write the rule by hand"
        )
    return (
        f'SUBSYSTEM=="input", KERNEL=="event*", ATTRS{{name}}=="{info.name}", '
        f'ATTRS{{id/vendor}}=="{info.vendor}", ATTRS{{id/product}}=="{info.product}", '
        'TAG+="uaccess"'
    )


def render_rules(config: Config, inputs: list[SysfsInput], source: str) -> str:
    """Rules granting session access to /dev/uinput and the configured inputs."""
    lines = [
        f"# InpMap udev rules, generated by `inpmap udev-rules {source}`.",
        "# Grants the user of the active local session (systemd-logind 'uaccess')",
        "# access to /dev/uinput and to the configured input devices only.",
        "#",
        f"# Install: sudo install -m 644 70-inpmap.rules {RULES_PATH}",
        "#          sudo udevadm control --reload",
        "#          sudo udevadm trigger --subsystem-match=input --subsystem-match=misc",
        f"# Remove:  sudo rm {RULES_PATH}  (then the same two udevadm commands)",
        "",
        "# Virtual output devices (keyboard, gamepad, forwarding devices)",
        UINPUT_RULE,
    ]
    for device_id, spec in config.inputs.items():
        info = resolve(spec, inputs)
        lines += [
            "",
            f"# Input '{device_id}': {info.name} (currently {info.node})",
            device_rule(info),
        ]
    return "\n".join(lines) + "\n"

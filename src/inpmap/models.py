"""Validated, backend-independent configuration models.

Instances are produced by :mod:`inpmap.config` and never built from raw JSON
elsewhere. Codes are stored as integers (see :mod:`inpmap.codes`), so aliases
such as ``BTN_FACE_DOWN``/``BTN_FACE_DOWN`` compare equal.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import Enum

from .codes import TRIGGER_AXIS_NAMES
from .macros import DEFAULT_KEY_PAUSE_MS, Macro


class OutputKind(Enum):
    """Kind of virtual output device."""

    KEYBOARD = "keyboard"
    GAMEPAD = "gamepad"


class KeyAction(Enum):
    """What happened to a key or button."""

    RELEASE = 0
    PRESS = 1
    REPEAT = 2  # autorepeat while held; not a new press


@dataclass(frozen=True)
class InputEvent:
    """A normalized key/button event from a physical input device.

    Backends translate their native events into this form; the engine never
    sees backend objects.
    """

    device: str
    code: int
    action: KeyAction


@dataclass(frozen=True)
class TouchContact:
    """A finger on a physical touchpad.

    ``slot`` identifies the finger while it touches; ``x`` and ``y`` are
    fractions of the surface, 0.0 (left, top) … 1.0 (right, bottom).
    """

    slot: int
    x: float
    y: float


@dataclass(frozen=True)
class TouchEvent:
    """Every finger on a touchpad after a change, in the order they touched."""

    device: str
    contacts: tuple[TouchContact, ...]


@dataclass(frozen=True)
class TouchPoint:
    """A finger on an output's touchpad: a contact number (0 … 127, new for
    every touch) and its position as in :class:`TouchContact`."""

    id: int
    x: float
    y: float


@dataclass(frozen=True)
class InputDeviceSpec:
    """How to find a physical input device, and where its unmapped input goes.

    Exactly one selector (``name``, ``path``) is set. ``targets`` names the
    output that receives unmapped input of each kind (docs/configuration.md
    §3.4); a kind without a target has nowhere to go. ``own``: the device
    passes through on a virtual device of its own instead (``to = own``).
    """

    id: str
    name: str | None = None
    path: str | None = None
    own: bool = False
    targets: tuple[tuple[OutputKind, str], ...] = ()

    def target(self, kind: OutputKind) -> str | None:
        """The output that receives this device's unmapped input of ``kind``."""
        return dict(self.targets).get(kind)


# Values of `emulate` (configuration.md §3.5).
EMULATE_DUALSENSE_EDGE = "dualsense-edge"
EMULATIONS = (EMULATE_DUALSENSE_EDGE,)


@dataclass(frozen=True)
class OutputDeviceSpec:
    """A virtual output device to create."""

    id: str
    kind: OutputKind
    name: str
    # A real controller the gamepad presents itself as (configuration.md
    # §3.5); None for InpMap's own virtual gamepad.
    emulate: str | None = None


class Modifier(Enum):
    """Modifier groups (docs/configuration.md §5.2)."""

    CTRL = "ctrl"
    SHIFT = "shift"
    ALT = "alt"
    META = "meta"


class Side(Enum):
    EITHER = "either"
    LEFT = "left"
    RIGHT = "right"


# Linux key codes of each modifier group: (left, right).
MODIFIER_KEYS: dict[Modifier, tuple[int, int]] = {
    Modifier.CTRL: (29, 97),  # KEY_LEFTCTRL, KEY_RIGHTCTRL
    Modifier.SHIFT: (42, 54),  # KEY_LEFTSHIFT, KEY_RIGHTSHIFT
    Modifier.ALT: (56, 100),  # KEY_LEFTALT, KEY_RIGHTALT
    Modifier.META: (125, 126),  # KEY_LEFTMETA, KEY_RIGHTMETA
}


@dataclass(frozen=True)
class ModifierRequirement:
    modifier: Modifier
    side: Side = Side.EITHER

    @property
    def name(self) -> str:
        if self.side is Side.EITHER:
            return self.modifier.value
        return f"{self.side.value}_{self.modifier.value}"


@dataclass(frozen=True)
class AxisThreshold:
    """An axis of an input device passing a value, used like a button (§5.5).

    ``value`` is a fraction of the device's range (-1.0 .. 1.0, not 0).
    """

    axis: int  # Linux ABS code
    above: bool
    value: float

    def describe(self) -> str:
        name = TRIGGER_AXIS_NAMES.get(self.axis, f"ABS_{self.axis:#x}")
        return f"{name} {'above' if self.above else 'below'} {self.value:g}"


@dataclass(frozen=True)
class InputTrigger:
    """A key/button on one named physical input device, or on every input.

    ``device`` None means every configured input that has the key; each
    device then runs the mapping independently (docs/configuration.md §5.1).

    ``modifiers`` lists the modifier state required when the key is pressed
    (exactly these, no others); empty means "no modifier held". With
    ``any_modifiers`` the modifier state does not matter.
    """

    device: str | None
    code: int  # for an axis threshold: its virtual key code (see axis_triggers.py)
    modifiers: frozenset[ModifierRequirement] = frozenset()
    any_modifiers: bool = False
    axis: AxisThreshold | None = None

    @property
    def match_key(self) -> tuple:
        """Identity of the trigger for duplicate detection."""
        return (self.device, self.code, self.modifiers, self.any_modifiers)


class OutputMode(Enum):
    """How an output follows its input."""

    HOLD = "hold"  # pressed while the input is held
    TAP = "tap"  # pressed briefly when the input is pressed


@dataclass(frozen=True)
class OutputAction:
    """A key/button on a named virtual output device."""

    device: str
    code: int
    mode: OutputMode = OutputMode.HOLD


@dataclass(frozen=True)
class AxisOutput:
    """A gamepad axis held at ``value`` while the input is held.

    ``value`` is a fraction of the axis range (sticks -1..1, triggers 0..1).
    """

    device: str
    code: int
    value: float
    attack_ms: float = 0.0
    release_ms: float = 0.0


@dataclass(frozen=True)
class MappingRule:
    """One input mapped to key outputs, axis outputs and/or macros."""

    id: str
    trigger: InputTrigger
    outputs: tuple[OutputAction, ...] = ()
    consume: bool = True
    description: str | None = None
    axes: tuple[AxisOutput, ...] = ()
    macros: tuple[Macro, ...] = ()
    keep_modifiers: bool = False
    disabled: bool = False  # `disable`: the key is suppressed, nothing is sent
    layer: str | None = None  # None: the base, always active (§5.6)


@dataclass(frozen=True)
class Settings:
    key_pause_ms: float = DEFAULT_KEY_PAUSE_MS
    modifiers: frozenset[Modifier] = frozenset(Modifier)


@dataclass(frozen=True)
class Config:
    """A complete, validated configuration."""

    version: int
    inputs: Mapping[str, InputDeviceSpec]
    outputs: Mapping[str, OutputDeviceSpec]
    mappings: tuple[MappingRule, ...]
    settings: Settings = Settings()
    variables: Mapping[str, object] = field(default_factory=dict)
    layers: tuple[str, ...] = ()

    def axis_thresholds(self) -> dict[int, AxisThreshold]:
        """Virtual key code -> axis threshold, for every axis trigger."""
        return {r.trigger.code: r.trigger.axis for r in self.mappings if r.trigger.axis}

    def input_axes(self, device_id: str) -> frozenset[AxisThreshold]:
        """Axis thresholds that mappings name for this input device."""
        return frozenset(
            r.trigger.axis
            for r in self.mappings
            if r.trigger.axis and r.trigger.device == device_id
        )

    def output_codes(self, device_id: str) -> frozenset[int]:
        """Key/button codes a virtual output device must declare."""
        codes = {
            action.code
            for rule in self.mappings
            for action in rule.outputs
            if action.device == device_id
        }
        codes |= {
            key.code
            for rule in self.mappings
            for macro in rule.macros
            for key in macro.key_refs()
            if key.device == device_id
        }
        return frozenset(codes)

    def input_codes(self, device_id: str) -> frozenset[int]:
        """Codes that mappings name for this input device (``kbd.KEY_X``).

        The device must have all of them; codes of mappings without a device
        (``shared_codes``) apply only where the device has them.
        """
        return frozenset(
            rule.trigger.code
            for rule in self.mappings
            if rule.trigger.device == device_id and rule.trigger.axis is None
        )

    def shared_codes(self) -> frozenset[int]:
        """Key codes of mappings without a device name (they apply to every input)."""
        return frozenset(
            rule.trigger.code
            for rule in self.mappings
            if rule.trigger.device is None and rule.trigger.axis is None
        )

    def shared_axes(self) -> frozenset[AxisThreshold]:
        """Axis thresholds of mappings without a device name."""
        return frozenset(
            r.trigger.axis for r in self.mappings if r.trigger.axis and r.trigger.device is None
        )

    def watched_axes(self, device_id: str) -> frozenset[int]:
        """ABS codes whose values go to the thresholds on this device (and are suppressed)."""
        return frozenset(
            r.trigger.axis.axis
            for r in self.mappings
            if r.trigger.axis and r.trigger.device in (device_id, None)
        )

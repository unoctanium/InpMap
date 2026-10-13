"""Validated, backend-independent configuration models.

Instances are produced by :mod:`inpmap.config` and never built from raw JSON
elsewhere. Codes are stored as integers (see :mod:`inpmap.codes`), so aliases
such as ``BTN_A``/``BTN_SOUTH`` compare equal.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import Enum

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
class InputDeviceSpec:
    """How to find a physical input device. Exactly one selector is set."""

    id: str
    name: str | None = None
    path: str | None = None


@dataclass(frozen=True)
class OutputDeviceSpec:
    """A virtual output device to create."""

    id: str
    kind: OutputKind
    name: str


@dataclass(frozen=True)
class InputTrigger:
    """A key/button on a named physical input device."""

    device: str
    code: int


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


@dataclass(frozen=True)
class Settings:
    key_pause_ms: float = DEFAULT_KEY_PAUSE_MS


@dataclass(frozen=True)
class Config:
    """A complete, validated configuration."""

    version: int
    inputs: Mapping[str, InputDeviceSpec]
    outputs: Mapping[str, OutputDeviceSpec]
    mappings: tuple[MappingRule, ...]
    settings: Settings = Settings()
    variables: Mapping[str, object] = field(default_factory=dict)

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
        """Codes mapped on a physical input device."""
        return frozenset(
            rule.trigger.code for rule in self.mappings if rule.trigger.device == device_id
        )

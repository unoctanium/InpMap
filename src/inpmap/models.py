"""Validated, backend-independent configuration models.

Instances are produced by :mod:`inpmap.config` and never built from raw JSON
elsewhere. Codes are stored as integers (see :mod:`inpmap.codes`), so aliases
such as ``BTN_A``/``BTN_SOUTH`` compare equal.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum


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
class MappingRule:
    """One input mapped to one or more outputs."""

    id: str
    trigger: InputTrigger
    outputs: tuple[OutputAction, ...]
    consume: bool = True
    description: str | None = None


@dataclass(frozen=True)
class Config:
    """A complete, validated configuration."""

    version: int
    inputs: Mapping[str, InputDeviceSpec]
    outputs: Mapping[str, OutputDeviceSpec]
    mappings: tuple[MappingRule, ...]

    def output_codes(self, device_id: str) -> frozenset[int]:
        """Codes a virtual output device must declare as capabilities."""
        return frozenset(
            action.code
            for rule in self.mappings
            for action in rule.outputs
            if action.device == device_id
        )

    def input_codes(self, device_id: str) -> frozenset[int]:
        """Codes mapped on a physical input device."""
        return frozenset(
            rule.trigger.code for rule in self.mappings if rule.trigger.device == device_id
        )

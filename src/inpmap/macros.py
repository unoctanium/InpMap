"""Validated macro model (see docs/macros.md).

Instances are produced by the configuration loader; the executor
(:mod:`inpmap.macro_runtime`) interprets them. Durations are milliseconds.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from enum import Enum

# -- values -----------------------------------------------------------------


@dataclass(frozen=True)
class VarRef:
    """Read a variable at runtime."""

    name: str


@dataclass(frozen=True)
class RandomRange:
    """Uniformly random duration in [min_ms, max_ms]."""

    min_ms: float
    max_ms: float


Duration = float | RandomRange | VarRef
Count = int | VarRef

MAX_REPEAT = 10000


@dataclass(frozen=True)
class KeyRef:
    device: str
    code: int


# -- axes -------------------------------------------------------------------


class AxisKind(Enum):
    STICK = "stick"  # -1.0 .. 1.0, rest 0.0
    TRIGGER = "trigger"  # 0.0 .. 1.0, rest 0.0


# Linux ABS codes of the virtual gamepad's axes.
GAMEPAD_AXES: dict[str, tuple[int, AxisKind]] = {
    "ABS_X": (0x00, AxisKind.STICK),
    "ABS_Y": (0x01, AxisKind.STICK),
    "ABS_Z": (0x02, AxisKind.TRIGGER),
    "ABS_RX": (0x03, AxisKind.STICK),
    "ABS_RY": (0x04, AxisKind.STICK),
    "ABS_RZ": (0x05, AxisKind.TRIGGER),
}
AXIS_NAMES = {code: name for name, (code, _) in GAMEPAD_AXES.items()}
AXIS_KINDS = {code: kind for _, (code, kind) in GAMEPAD_AXES.items()}
AXIS_REST = 0.0


def axis_range(kind: AxisKind) -> tuple[float, float]:
    return (-1.0, 1.0) if kind is AxisKind.STICK else (0.0, 1.0)


# -- steps ------------------------------------------------------------------


@dataclass(frozen=True)
class Tap:
    keys: tuple[KeyRef, ...]
    pause: Duration | None = None  # None: macro's key pause


@dataclass(frozen=True)
class Press:
    keys: tuple[KeyRef, ...]
    pause: Duration | None = None


@dataclass(frozen=True)
class Release:
    keys: tuple[KeyRef, ...]
    pause: Duration | None = None


@dataclass(frozen=True)
class HoldKeys:
    keys: tuple[KeyRef, ...]


@dataclass(frozen=True)
class WithKeys:
    keys: tuple[KeyRef, ...]
    steps: tuple[Step, ...]


@dataclass(frozen=True)
class MoveAxis:
    device: str
    code: int
    to: float
    over: Duration = 0.0


@dataclass(frozen=True)
class HoldAxis:
    device: str
    code: int
    value: float
    attack: Duration = 0.0
    release: Duration = 0.0


@dataclass(frozen=True)
class Wait:
    duration: Duration


@dataclass(frozen=True)
class Repeat:
    count: Count
    steps: tuple[Step, ...]


@dataclass(frozen=True)
class WhileHeld:
    steps: tuple[Step, ...]


@dataclass(frozen=True)
class Toggle:
    steps: tuple[Step, ...]


@dataclass(frozen=True)
class Parallel:
    branches: tuple[tuple[Step, ...], ...]


@dataclass(frozen=True)
class IfTap:
    then: tuple[Step, ...] = ()
    otherwise: tuple[Step, ...] = ()
    timeout_ms: float = 300.0


@dataclass(frozen=True)
class IfSingle:
    then: tuple[Step, ...] = ()
    otherwise: tuple[Step, ...] = ()
    timeout_ms: float | None = None


@dataclass(frozen=True)
class IfEq:
    var: str
    value: object
    then: tuple[Step, ...] = ()
    otherwise: tuple[Step, ...] = ()


class Led(Enum):
    CAPSLOCK = "capslock"
    NUMLOCK = "numlock"
    SCROLLLOCK = "scrolllock"


@dataclass(frozen=True)
class IfLed:
    led: Led
    then: tuple[Step, ...] = ()
    otherwise: tuple[Step, ...] = ()


@dataclass(frozen=True)
class SetVar:
    var: str
    value: object


@dataclass(frozen=True)
class AddVar:
    var: str
    value: int | float


Step = (
    Tap
    | Press
    | Release
    | HoldKeys
    | WithKeys
    | MoveAxis
    | HoldAxis
    | Wait
    | Repeat
    | WhileHeld
    | Toggle
    | Parallel
    | IfTap
    | IfSingle
    | IfEq
    | IfLed
    | SetVar
    | AddVar
)


class OnRelease(Enum):
    FINISH = "finish"
    CANCEL = "cancel"


class OnRetrigger(Enum):
    IGNORE = "ignore"
    RESTART = "restart"


DEFAULT_KEY_PAUSE_MS = 10.0
DEFAULT_MAX_RUN_MS = 60000.0


@dataclass(frozen=True)
class Macro:
    steps: tuple[Step, ...]
    release_steps: tuple[Step, ...] = ()
    on_release: OnRelease = OnRelease.FINISH
    on_retrigger: OnRetrigger = OnRetrigger.IGNORE
    key_pause_ms: float = DEFAULT_KEY_PAUSE_MS
    max_run_ms: float | None = DEFAULT_MAX_RUN_MS

    @property
    def is_toggle(self) -> bool:
        return len(self.steps) == 1 and isinstance(self.steps[0], Toggle)

    def key_refs(self) -> Iterator[KeyRef]:
        """All keys the macro may press (for device capabilities)."""
        for step in walk(self.steps + self.release_steps):
            if isinstance(step, (Tap, Press, Release, HoldKeys, WithKeys)):
                yield from step.keys


def children(step: Step) -> tuple[tuple[Step, ...], ...]:
    """Nested step lists of a step."""
    if isinstance(step, (WithKeys, Repeat, WhileHeld, Toggle)):
        return (step.steps,)
    if isinstance(step, Parallel):
        return step.branches
    if isinstance(step, (IfTap, IfSingle, IfEq, IfLed)):
        return (step.then, step.otherwise)
    return ()


def walk(steps: tuple[Step, ...]) -> Iterator[Step]:
    """All steps, depth-first, including nested ones."""
    for step in steps:
        yield step
        for nested in children(step):
            yield from walk(nested)

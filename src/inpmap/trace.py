"""Simulate a mapping on a fake clock and record its outputs (``macro-trace``).

No devices are opened or created: the real engine runs against a recording
sink, driven by scripted presses and releases of the mapping's input.
"""

from __future__ import annotations

import random
from dataclasses import dataclass

from . import codes
from .engine import MappingEngine
from .macros import AXIS_NAMES, Led
from .models import Config, InputEvent, KeyAction

IDLE_LIMIT_MS = 120_000.0  # stop waiting for macros to finish after this


@dataclass(frozen=True)
class TraceLine:
    ms: float
    text: str


class _Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


class _Recorder:
    def __init__(self, clock: _Clock) -> None:
        self.clock = clock
        self.lines: list[TraceLine] = []

    def _add(self, text: str) -> None:
        self.lines.append(TraceLine(self.clock.now * 1000, text))

    def press(self, device: str, code: int) -> None:
        self._add(f"{device:<10} {codes.code_name(code):<16} down")

    def release(self, device: str, code: int) -> None:
        self._add(f"{device:<10} {codes.code_name(code):<16} up")

    def set_axis(self, device: str, code: int, value: float) -> None:
        self._add(f"{device:<10} {AXIS_NAMES.get(code, hex(code)):<16} {value:+.3f}")


def trace(
    config: Config,
    mapping_id: str,
    *,
    hold_ms: float = 100.0,
    press_at: list[float] | None = None,
    other_key_at: list[float] | None = None,
    until_ms: float | None = None,
    seed: int = 0,
    leds: frozenset[Led] = frozenset(),
) -> list[TraceLine]:
    """Return the timeline of inputs (marked ``>>``) and outputs.

    The mapping's input is pressed at each time in ``press_at`` (default: 0)
    and released ``hold_ms`` later. ``other_key_at`` presses (and 10 ms later
    releases) some other key, e.g. to exercise ``if_single``. Without
    ``until_ms``, the simulation ends when no macro runs any more.
    """
    rule = next((r for r in config.mappings if r.id == mapping_id), None)
    if rule is None:
        known = ", ".join(r.id for r in config.mappings)
        raise ValueError(f"unknown mapping '{mapping_id}' (mappings: {known})")
    clock = _Clock()
    recorder = _Recorder(clock)
    engine = MappingEngine(
        config, recorder, clock=clock, leds=lambda device: leds, rng=random.Random(seed)
    )
    trigger = (rule.trigger.device, rule.trigger.code)
    other = (rule.trigger.device, _unmapped_code(config, rule.trigger.device))

    script: list[tuple[float, int, tuple[str, int], KeyAction, str]] = []
    for at in press_at or [0.0]:
        script.append((at, len(script), trigger, KeyAction.PRESS, "input pressed"))
        script.append((at + hold_ms, len(script), trigger, KeyAction.RELEASE, "input released"))
    for at in other_key_at or []:
        script.append((at, len(script), other, KeyAction.PRESS, "other key pressed"))
        script.append((at + 10, len(script), other, KeyAction.RELEASE, "other key released"))
    script.sort()

    for at, _order, (device, code), action, label in script:
        if until_ms is not None and at > until_ms:
            break
        _advance(engine, clock, at / 1000)
        recorder.lines.append(TraceLine(at, f">> {label}"))
        engine.handle(InputEvent(device, code, action))

    if until_ms is not None:
        _advance(engine, clock, until_ms / 1000)
    else:
        limit = max([s[0] for s in script] + [0.0]) + IDLE_LIMIT_MS
        while engine.running_macros() or engine.held_outputs():
            due = engine.next_deadline()
            if due is None or due * 1000 > limit:
                break
            _advance(engine, clock, due)
    return recorder.lines


def _advance(engine: MappingEngine, clock: _Clock, target: float) -> None:
    while True:
        due = engine.next_deadline()
        if due is None or due > target:
            break
        clock.now = max(clock.now, due)
        engine.tick()
    clock.now = max(clock.now, target)
    engine.tick()


def _unmapped_code(config: Config, device: str) -> int:
    mapped = {r.trigger.code for r in config.mappings if r.trigger.device == device}
    for name in ("KEY_F13", "KEY_F14", "KEY_F15", "KEY_F16"):
        code = codes.code_from_name(name)
        if code is not None and code not in mapped:
            return code
    raise ValueError("no unmapped key available to simulate 'other key'")


def format_trace(lines: list[TraceLine]) -> str:
    return "\n".join(f"{line.ms:9.1f} ms  {line.text}" for line in lines)

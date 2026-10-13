"""Mapping engine: applies mapping rules to normalized input events.

Semantics (V1):

* Press of a mapped input activates its rule. Each output gains a holder and
  is pressed if no other holder already holds it.
  - ``hold`` outputs keep their holder until the input is released.
  - ``tap`` outputs give up their holder automatically after
    :data:`TAP_DURATION`, independent of the input.
* An output is released only when its last holder lets go (reference
  counting), so overlapping mappings never release each other's keys.
* Repeat events of mapped inputs are consumed without action.
* A second press of an already active input, or a release of an inactive
  one, is ignored (missed or duplicated events must not unbalance counts).
* Unmapped events are not handled here; ``handle`` returns False and the
  caller decides about passthrough.

Timed releases never block: they are queued and executed by :meth:`tick`,
which the runtime calls from its event loop (:meth:`next_deadline` tells it
how long it may wait).

The engine is backend-independent: it consumes :class:`InputEvent` and drives
an :class:`OutputSink` (normally :class:`inpmap.output.OutputManager`).
"""

from __future__ import annotations

import heapq
import itertools
import logging
import time
from collections.abc import Callable, Iterable
from typing import Protocol

from . import codes
from .models import Config, InputEvent, KeyAction, MappingRule, OutputAction, OutputMode
from .output import OutputError
from .state import OutputKey, OutputRefCounts

log = logging.getLogger(__name__)

InputKey = tuple[str, int]  # (input device id, code)

# How long a tap output stays pressed. Long enough for games that sample key
# state once per frame (16.7 ms at 60 fps) to see it.
TAP_DURATION = 0.02


class OutputSink(Protocol):
    def press(self, device_id: str, code: int) -> None: ...

    def release(self, device_id: str, code: int) -> None: ...


class MappingEngine:
    """Tracks active inputs and drives outputs with reference counting."""

    def __init__(
        self,
        config: Config,
        sink: OutputSink,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._sink = sink
        self._clock = clock
        self._rules: dict[InputKey, MappingRule] = {
            (rule.trigger.device, rule.trigger.code): rule for rule in config.mappings
        }
        self._active: dict[InputKey, MappingRule] = {}
        self._refs = OutputRefCounts()
        # (due time, sequence, output key) for pending tap releases.
        self._timed: list[tuple[float, int, OutputKey]] = []
        self._sequence = itertools.count()

    def handle(self, event: InputEvent) -> bool:
        """Process one event. Returns True if the original must be suppressed.

        Raises OutputError if an output could not be written; the engine's
        state stays consistent, so later releases still clean up.
        """
        key = (event.device, event.code)
        rule = self._rules.get(key)
        if rule is None:
            return False
        if event.action is KeyAction.PRESS:
            self._activate(key, rule)
        elif event.action is KeyAction.RELEASE:
            self._deactivate(key, rule)
        # REPEAT: outputs are already held or tapped; nothing to do.
        return rule.consume

    def tick(self) -> None:
        """Execute timed releases that are due."""
        now = self._clock()
        due: list[OutputKey] = []
        while self._timed and self._timed[0][0] <= now:
            due.append(heapq.heappop(self._timed)[2])
        self._release_keys(due, "tap")

    def next_deadline(self) -> float | None:
        """Clock time of the next timed release, if any."""
        return self._timed[0][0] if self._timed else None

    def is_mapped(self, device_id: str, code: int) -> bool:
        return (device_id, code) in self._rules

    def active_rules(self) -> list[str]:
        """Ids of rules whose input is currently held."""
        return [rule.id for rule in self._active.values()]

    def held_outputs(self) -> frozenset[OutputKey]:
        """(output device, code) pairs currently held (by inputs or taps)."""
        return self._refs.held()

    def release_device(self, device_id: str) -> None:
        """Deactivate all rules triggered by one input device (e.g. it was lost).

        Pending taps finish on their own schedule.
        """
        self._deactivate_all(key for key in self._active if key[0] == device_id)

    def release_all(self) -> None:
        """Deactivate every rule and finish all pending taps immediately."""
        failures: list[str] = []
        try:
            self._deactivate_all(list(self._active))
        except OutputError as exc:
            failures.append(str(exc))
        pending = [entry[2] for entry in self._timed]
        self._timed.clear()
        try:
            self._release_keys(pending, "tap")
        except OutputError as exc:
            failures.append(str(exc))
        if failures:
            raise OutputError("; ".join(failures))

    def _activate(self, key: InputKey, rule: MappingRule) -> None:
        if key in self._active:
            log.debug("ignoring duplicate press for mapping '%s'", rule.id)
            return
        self._active[key] = rule
        log.debug("mapping '%s' activated", rule.id)
        failures: list[str] = []
        due = self._clock() + TAP_DURATION
        for action in rule.outputs:
            output = (action.device, action.code)
            if action.mode is OutputMode.TAP:
                # Queue the release even if the press fails, so counts balance.
                heapq.heappush(self._timed, (due, next(self._sequence), output))
            if self._refs.acquire(output):
                self._emit(self._sink.press, action, "press", failures)
        if failures:
            raise OutputError(f"mapping '{rule.id}': " + "; ".join(failures))

    def _deactivate(self, key: InputKey, rule: MappingRule) -> None:
        if key not in self._active:
            log.debug("ignoring release of inactive mapping '%s'", rule.id)
            return
        del self._active[key]
        log.debug("mapping '%s' deactivated", rule.id)
        held = [(a.device, a.code) for a in rule.outputs if a.mode is OutputMode.HOLD]
        try:
            self._release_keys(held, "release")
        except OutputError as exc:
            raise OutputError(f"mapping '{rule.id}': {exc}") from exc

    def _release_keys(self, keys: Iterable[OutputKey], verb: str) -> None:
        # Counts are updated for every key even if an earlier write failed,
        # so press and release stay balanced; failures are raised afterwards.
        failures: list[str] = []
        for device, code in keys:
            if self._refs.release((device, code)):
                self._emit(self._sink.release, OutputAction(device, code), verb, failures)
        if failures:
            raise OutputError("; ".join(failures))

    def _emit(
        self,
        emit: Callable[[str, int], None],
        action: OutputAction,
        verb: str,
        failures: list[str],
    ) -> None:
        try:
            emit(action.device, action.code)
        except OutputError as exc:
            failures.append(f"{verb} {action.device} {codes.code_name(action.code)}: {exc}")

    def _deactivate_all(self, keys: Iterable[InputKey]) -> None:
        failures: list[str] = []
        for key in list(keys):
            try:
                self._deactivate(key, self._active[key])
            except OutputError as exc:
                failures.append(str(exc))
        if failures:
            raise OutputError("; ".join(failures))

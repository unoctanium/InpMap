"""Mapping engine: applies mapping rules to normalized input events.

Semantics (V1):

* Press of a mapped input activates its rule: each output gains a holder and
  is pressed if it was not already held by another active rule.
* Release deactivates the rule: each output loses a holder and is released
  only when no other active rule still holds it.
* Repeat events of mapped inputs are consumed without action; outputs are
  held, not re-pressed.
* A second press of an already active input, or a release of an inactive
  one, is ignored (missed or duplicated events must not unbalance counts).
* Unmapped events are not handled here; ``handle`` returns False and the
  caller decides about passthrough.

The engine is backend-independent: it consumes :class:`InputEvent` and drives
an :class:`OutputSink` (normally :class:`inpmap.output.OutputManager`).
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterable
from typing import Protocol

from . import codes
from .models import Config, InputEvent, KeyAction, MappingRule
from .output import OutputError
from .state import OutputRefCounts

log = logging.getLogger(__name__)

InputKey = tuple[str, int]  # (input device id, code)


class OutputSink(Protocol):
    def press(self, device_id: str, code: int) -> None: ...

    def release(self, device_id: str, code: int) -> None: ...


class MappingEngine:
    """Tracks active inputs and drives outputs with reference counting."""

    def __init__(self, config: Config, sink: OutputSink) -> None:
        self._sink = sink
        self._rules: dict[InputKey, MappingRule] = {
            (rule.trigger.device, rule.trigger.code): rule for rule in config.mappings
        }
        self._active: dict[InputKey, MappingRule] = {}
        self._refs = OutputRefCounts()

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
        # REPEAT: outputs are already held; nothing to do.
        return rule.consume

    def is_mapped(self, device_id: str, code: int) -> bool:
        return (device_id, code) in self._rules

    def active_rules(self) -> list[str]:
        """Ids of rules whose input is currently held."""
        return [rule.id for rule in self._active.values()]

    def held_outputs(self) -> frozenset[tuple[str, int]]:
        """(output device, code) pairs currently held by active rules."""
        return self._refs.held()

    def release_device(self, device_id: str) -> None:
        """Deactivate all rules triggered by one input device (e.g. it was lost)."""
        self._deactivate_all(key for key in self._active if key[0] == device_id)

    def release_all(self) -> None:
        """Deactivate every active rule."""
        self._deactivate_all(list(self._active))

    def _activate(self, key: InputKey, rule: MappingRule) -> None:
        if key in self._active:
            log.debug("ignoring duplicate press for mapping '%s'", rule.id)
            return
        self._active[key] = rule
        log.debug("mapping '%s' activated", rule.id)
        self._apply(rule, self._refs.acquire, self._sink.press, "press")

    def _deactivate(self, key: InputKey, rule: MappingRule) -> None:
        if key not in self._active:
            log.debug("ignoring release of inactive mapping '%s'", rule.id)
            return
        del self._active[key]
        log.debug("mapping '%s' deactivated", rule.id)
        self._apply(rule, self._refs.release, self._sink.release, "release")

    def _apply(
        self,
        rule: MappingRule,
        update_count: Callable[[tuple[str, int]], bool],
        emit: Callable[[str, int], None],
        verb: str,
    ) -> None:
        # Counts are updated for every output even if an earlier write failed,
        # so press and release stay balanced; failures are raised afterwards.
        failures: list[str] = []
        for action in rule.outputs:
            if not update_count((action.device, action.code)):
                continue
            try:
                emit(action.device, action.code)
            except OutputError as exc:
                failures.append(f"{verb} {action.device} {codes.code_name(action.code)}: {exc}")
        if failures:
            raise OutputError(f"mapping '{rule.id}': " + "; ".join(failures))

    def _deactivate_all(self, keys: Iterable[InputKey]) -> None:
        failures: list[str] = []
        for key in list(keys):
            try:
                self._deactivate(key, self._active[key])
            except OutputError as exc:
                failures.append(str(exc))
        if failures:
            raise OutputError("; ".join(failures))

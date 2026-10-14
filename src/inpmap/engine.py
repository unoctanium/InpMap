"""Mapping engine: applies mapping rules to normalized input events.

Semantics:

* Press of a mapped input activates its rule.
  - Key outputs gain a holder and are pressed if no other holder holds them.
    ``hold`` outputs keep the holder until the input is released; ``tap``
    outputs give it up after :data:`TAP_DURATION`.
  - Each macro of the rule starts a run (or, if it is still running, the
    press goes to the run: see docs/configuration.md §7). Axis outputs run as small
    internal macros.
* An output key is released only when its last holder lets go (reference
  counting), so overlapping mappings and macros never release each other's
  keys. Axes use holder stacks (:mod:`inpmap.axes`).
* Repeat events of mapped inputs are consumed without action.
* A second press of an already active input, or a release of an inactive
  one, is ignored (missed or duplicated events must not unbalance counts).
* Every press of any key is offered to running macros first, so ``if_single``
  can act before that key is processed.
* Unmapped events are not handled here; ``handle`` returns False and the
  caller decides about passthrough.

Timed work never blocks: it is queued and executed by :meth:`tick`, which the
runtime calls from its event loop (:meth:`next_deadline` tells it how long it
may wait).
"""

from __future__ import annotations

import heapq
import itertools
import logging
import random
import time
from collections import Counter
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Protocol

from . import codes
from .axes import AxisStacks
from .macro_runtime import MacroRun
from .macros import HoldAxis, KeyRef, LayerAction, Led, Macro, OnRetrigger
from .models import Config, InputEvent, KeyAction, MappingRule, OutputAction, OutputMode
from .modifiers import ModifierState, choose
from .output import OutputError
from .state import OutputKey, OutputRefCounts

log = logging.getLogger(__name__)

InputKey = tuple[str, int]  # (input device id, code)
# A mapping without a device runs independently on every input device, so
# runs and masks belong to an instance: (mapping id, input device id).
Instance = tuple[str, str]
Slot = tuple[str, str, int]  # (mapping id, input device id, macro index)

# How long a tap output stays pressed. Long enough for games that sample key
# state once per frame (16.7 ms at 60 fps) to see it.
TAP_DURATION = 0.02


class OutputSink(Protocol):
    def press(self, device_id: str, code: int) -> None: ...

    def release(self, device_id: str, code: int) -> None: ...

    def set_axis(self, device_id: str, code: int, value: float) -> None: ...


class InputControl(Protocol):
    """Lets the engine temporarily hide passed-through modifier keys."""

    def mask(self, device_id: str, code: int) -> None: ...

    def unmask(self, device_id: str, code: int) -> None: ...


class _NoInputControl:
    def mask(self, device_id: str, code: int) -> None:
        pass

    def unmask(self, device_id: str, code: int) -> None:
        pass


@dataclass
class _MaskOwner:
    """Modifier keys hidden for one activation of a mapping with modifiers."""

    instance: Instance
    keys: frozenset[tuple[str, int]]
    released: bool = False


def _axis_macro(axis) -> Macro:
    """A plain axis output behaves like a one-step hold_axis macro."""
    step = HoldAxis(axis.device, axis.code, axis.value, axis.attack_ms, axis.release_ms)
    return Macro(steps=(step,), on_retrigger=OnRetrigger.RESTART, key_pause_ms=0.0, max_run_ms=None)


class MappingEngine:
    """Tracks active inputs, runs macros and drives outputs with reference counting.

    Also acts as the :class:`inpmap.macro_runtime.MacroHost` for macro runs.
    """

    def __init__(
        self,
        config: Config,
        sink: OutputSink,
        clock: Callable[[], float] = time.monotonic,
        leds: Callable[[str], frozenset[Led]] | None = None,
        rng: random.Random | None = None,
        inputs: InputControl | None = None,
    ) -> None:
        self._sink = sink
        self._clock = clock
        self._leds = leds or (lambda device_id: frozenset())
        self.rng = rng or random.Random()
        self.variables: dict[str, object] = dict(config.variables)
        self.axes = AxisStacks(sink.set_axis)
        self._input_control: InputControl = inputs or _NoInputControl()
        self._modifiers = ModifierState(config.settings.modifiers)
        # Rules per (layer, device, code); several per key are possible
        # (different modifier requirements). Layer None: the base. Device
        # None: rules without a device name, for every input.
        self._rules: dict[tuple[str | None, str | None, int], list[MappingRule]] = {}
        self._mapped: set[tuple[str | None, int]] = set()  # (device, code) in any layer
        for rule in config.mappings:
            key = (rule.layer, rule.trigger.device, rule.trigger.code)
            self._rules.setdefault(key, []).append(rule)
            self._mapped.add((rule.trigger.device, rule.trigger.code))
        # Layers (§5.6): switched on, held by runs, and the order in which
        # the active ones became active (most recent last).
        self._layers_on: set[str] = set()
        self._layer_holds: Counter[str] = Counter()
        self._layer_order: list[str] = []
        self._masked: Counter[tuple[str, int]] = Counter()
        self._mask_owners: list[_MaskOwner] = []
        self._macros: dict[str, tuple[Macro, ...]] = {
            rule.id: rule.macros + tuple(_axis_macro(axis) for axis in rule.axes)
            for rule in config.mappings
        }
        self._active: dict[InputKey, MappingRule] = {}
        self._refs = OutputRefCounts()
        self._runs: dict[Slot, MacroRun] = {}
        self._run_trigger: dict[Slot, InputKey] = {}
        # (due time, sequence, output key) for pending tap releases.
        self._taps: list[tuple[float, int, OutputKey]] = []
        # (due time, sequence, callback) for macro timers.
        self._timers: list[tuple[float, int, Callable[[], None]]] = []
        self._sequence = itertools.count()

    # -- input -------------------------------------------------------------

    def handle(self, event: InputEvent) -> bool:
        """Process one event. Returns True if the original must be suppressed.

        Raises OutputError if an output could not be written; the engine's
        state stays consistent, so later releases still clean up.
        """
        key = (event.device, event.code)
        self._modifiers.update(event.device, event.code, event.action)
        if event.action is KeyAction.PRESS:
            self._offer_other_press(key)
        if not self.is_mapped(event.device, event.code):
            return False
        active = self._active.get(key)
        if event.action is KeyAction.PRESS:
            if active is not None:
                log.debug("ignoring duplicate press for mapping '%s'", active.id)
                return active.consume
            rule = self._choose(event.device, event.code)
            if rule is None:
                return False  # no mapping fits the held modifiers: pass through
            self._activate(key, rule)
            return rule.consume
        if active is None:
            # The press was passed through (or never seen): pass this on too.
            return False
        if event.action is KeyAction.RELEASE:
            self._deactivate(key, active)
        # REPEAT: outputs are already held or tapped; nothing to do.
        return active.consume

    def tick(self) -> None:
        """Execute timed work (tap releases, macro timers) that is due."""
        now = self._clock()
        failures: list[str] = []
        due_taps: list[OutputKey] = []
        while self._taps and self._taps[0][0] <= now:
            due_taps.append(heapq.heappop(self._taps)[2])
        try:
            self._release_keys(due_taps, "tap")
        except OutputError as exc:
            failures.append(str(exc))
        while self._timers and self._timers[0][0] <= now:
            callback = heapq.heappop(self._timers)[2]
            try:
                callback()
            except OutputError as exc:
                failures.append(str(exc))
        if failures:
            raise OutputError("; ".join(failures))

    def next_deadline(self) -> float | None:
        """Clock time of the next timed work, if any."""
        heads = [queue[0][0] for queue in (self._taps, self._timers) if queue]
        return min(heads) if heads else None

    # -- queries -------------------------------------------------------------

    def is_mapped(self, device_id: str, code: int) -> bool:
        """Whether any mapping (in any layer) could handle this key."""
        return (device_id, code) in self._mapped or (None, code) in self._mapped

    def _choose(self, device_id: str, code: int) -> MappingRule | None:
        """Active layers from the most recent, then the base (§5.6); within
        each, mappings naming the device first, then those for every input."""
        for layer in (*reversed(self._layer_order), None):
            for device in (device_id, None):
                rule = choose(self._rules.get((layer, device, code), []), self._modifiers)
                if rule is not None:
                    return rule
        return None

    # -- layers (MacroHost) --------------------------------------------------

    def layer_active(self, layer: str) -> bool:
        return layer in self._layer_order

    def active_layers(self) -> list[str]:
        """Active layers, most recently activated last."""
        return list(self._layer_order)

    def switch_layer(self, layer: str, action: LayerAction) -> None:
        if action is LayerAction.HOLD:
            self._layer_holds[layer] += 1
        elif action is LayerAction.ON:
            self._layers_on.add(layer)
        elif action is LayerAction.OFF:
            self._layers_on.discard(layer)
        elif layer in self._layers_on or self._layer_holds[layer]:
            # toggle while active: switch off (a hold keeps it active, §5.6 rule 2)
            self._layers_on.discard(layer)
        else:
            self._layers_on.add(layer)
        self._update_layer(layer)

    def release_layer(self, layer: str) -> None:
        if self._layer_holds[layer] > 0:
            self._layer_holds[layer] -= 1
        self._update_layer(layer)

    def _update_layer(self, layer: str) -> None:
        active = layer in self._layers_on or self._layer_holds[layer] > 0
        if active and layer not in self._layer_order:
            self._layer_order.append(layer)
            log.debug("layer '%s' active", layer)
        elif not active and layer in self._layer_order:
            self._layer_order.remove(layer)
            log.debug("layer '%s' inactive", layer)

    def active_rules(self) -> list[str]:
        """Ids of rules whose input is currently held."""
        return [rule.id for rule in self._active.values()]

    def held_outputs(self) -> frozenset[OutputKey]:
        """(output device, code) pairs currently held (by inputs, taps or macros)."""
        return self._refs.held()

    def running_macros(self) -> list[Slot]:
        return [slot for slot, run in self._runs.items() if run.active]

    # -- device loss and shutdown ---------------------------------------------

    def release_device(self, device_id: str) -> None:
        """Deactivate rules and cancel macro runs triggered by one input device.

        Pending taps finish on their own schedule.
        """
        self._modifiers.forget_device(device_id)
        self._forget_masks(lambda key: key[0] == device_id)
        failures: list[str] = []
        try:
            self._deactivate_all(key for key in self._active if key[0] == device_id)
        except OutputError as exc:
            failures.append(str(exc))
        slots = [slot for slot, key in self._run_trigger.items() if key[0] == device_id]
        failures += self._cancel_runs(slots)
        if failures:
            raise OutputError("; ".join(failures))

    def release_all(self) -> None:
        """Deactivate every rule, cancel all macros, finish pending taps now."""
        failures: list[str] = []
        try:
            self._deactivate_all(list(self._active))
        except OutputError as exc:
            failures.append(str(exc))
        failures += self._cancel_runs(list(self._runs))
        self._forget_masks(lambda key: True)
        pending = [entry[2] for entry in self._taps]
        self._taps.clear()
        self._timers.clear()
        try:
            self._release_keys(pending, "tap")
        except OutputError as exc:
            failures.append(str(exc))
        if failures:
            raise OutputError("; ".join(failures))

    # -- MacroHost -------------------------------------------------------------

    def now(self) -> float:
        return self._clock()

    def schedule(self, delay: float, callback: Callable[[], None]) -> None:
        heapq.heappush(self._timers, (self._clock() + delay, next(self._sequence), callback))

    def press_key(self, key: KeyRef) -> None:
        if self._refs.acquire((key.device, key.code)):
            self._emit_or_raise(self._sink.press, key.device, key.code, "press")

    def release_key(self, key: KeyRef) -> None:
        self._release_keys([(key.device, key.code)], "release")

    def led_on(self, input_device: str, led: Led) -> bool:
        return led in self._leds(input_device)

    # -- activation --------------------------------------------------------------

    def _activate(self, key: InputKey, rule: MappingRule) -> None:
        if rule.trigger.modifiers and not rule.keep_modifiers and not rule.disabled:
            # Hide the held modifiers from the desktop before any output, so
            # the outputs are not modified by them (docs/configuration.md §5.2 rule 8).
            self._mask((rule.id, key[0]), self._modifiers.held_keys())
        self._active[key] = rule
        log.debug("mapping '%s' activated", rule.id)
        failures: list[str] = []
        due = self._clock() + TAP_DURATION
        for action in rule.outputs:
            output = (action.device, action.code)
            if action.mode is OutputMode.TAP:
                # Queue the release even if the press fails, so counts balance.
                heapq.heappush(self._taps, (due, next(self._sequence), output))
            if self._refs.acquire(output):
                self._emit(self._sink.press, action, "press", failures)
        try:
            self._press_macros(key, rule)
        except OutputError as exc:
            failures.append(str(exc))
        if failures:
            raise OutputError(f"mapping '{rule.id}': " + "; ".join(failures))

    def _deactivate(self, key: InputKey, rule: MappingRule) -> None:
        if key not in self._active:
            log.debug("ignoring release of inactive mapping '%s'", rule.id)
            return
        del self._active[key]
        log.debug("mapping '%s' deactivated", rule.id)
        failures: list[str] = []
        held = [(a.device, a.code) for a in rule.outputs if a.mode is OutputMode.HOLD]
        try:
            self._release_keys(held, "release")
        except OutputError as exc:
            failures.append(str(exc))
        for slot in self._slots(rule, key[0]):
            run = self._runs.get(slot)
            if run is not None and run.active:
                try:
                    run.on_release()
                except OutputError as exc:
                    failures.append(str(exc))
        instance = (rule.id, key[0])
        owner = next(
            (o for o in self._mask_owners if o.instance == instance and not o.released), None
        )
        if owner is not None:
            owner.released = True
            self._unmask_finished(instance)
        if failures:
            raise OutputError(f"mapping '{rule.id}': " + "; ".join(failures))

    # -- macros -------------------------------------------------------------------

    def _slots(self, rule: MappingRule, device_id: str) -> list[Slot]:
        return [(rule.id, device_id, index) for index in range(len(self._macros[rule.id]))]

    def _press_macros(self, key: InputKey, rule: MappingRule) -> None:
        for slot, macro in zip(self._slots(rule, key[0]), self._macros[rule.id], strict=True):
            run = self._runs.get(slot)
            if run is None or not run.active:
                self._start_run(slot, key, macro)
            elif run.on_press():
                continue  # consumed by a waiting step or a toggle
            elif macro.on_retrigger is OnRetrigger.RESTART:
                # Batch axis writes so a restarted axis hold does not jump to rest.
                with self.axes.batch():
                    run.cancel()
                    self._start_run(slot, key, macro)

    def _start_run(self, slot: Slot, key: InputKey, macro: Macro) -> None:
        name = f"mapping '{slot[0]}' on {slot[1]} macro {slot[2]}"
        run = MacroRun(self, macro, key[0], lambda r: self._run_finished(slot, r), name)
        self._runs[slot] = run
        self._run_trigger[slot] = key
        run.start()

    def _run_finished(self, slot: Slot, run: MacroRun) -> None:
        if self._runs.get(slot) is run:
            del self._runs[slot]
            del self._run_trigger[slot]
        self._unmask_finished((slot[0], slot[1]))

    # -- modifier masking --------------------------------------------------------

    def _mask(self, instance: Instance, keys: frozenset[tuple[str, int]]) -> None:
        for key in sorted(keys):
            if self._masked[key] == 0:
                self._input_control.mask(*key)
            self._masked[key] += 1
        self._mask_owners.append(_MaskOwner(instance, keys))

    def _unmask_finished(self, instance: Instance) -> None:
        """Give modifiers back once the mapping is released and no run is left."""
        if any(slot[:2] == instance and run.active for slot, run in self._runs.items()):
            return
        for owner in [o for o in self._mask_owners if o.instance == instance and o.released]:
            self._mask_owners.remove(owner)
            for key in sorted(owner.keys):
                self._masked[key] -= 1
                if self._masked[key] == 0:
                    del self._masked[key]
                    self._input_control.unmask(*key)

    def _forget_masks(self, which: Callable[[tuple[str, int]], bool]) -> None:
        """Drop masks without unmasking (device gone or shutting down)."""
        for key in [k for k in self._masked if which(k)]:
            del self._masked[key]
        for owner in self._mask_owners:
            owner.keys = frozenset(k for k in owner.keys if not which(k))

    def _offer_other_press(self, key: InputKey) -> None:
        for slot, run in list(self._runs.items()):
            if self._run_trigger.get(slot) != key and run.active:
                run.on_other_press()

    def _cancel_runs(self, slots: Iterable[Slot]) -> list[str]:
        failures: list[str] = []
        for slot in list(slots):
            run = self._runs.get(slot)
            if run is None:
                continue
            try:
                run.cancel()
            except OutputError as exc:
                failures.append(str(exc))
        return failures

    # -- output helpers ------------------------------------------------------------

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

    def _emit_or_raise(
        self, emit: Callable[[str, int], None], device: str, code: int, verb: str
    ) -> None:
        failures: list[str] = []
        self._emit(emit, OutputAction(device, code), verb, failures)
        if failures:
            raise OutputError(failures[0])

    def _deactivate_all(self, keys: Iterable[InputKey]) -> None:
        failures: list[str] = []
        for key in list(keys):
            try:
                self._deactivate(key, self._active[key])
            except OutputError as exc:
                failures.append(str(exc))
        if failures:
            raise OutputError("; ".join(failures))

"""Remapping runtime: startup, event loop, reconnect and guaranteed cleanup.

Independent of CLI parsing so foreground mode, a future systemd service and
tests share it. Each configured input device moves through these states:

    opened  --no key held-->  grabbed  --lost-->  absent  --reopened-->  opened

* opened: not grabbed yet. Its events still reach the desktop, so they are
  read and discarded. Grabbing waits until no key is held, otherwise the
  desktop would never see the release of a key held at grab time.
* grabbed: events go to the engine; what no mapping consumes goes to the
  outputs (:mod:`inpmap.routing`), or to the device's pass-through device
  if no output carries it.
* absent: the device disappeared. Outputs it held are released, its
  resources closed, and opening is retried periodically.

Startup creates the virtual outputs first, then opens all inputs. By default
an input that cannot be opened at startup is a hard error (likely a
configuration mistake). With ``wait_for_inputs`` (used by the service) it
starts in the absent state instead, so a gamepad that is switched off at
login does not stop the remapper; why it is absent is logged. A device
whose unmapped input would have nowhere to go is never grabbed
(configuration.md §3.4 rule 2): an error at startup in both modes, only
logged when it appears later. Cleanup
on every exit path: release engine outputs, ungrab and close inputs
(releasing forwarded keys), destroy the virtual devices.

Emergency stop: holding Backspace, Escape and Enter together on the grabbed
inputs stops the runtime like a signal does. It is the way out when a
configuration makes the keyboard unusable while InpMap runs as a service.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
from typing import Protocol

from . import codes
from .axis_triggers import AxisEvent, AxisTriggers
from .axis_triggers import problem as axis_problem
from .config import Config
from .engine import MappingEngine
from .input import InputBackend, InputDeviceLost, InputError, InputSource
from .macros import Led
from .models import AxisThreshold, InputDeviceSpec, KeyAction, OutputKind
from .output import OutputBackend, OutputError, OutputManager
from .routing import InputRefused, Router, plan_route

log = logging.getLogger(__name__)


class StopReason(Enum):
    STOPPED = "stopped"  # stop was requested (signal)
    TIMEOUT = "timeout"  # the configured run time elapsed
    EMERGENCY = "emergency stop: Backspace+Escape+Enter"


EMERGENCY_KEYS = frozenset(
    codes.code_from_name(n) for n in ("KEY_BACKSPACE", "KEY_ESC", "KEY_ENTER")
)


class StopFlag(Protocol):
    def is_set(self) -> bool: ...


class CleanupError(Exception):
    """Shutdown did not complete cleanly (details were logged)."""


@dataclass
class _Slot:
    """Runtime state of one configured input device."""

    spec: InputDeviceSpec
    codes: frozenset[int]
    axes: frozenset[AxisThreshold] = frozenset()  # thresholds that name this device
    source: InputSource | None = None
    grabbed: bool = False
    waiting_announced: bool = False
    retry_at: float = 0.0
    open_error: str | None = None  # last reason the device could not be opened
    key_codes: frozenset[int] | None = None  # known once the device was opened


class Runtime:
    """Runs one configuration until stopped, timed out, or failed."""

    def __init__(
        self,
        config: Config,
        input_backend: InputBackend,
        output_backend: OutputBackend,
        *,
        poll_interval: float = 0.1,
        reconnect_interval: float = 1.0,
        wait_for_inputs: bool = False,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._config = config
        self._inputs = input_backend
        self._outputs = OutputManager(output_backend, config)
        self._poll_interval = poll_interval
        self._reconnect_interval = reconnect_interval
        self._wait_for_inputs = wait_for_inputs
        self._clock = clock
        self._sleep = sleep
        self._slots: list[_Slot] = []
        self._engine: MappingEngine | None = None
        self._router: Router | None = None
        self._output_leds: dict[str, frozenset[Led]] = {}  # last LEDs per keyboard output
        self._all_grabbed_announced = False
        # (device id, code) of emergency keys currently held on grabbed inputs
        self._emergency_held: set[tuple[str, int]] = set()
        self._shared_codes_checked = False
        self._axis_triggers = AxisTriggers(config.axis_thresholds())
        self._watched = {device_id: config.watched_axes(device_id) for device_id in config.inputs}

    def run(self, stop: StopFlag, timeout: float | None = None) -> StopReason:
        """Run until ``stop`` is set or ``timeout`` seconds have passed.

        Raises InputError/OutputError on unrecoverable failures (after
        cleanup), and CleanupError if shutdown itself failed.
        """
        deadline = None if timeout is None else self._clock() + timeout
        if not self._config.mappings:
            return self._idle(stop, deadline)
        self._outputs.open()
        try:
            reason = self._start_and_loop(stop, deadline)
        except BaseException:
            # Cleanup boundary: never leave devices grabbed or keys held.
            self._shutdown()
            raise
        log.info("stopping (%s)", reason.value)
        if self._shutdown():
            raise CleanupError("shutdown completed with errors (see log)")
        return reason

    def _idle(self, stop: StopFlag, deadline: float | None) -> StopReason:
        """No mappings: grab nothing, create nothing, just wait to be stopped."""
        log.info("no mappings in this configuration: nothing is grabbed or created")
        while (reason := self._should_stop(stop, deadline)) is None:
            wait = self._poll_interval
            if deadline is not None:
                wait = max(0.0, min(wait, deadline - self._clock()))
            self._sleep(wait)
        log.info("stopping (%s)", reason.value)
        return reason

    def _start_and_loop(self, stop: StopFlag, deadline: float | None) -> StopReason:
        self._engine = MappingEngine(
            self._config, self._outputs, clock=self._clock, leds=self._leds_of, inputs=self
        )
        self._router = Router(self._engine)
        for device_id, spec in self._config.inputs.items():
            slot = _Slot(
                spec=spec,
                codes=self._config.input_codes(device_id),
                axes=self._config.input_axes(device_id),
            )
            self._slots.append(slot)
            if self._wait_for_inputs:
                self._try_open(slot, starting=True)
            else:
                slot.source = self._open(slot)
                log.info("opened input '%s': %s", device_id, slot.source.description)
                self._opened(slot)
        while True:
            reason = self._should_stop(stop, deadline)
            if reason is not None:
                return reason
            for slot in self._slots:
                self._advance(slot)
            self._engine.tick()  # timed releases (tap outputs)
            self._wait_and_process(deadline)

    def _advance(self, slot: _Slot) -> None:
        """Move a slot towards 'grabbed': reconnect or grab when possible."""
        if slot.source is None:
            if self._clock() >= slot.retry_at:
                self._try_open(slot)
            return
        if slot.grabbed:
            return
        source = slot.source
        try:
            if source.held_codes():
                if not slot.waiting_announced:
                    log.info("release all keys on %s to start remapping it", source.description)
                    slot.waiting_announced = True
                return
            # Events queued so far were already delivered to the desktop.
            # A tiny window remains between this read and the grab.
            source.read()
            source.grab()
        except InputDeviceLost:
            self._lose(slot)
            return
        slot.grabbed = True
        slot.waiting_announced = False
        log.info("grabbed %s", source.description)
        target = self._keyboard_target(slot)
        if target in self._output_leds:
            source.set_leds(self._output_leds[target])
        if not self._all_grabbed_announced and all(s.grabbed for s in self._slots):
            self._all_grabbed_announced = True
            log.info("remapping active")

    # InputControl for the engine: hide/restore passed-through modifiers.
    def mask(self, device_id: str, code: int) -> None:
        if self._router is not None and self._router.routes(device_id):
            self._router.mask(device_id, code)
            return
        source = self._source_of(device_id)
        if source is not None:
            source.mask(code)

    def unmask(self, device_id: str, code: int) -> None:
        if self._router is not None and self._router.routes(device_id):
            self._router.unmask(device_id, code)
            return
        source = self._source_of(device_id)
        if source is not None:
            source.unmask(code)

    def _keyboard_target(self, slot: _Slot) -> str | None:
        """The keyboard output whose LEDs this input shows (none with `to = own`)."""
        return None if slot.spec.own else slot.spec.target(OutputKind.KEYBOARD)

    def _apply_leds(self, changed: dict[str, frozenset[Led]]) -> None:
        """Show LEDs the desktop set on a keyboard output on its physical keyboards."""
        for output_id, leds in changed.items():
            self._output_leds[output_id] = leds
            for slot in self._slots:
                if slot.grabbed and slot.source and self._keyboard_target(slot) == output_id:
                    slot.source.set_leds(leds)

    def _source_of(self, device_id: str) -> InputSource | None:
        for slot in self._slots:
            if slot.spec.id == device_id:
                return slot.source
        return None

    def _leds_of(self, device_id: str) -> frozenset[Led]:
        for slot in self._slots:
            if slot.spec.id == device_id and slot.source is not None:
                return slot.source.leds()
        return frozenset()

    def _open(self, slot: _Slot) -> InputSource:
        """Open the device and check the axes its mappings use (§5.5 rule 7)."""
        source = self._inputs.open(slot.spec, slot.codes)
        ranges = source.axis_ranges()
        problems = []
        for threshold in sorted(slot.axes, key=lambda t: (t.axis, t.above, t.value)):
            if threshold.axis not in ranges:
                problems.append(f"does not report {threshold.describe().split()[0]}")
            elif reason := axis_problem(threshold, *ranges[threshold.axis]):
                problems.append(reason)
        if problems:
            source.close()
            raise InputError(f"input '{slot.spec.id}': {source.description} " + "; ".join(problems))
        assert self._router is not None
        try:
            plan = plan_route(slot.spec, self._config, source.capabilities())
            source.start_passthrough(plan)
        except InputError as exc:
            try:
                source.close()
            except InputError as close_exc:
                log.warning("closing %s: %s", source.description, close_exc)
            if isinstance(exc, InputRefused):
                raise InputRefused(f"{exc} ({source.description})") from None
            raise
        self._router.attach(slot.spec.id, plan)
        return source

    def _try_open(self, slot: _Slot, starting: bool = False) -> None:
        try:
            slot.source = self._open(slot)
        except InputError as exc:
            if starting and isinstance(exc, InputRefused):
                raise  # present at start but unusable: a configuration problem
            # Log each distinct reason once: the device being away is normal,
            # but a lasting permission or selector problem must be visible.
            # A refused device is left alone (§3.4 rule 2) and checked again.
            if str(exc) != slot.open_error:
                log.warning("waiting for input '%s': %s", slot.spec.id, exc)
            else:
                log.debug("input '%s' still not available", slot.spec.id)
            slot.open_error = str(exc)
            slot.retry_at = self._clock() + self._reconnect_interval
            return
        slot.open_error = None
        log.info("opened input '%s': %s", slot.spec.id, slot.source.description)
        self._opened(slot)

    def _opened(self, slot: _Slot) -> None:
        """Note the device's keys; once every input has been seen, check that
        each key mapped for every input exists somewhere (§3.1)."""
        assert slot.source is not None
        slot.key_codes = slot.source.key_codes()
        if self._shared_codes_checked or any(s.key_codes is None for s in self._slots):
            return
        if len(self._slots) < len(self._config.inputs):
            return  # still opening the inputs at startup
        self._shared_codes_checked = True
        available = frozenset().union(*(s.key_codes or frozenset() for s in self._slots))
        for code in sorted(self._config.shared_codes() - available):
            log.warning(
                "no input device has %s, so its mappings can never fire",
                codes.code_name(code),
            )
        ranges = [s.source.axis_ranges() for s in self._slots if s.source is not None]
        for threshold in sorted(self._config.shared_axes(), key=lambda t: (t.axis, t.value)):
            usable = [r[threshold.axis] for r in ranges if threshold.axis in r]
            if not any(axis_problem(threshold, *limits) is None for limits in usable):
                log.warning(
                    "no input device can trigger %s, so its mappings can never fire",
                    threshold.describe(),
                )

    def _wait_and_process(self, deadline: float | None) -> None:
        assert self._engine is not None
        wait = self._poll_interval
        now = self._clock()
        for limit in (deadline, self._engine.next_deadline()):
            if limit is not None:
                wait = max(0.0, min(wait, limit - now))
        by_source = {id(s.source): s for s in self._slots if s.source is not None}
        sources = [s.source for s in self._slots if s.source is not None]
        ready = self._inputs.wait(sources, wait, self._outputs.feedback_filenos())
        self._apply_leds(self._outputs.poll_leds())
        for source in ready:
            slot = by_source.get(id(source))
            if slot is not None and slot.source is source:
                self._process(slot)

    def _process(self, slot: _Slot) -> None:
        assert self._engine is not None and self._router is not None and slot.source is not None
        try:
            events = slot.source.read()
        except InputDeviceLost:
            self._lose(slot)
            return
        if not slot.grabbed:
            return  # the desktop received these events already
        watched = self._watched[slot.spec.id]
        routed = self._router.routes(slot.spec.id)
        for event, raw in events:
            if isinstance(event, AxisEvent):
                if event.code in watched:
                    # The axis drives thresholds and is suppressed (§5.5 rule 5).
                    for key_event in self._axis_triggers.update(event):
                        self._engine.handle(key_event)
                elif not (routed and self._router.axis(event.device, event.code, event.value)):
                    slot.source.forward(raw)
                continue
            consumed = event is not None and self._engine.handle(event)
            # Unmapped input goes to the outputs (§3.4); what no output
            # carries goes to the pass-through device.
            if not consumed and not (routed and event is not None and self._router.key(event)):
                slot.source.forward(raw)
            if event is not None and event.code in EMERGENCY_KEYS:
                self._track_emergency_key(slot.spec.id, event.code, event.action)
                if self._emergency_requested():
                    log.warning("emergency stop requested (Backspace+Escape+Enter held)")
                    return

    def _track_emergency_key(self, device_id: str, code: int, action: KeyAction) -> None:
        if action is KeyAction.PRESS:
            self._emergency_held.add((device_id, code))
        elif action is KeyAction.RELEASE:
            self._emergency_held.discard((device_id, code))

    def _emergency_requested(self) -> bool:
        return {code for _, code in self._emergency_held} >= EMERGENCY_KEYS

    def _lose(self, slot: _Slot) -> None:
        assert self._engine is not None and slot.source is not None
        log.error(
            "input device lost: %s; releasing its outputs and waiting for it to reconnect",
            slot.source.description,
        )
        assert self._router is not None
        self._engine.release_device(slot.spec.id)
        self._router.detach(slot.spec.id)
        self._axis_triggers.forget_device(slot.spec.id)
        self._emergency_held = {k for k in self._emergency_held if k[0] != slot.spec.id}
        try:
            slot.source.close()
        except InputError as exc:
            log.warning("cleanup of lost device %s: %s", slot.source.description, exc)
        slot.source = None
        slot.grabbed = False
        slot.waiting_announced = False
        slot.retry_at = self._clock() + self._reconnect_interval
        self._all_grabbed_announced = False

    def _should_stop(self, stop: StopFlag, deadline: float | None) -> StopReason | None:
        if self._emergency_requested():
            return StopReason.EMERGENCY
        if stop.is_set():
            return StopReason.STOPPED
        if deadline is not None and self._clock() >= deadline:
            return StopReason.TIMEOUT
        return None

    def _shutdown(self) -> list[str]:
        """Release, ungrab and destroy everything; return logged errors."""
        errors: list[str] = []
        if self._engine is not None:
            try:
                self._engine.release_all()
            except OutputError as exc:
                errors.append(str(exc))
                log.error("releasing outputs failed: %s", exc)
            self._engine = None
        if self._router is not None:
            try:
                self._router.detach_all()
            except OutputError as exc:
                errors.append(str(exc))
                log.error("releasing routed input failed: %s", exc)
            self._router = None
        for slot in self._slots:
            if slot.source is None:
                continue
            try:
                slot.source.close()
                log.info("released %s", slot.source.description)
            except InputError as exc:
                errors.append(str(exc))
                log.error("closing input %s failed: %s", slot.source.description, exc)
            slot.source = None
        self._slots.clear()
        try:
            self._outputs.close()
        except OutputError as exc:
            errors.append(str(exc))
            log.error("closing outputs failed: %s", exc)
        return errors

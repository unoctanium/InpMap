"""Remapping runtime: startup, event loop, reconnect and guaranteed cleanup.

Independent of CLI parsing so foreground mode, a future systemd service and
tests share it. Each configured input device moves through these states:

    opened  --no key held-->  grabbed  --lost-->  absent  --reopened-->  opened

* opened: not grabbed yet. Its events still reach the desktop, so they are
  read and discarded. Grabbing waits until no key is held, otherwise the
  desktop would never see the release of a key held at grab time.
* grabbed: events go to the engine; everything not consumed is forwarded.
* absent: the device disappeared. Outputs it held are released, its
  resources closed, and opening is retried periodically.

Startup creates the virtual outputs first, then opens all inputs; a missing
input at startup is a hard error (likely a configuration mistake). Cleanup
on every exit path: release engine outputs, ungrab and close inputs
(releasing forwarded keys), destroy the virtual devices.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
from typing import Protocol

from .config import Config
from .engine import MappingEngine
from .input import InputBackend, InputDeviceLost, InputError, InputSource
from .macros import Led
from .models import InputDeviceSpec
from .output import OutputBackend, OutputError, OutputManager

log = logging.getLogger(__name__)


class StopReason(Enum):
    STOPPED = "stopped"  # stop was requested (signal)
    TIMEOUT = "timeout"  # the configured run time elapsed


class StopFlag(Protocol):
    def is_set(self) -> bool: ...


class CleanupError(Exception):
    """Shutdown did not complete cleanly (details were logged)."""


@dataclass
class _Slot:
    """Runtime state of one configured input device."""

    spec: InputDeviceSpec
    codes: frozenset[int]
    source: InputSource | None = None
    grabbed: bool = False
    waiting_announced: bool = False
    retry_at: float = 0.0


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
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._config = config
        self._inputs = input_backend
        self._outputs = OutputManager(output_backend, config)
        self._poll_interval = poll_interval
        self._reconnect_interval = reconnect_interval
        self._clock = clock
        self._slots: list[_Slot] = []
        self._engine: MappingEngine | None = None
        self._all_grabbed_announced = False

    def run(self, stop: StopFlag, timeout: float | None = None) -> StopReason:
        """Run until ``stop`` is set or ``timeout`` seconds have passed.

        Raises InputError/OutputError on unrecoverable failures (after
        cleanup), and CleanupError if shutdown itself failed.
        """
        deadline = None if timeout is None else self._clock() + timeout
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

    def _start_and_loop(self, stop: StopFlag, deadline: float | None) -> StopReason:
        self._engine = MappingEngine(
            self._config, self._outputs, clock=self._clock, leds=self._leds_of
        )
        for device_id, spec in self._config.inputs.items():
            slot = _Slot(spec=spec, codes=self._config.input_codes(device_id))
            self._slots.append(slot)
            slot.source = self._inputs.open(spec, slot.codes)
            log.info("opened input '%s': %s", device_id, slot.source.description)
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
                self._try_reopen(slot)
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
        if not self._all_grabbed_announced and all(s.grabbed for s in self._slots):
            self._all_grabbed_announced = True
            log.info("remapping active")

    def _leds_of(self, device_id: str) -> frozenset[Led]:
        for slot in self._slots:
            if slot.spec.id == device_id and slot.source is not None:
                return slot.source.leds()
        return frozenset()

    def _try_reopen(self, slot: _Slot) -> None:
        try:
            slot.source = self._inputs.open(slot.spec, slot.codes)
        except InputError as exc:
            log.debug("input '%s' not available yet: %s", slot.spec.id, exc)
            slot.retry_at = self._clock() + self._reconnect_interval
            return
        log.info("input '%s' reconnected: %s", slot.spec.id, slot.source.description)

    def _wait_and_process(self, deadline: float | None) -> None:
        assert self._engine is not None
        wait = self._poll_interval
        now = self._clock()
        for limit in (deadline, self._engine.next_deadline()):
            if limit is not None:
                wait = max(0.0, min(wait, limit - now))
        by_source = {id(s.source): s for s in self._slots if s.source is not None}
        sources = [s.source for s in self._slots if s.source is not None]
        for source in self._inputs.wait(sources, wait):
            slot = by_source.get(id(source))
            if slot is not None and slot.source is source:
                self._process(slot)

    def _process(self, slot: _Slot) -> None:
        assert self._engine is not None and slot.source is not None
        try:
            events = slot.source.read()
        except InputDeviceLost:
            self._lose(slot)
            return
        if not slot.grabbed:
            return  # the desktop received these events already
        for event, raw in events:
            consumed = event is not None and self._engine.handle(event)
            if not consumed:
                slot.source.forward(raw)

    def _lose(self, slot: _Slot) -> None:
        assert self._engine is not None and slot.source is not None
        log.error(
            "input device lost: %s; releasing its outputs and waiting for it to reconnect",
            slot.source.description,
        )
        self._engine.release_device(slot.spec.id)
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

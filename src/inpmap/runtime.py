"""Remapping runtime: startup, event loop and guaranteed cleanup.

Independent of CLI parsing so foreground mode, a future systemd service and
tests share it. Startup order is chosen so that a failure never leaves a
grabbed device behind:

1. create virtual output devices;
2. open the physical input devices (not grabbed) and verify their codes;
3. per input device: wait until no key is held, discard events the desktop
   has already seen, then grab;
4. loop: read events, let the engine consume mapped ones, forward the rest.

Cleanup on every exit path: release engine outputs, ungrab and close inputs
(releasing forwarded keys), destroy the virtual devices.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from enum import Enum
from typing import Protocol

from .config import Config
from .engine import MappingEngine
from .input import InputBackend, InputDeviceLost, InputError, InputSource
from .output import OutputBackend, OutputError, OutputManager

log = logging.getLogger(__name__)


class StopReason(Enum):
    STOPPED = "stopped"  # stop was requested (signal)
    TIMEOUT = "timeout"  # the configured run time elapsed


class StopFlag(Protocol):
    def is_set(self) -> bool: ...


class CleanupError(Exception):
    """Shutdown did not complete cleanly (details were logged)."""


class Runtime:
    """Runs one configuration until stopped, timed out, or failed."""

    def __init__(
        self,
        config: Config,
        input_backend: InputBackend,
        output_backend: OutputBackend,
        *,
        poll_interval: float = 0.1,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._config = config
        self._inputs = input_backend
        self._outputs = OutputManager(output_backend, config)
        self._poll_interval = poll_interval
        self._clock = clock
        self._sleep = sleep
        self._sources: list[InputSource] = []
        self._engine: MappingEngine | None = None

    def run(self, stop: StopFlag, timeout: float | None = None) -> StopReason:
        """Run until ``stop`` is set or ``timeout`` seconds have passed.

        Raises InputError/OutputError on failures (after cleanup), and
        CleanupError if shutdown itself failed.
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
        self._open_inputs()
        self._engine = MappingEngine(self._config, self._outputs)
        for source in self._sources:
            reason = self._grab_when_released(source, stop, deadline)
            if reason is not None:
                return reason
        log.info("remapping active")
        return self._loop(stop, deadline)

    def _open_inputs(self) -> None:
        for device_id, spec in self._config.inputs.items():
            source = self._inputs.open(spec, self._config.input_codes(device_id))
            self._sources.append(source)
            log.info("opened input '%s': %s", device_id, source.description)

    def _grab_when_released(
        self, source: InputSource, stop: StopFlag, deadline: float | None
    ) -> StopReason | None:
        # Grabbing while a key is held would hide its release from the
        # desktop, leaving that key stuck there.
        if source.held_codes():
            log.info("release all keys on %s to start", source.description)
        while source.held_codes():
            reason = self._should_stop(stop, deadline)
            if reason is not None:
                return reason
            self._sleep(0.05)
        # Events queued so far were already delivered to the desktop.
        # A tiny window remains between this read and the grab.
        source.read()
        source.grab()
        log.info("grabbed %s", source.description)
        return None

    def _loop(self, stop: StopFlag, deadline: float | None) -> StopReason:
        assert self._engine is not None
        while True:
            reason = self._should_stop(stop, deadline)
            if reason is not None:
                return reason
            wait = self._poll_interval
            if deadline is not None:
                wait = max(0.0, min(wait, deadline - self._clock()))
            for source in self._inputs.wait(self._sources, wait):
                self._process(source)

    def _process(self, source: InputSource) -> None:
        assert self._engine is not None
        try:
            events = source.read()
        except InputDeviceLost:
            log.error("input device lost: %s", source.description)
            self._engine.release_device(source.spec.id)
            raise
        for event, raw in events:
            consumed = event is not None and self._engine.handle(event)
            if not consumed:
                source.forward(raw)

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
        for source in self._sources:
            try:
                source.close()
                log.info("released %s", source.description)
            except InputError as exc:
                errors.append(str(exc))
                log.error("closing input %s failed: %s", source.description, exc)
        self._sources.clear()
        try:
            self._outputs.close()
        except OutputError as exc:
            errors.append(str(exc))
            log.error("closing outputs failed: %s", exc)
        return errors

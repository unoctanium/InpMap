"""Macro execution (see docs/configuration.md §7).

A :class:`MacroRun` executes one macro after a trigger press. Its steps are
interpreted by Python generators ("fibers") that yield what they wait for —
time, trigger release, trigger press, another key, or other fibers — and
are resumed by the run when that happens. Nothing blocks: timed resumption
goes through the host's timer queue (the engine's), so runs are
deterministic under a fake clock.

Ownership: every key a run presses and every axis it holds is recorded and
given back when the run finishes or is cancelled.
"""

from __future__ import annotations

import logging
import random
from collections.abc import Callable, Generator, Iterable
from dataclasses import dataclass
from typing import Protocol

from .axes import AxisHolder, AxisKey, AxisStacks
from .macros import (
    MAX_REPEAT,
    AddVar,
    Count,
    Duration,
    HoldAxis,
    HoldKeys,
    IfEq,
    IfLayer,
    IfLed,
    IfSingle,
    IfTap,
    KeyRef,
    LayerAction,
    Led,
    Macro,
    MoveAxis,
    OnRelease,
    Parallel,
    Press,
    RandomRange,
    Release,
    Repeat,
    SetVar,
    Step,
    SwitchLayer,
    Tap,
    Toggle,
    VarRef,
    Wait,
    WhileHeld,
    WithKeys,
)

log = logging.getLogger(__name__)

RAMP_INTERVAL = 0.01  # seconds between axis updates during a ramp
MIN_LOOP_ITERATION = 0.001  # seconds; loops never spin faster


# -- what a fiber can wait for -------------------------------------------------


@dataclass
class Sleep:
    seconds: float


@dataclass
class WaitRelease:
    """Resumes with True when the trigger is released, False on timeout."""

    timeout: float | None = None


@dataclass
class WaitPress:
    """Resumes with True when the trigger is pressed, False on timeout."""

    timeout: float | None = None


@dataclass
class WaitSingle:
    """Resumes with "release", "other" (another key pressed) or "timeout"."""

    timeout: float | None = None


@dataclass
class Join:
    fibers: list[Fiber]


Wait_ = Sleep | WaitRelease | WaitPress | WaitSingle | Join
Program = Generator[Wait_, object, None]

_PENDING = object()


class MacroHost(Protocol):
    """What a run needs from its environment (implemented by the engine)."""

    variables: dict[str, object]
    rng: random.Random
    axes: AxisStacks

    def now(self) -> float: ...

    def schedule(self, delay: float, callback: Callable[[], None]) -> None: ...

    def press_key(self, key: KeyRef) -> None: ...

    def release_key(self, key: KeyRef) -> None: ...

    def led_on(self, input_device: str, led: Led) -> bool: ...

    def layer_active(self, layer: str) -> bool: ...

    def switch_layer(self, layer: str, action: LayerAction) -> None:
        """on/off/toggle; HOLD adds a holder, which ``release_layer`` removes."""
        ...

    def release_layer(self, layer: str) -> None: ...


class Fiber:
    def __init__(self, run: MacroRun, program: Program, on_done: Callable[[Fiber], None]):
        self.run = run
        self.program = program
        self.on_done = on_done
        self.token = 0  # invalidates stale wake-ups
        self.waiting: Wait_ | None = None
        self.done = False

    def resume(self, value: object = None) -> None:
        self.token += 1
        self.waiting = None
        while True:
            try:
                wait = self.program.send(value)
            except StopIteration:
                self.done = True
                self.on_done(self)
                return
            value = self.run.dispatch(self, wait)
            if value is _PENDING:
                return

    def wake(self, token: int, value: object) -> None:
        if token != self.token or self.done or self.run.cancelled:
            return
        self.run.forget_waiter(self)
        self.resume(value)

    def close(self) -> None:
        self.done = True
        self.program.close()


class MacroRun:
    """One execution of a macro, started by a trigger press."""

    def __init__(
        self,
        host: MacroHost,
        macro: Macro,
        trigger_device: str,
        on_finished: Callable[[MacroRun], None],
        name: str = "macro",
    ) -> None:
        self.host = host
        self.macro = macro
        self.trigger_device = trigger_device
        self.on_finished = on_finished
        self.name = name
        self.held = True
        self.cancelled = False
        self.finished = False
        self.toggle_stop = False
        self._fibers: list[Fiber] = []
        self._release_waiters: list[Fiber] = []
        self._press_waiters: list[Fiber] = []
        self._single_waiters: list[Fiber] = []
        self._joins: list[Fiber] = []
        self._owned_keys: list[KeyRef] = []
        self._held_layers: list[str] = []  # from `hold layer`
        self._axis_holders: dict[AxisKey, AxisHolder] = {}  # from MoveAxis steps
        self._temp_holders: list[AxisHolder] = []  # from HoldAxis steps
        self._main: Fiber | None = None
        self._release_started = False
        self._release_fiber: Fiber | None = None

    # -- lifecycle --------------------------------------------------------

    def start(self) -> None:
        if self.macro.max_run_ms is not None:
            self.host.schedule(self.macro.max_run_ms / 1000, self._max_run_reached)
        self._main = self.spawn(self.run_steps(self.macro.steps), self._main_done)

    def on_release(self) -> None:
        """The trigger was released."""
        if not self.held:
            return
        self.held = False
        for fiber in list(self._release_waiters):
            self._wake_now(fiber, True)
        for fiber in list(self._single_waiters):
            self._wake_now(fiber, "release")
        if self.finished or self.cancelled or self.macro.is_toggle:
            return
        if self.macro.on_release is OnRelease.CANCEL and self._main and not self._main.done:
            self._cancel_fibers()
            self._release_owned()
            self._main_done(self._main)
        elif self._main is not None and self._main.done:
            self._start_release_steps()

    def on_press(self) -> bool:
        """The trigger was pressed again. Returns True if a step consumed it."""
        self.held = True
        if self._press_waiters:
            for fiber in list(self._press_waiters):
                self._wake_now(fiber, True)
            return True
        if self.macro.is_toggle:
            self.toggle_stop = True
            return True
        return False

    def on_other_press(self) -> None:
        """Another key or button was pressed (for if_single)."""
        for fiber in list(self._single_waiters):
            self._wake_now(fiber, "other")

    def cancel(self) -> None:
        """Stop at once and give back everything the run owns."""
        if self.finished:
            return
        self.cancelled = True
        self._cancel_fibers()
        self._finish()

    @property
    def active(self) -> bool:
        return not self.finished

    # -- fibers -------------------------------------------------------------

    def spawn(self, program: Program, on_done: Callable[[Fiber], None] | None = None) -> Fiber:
        fiber = Fiber(self, program, on_done or self._child_done)
        self._fibers.append(fiber)
        fiber.resume()
        return fiber

    def dispatch(self, fiber: Fiber, wait: Wait_) -> object:
        """Return an immediate resume value, or _PENDING."""
        token = fiber.token
        timeout = getattr(wait, "timeout", None)
        if isinstance(wait, Sleep):
            if wait.seconds <= 0:
                return None
            self.host.schedule(wait.seconds, lambda: fiber.wake(token, None))
            fiber.waiting = wait
            return _PENDING
        if isinstance(wait, WaitRelease):
            if not self.held:
                return True
            if timeout is not None and timeout <= 0:
                return False
            self._release_waiters.append(fiber)
            default: object = False
        elif isinstance(wait, WaitPress):
            if timeout is not None and timeout <= 0:
                return False
            self._press_waiters.append(fiber)
            default = False
        elif isinstance(wait, WaitSingle):
            if not self.held:
                return "release"
            self._single_waiters.append(fiber)
            default = "timeout"
        elif isinstance(wait, Join):
            if all(child.done for child in wait.fibers):
                return None
            self._joins.append(fiber)
            fiber.waiting = wait
            return _PENDING
        else:  # pragma: no cover - guarded by the type
            raise TypeError(wait)
        fiber.waiting = wait
        if timeout is not None:
            self.host.schedule(timeout, lambda: fiber.wake(token, default))
        return _PENDING

    def forget_waiter(self, fiber: Fiber) -> None:
        for waiters in (self._release_waiters, self._press_waiters, self._single_waiters):
            if fiber in waiters:
                waiters.remove(fiber)
        if fiber in self._joins:
            self._joins.remove(fiber)

    def _wake_now(self, fiber: Fiber, value: object) -> None:
        fiber.wake(fiber.token, value)

    def _child_done(self, fiber: Fiber) -> None:
        for parent in list(self._joins):
            join = parent.waiting
            if isinstance(join, Join) and all(child.done for child in join.fibers):
                self._wake_now(parent, None)

    def _main_done(self, fiber: Fiber) -> None:
        if self.cancelled:
            return
        if self.macro.release_steps and not self.held:
            self._start_release_steps()
        elif not self.macro.release_steps:
            self._finish()
        # else: wait for the trigger release (on_release starts them)

    def _start_release_steps(self) -> None:
        if self._release_started or self.finished:
            return
        self._release_started = True
        if not self.macro.release_steps:
            self._finish()
            return
        self._release_fiber = self.spawn(
            self.run_steps(self.macro.release_steps), lambda f: self._finish()
        )

    def _cancel_fibers(self) -> None:
        for fiber in self._fibers:
            if not fiber.done:
                fiber.close()
        for waiters in (self._release_waiters, self._press_waiters, self._single_waiters):
            waiters.clear()
        self._joins.clear()

    def _finish(self) -> None:
        if self.finished:
            return
        self.finished = True
        self._release_owned()
        self.on_finished(self)

    def _max_run_reached(self) -> None:
        if not self.finished:
            log.warning(
                "%s exceeded max_run_ms (%g ms); cancelled", self.name, self.macro.max_run_ms
            )
            self.cancel()

    # -- ownership ---------------------------------------------------------

    def press(self, key: KeyRef) -> None:
        self._owned_keys.append(key)
        self.host.press_key(key)

    def release(self, key: KeyRef) -> None:
        if key in self._owned_keys:
            self._owned_keys.remove(key)
            self.host.release_key(key)

    def _release_owned(self) -> None:
        keys, self._owned_keys = self._owned_keys, []
        for key in reversed(keys):
            self.host.release_key(key)
        layers, self._held_layers = self._held_layers, []
        for layer in reversed(layers):
            self.host.release_layer(layer)
        holders = [*self._temp_holders, *self._axis_holders.values()]
        self._temp_holders.clear()
        self._axis_holders.clear()
        for holder in holders:
            self.host.axes.release(holder)

    # -- values ----------------------------------------------------------------

    def ms(self, duration: Duration) -> float:
        if isinstance(duration, RandomRange):
            return self.host.rng.uniform(duration.min_ms, duration.max_ms)
        if isinstance(duration, VarRef):
            value = self.host.variables[duration.name]
            return max(0.0, float(value))  # type: ignore[arg-type]
        return float(duration)

    def count(self, count: Count) -> int:
        value = self.host.variables[count.name] if isinstance(count, VarRef) else count
        return min(max(int(value), 0), MAX_REPEAT)  # type: ignore[call-overload]

    def pause(self, duration: Duration | None) -> Program:
        ms = self.macro.key_pause_ms if duration is None else self.ms(duration)
        if ms > 0:
            yield Sleep(ms / 1000)

    # -- step interpreters --------------------------------------------------------

    def run_steps(self, steps: Iterable[Step]) -> Program:
        for step in steps:
            yield from self.step(step)

    def step(self, step: Step) -> Program:  # noqa: C901 - a flat dispatch is clearest here
        if isinstance(step, Tap):
            for key in step.keys:
                self.press(key)
                yield from self.pause(step.pause)
            for key in reversed(step.keys):
                self.release(key)
                yield from self.pause(step.pause)
        elif isinstance(step, Press):
            for key in step.keys:
                self.press(key)
                yield from self.pause(step.pause)
        elif isinstance(step, Release):
            for key in step.keys:
                self.release(key)
                yield from self.pause(step.pause)
        elif isinstance(step, HoldKeys):
            yield from self.with_keys(step.keys, self.wait_release())
        elif isinstance(step, WithKeys):
            yield from self.with_keys(step.keys, self.run_steps(step.steps))
        elif isinstance(step, MoveAxis):
            yield from self.move_axis(step)
        elif isinstance(step, HoldAxis):
            yield from self.hold_axis(step)
        elif isinstance(step, Wait):
            ms = self.ms(step.duration)
            if ms > 0:
                yield Sleep(ms / 1000)
        elif isinstance(step, Repeat):
            for _ in range(self.count(step.count)):
                yield from self.run_steps(step.steps)
        elif isinstance(step, WhileHeld):
            while self.held:
                yield from self.loop_iteration(step.steps)
        elif isinstance(step, Toggle):
            while not self.toggle_stop:
                yield from self.loop_iteration(step.steps)
        elif isinstance(step, Parallel):
            children = [self.spawn(self.run_steps(branch)) for branch in step.branches]
            yield Join(children)
        elif isinstance(step, IfTap):
            yield from self.run_steps(
                step.then if (yield from self.tapped(step)) else step.otherwise
            )
        elif isinstance(step, IfSingle):
            timeout = None if step.timeout_ms is None else step.timeout_ms / 1000
            result = (yield WaitSingle(timeout)) if self.held else "release"
            yield from self.run_steps(step.then if result == "release" else step.otherwise)
        elif isinstance(step, IfEq):
            equal = self.host.variables[step.var] == step.value
            yield from self.run_steps(step.then if equal else step.otherwise)
        elif isinstance(step, IfLed):
            lit = self.host.led_on(self.trigger_device, step.led)
            yield from self.run_steps(step.then if lit else step.otherwise)
        elif isinstance(step, IfLayer):
            active = self.host.layer_active(step.layer)
            yield from self.run_steps(step.then if active else step.otherwise)
        elif isinstance(step, SwitchLayer) and step.action is LayerAction.HOLD:
            self._held_layers.append(step.layer)
            self.host.switch_layer(step.layer, LayerAction.HOLD)
            yield from self.wait_release()
            if step.layer in self._held_layers:
                self._held_layers.remove(step.layer)
                self.host.release_layer(step.layer)
        elif isinstance(step, SwitchLayer):
            self.host.switch_layer(step.layer, step.action)
        elif isinstance(step, SetVar):
            self.host.variables[step.var] = step.value
        elif isinstance(step, AddVar):
            self.host.variables[step.var] += step.value  # type: ignore[operator]
        else:  # pragma: no cover - the parser only creates known steps
            raise TypeError(f"unknown step {step!r}")

    def with_keys(self, keys: tuple[KeyRef, ...], body: Program) -> Program:
        for key in keys:
            self.press(key)
            yield from self.pause(None)
        yield from body
        for key in reversed(keys):
            self.release(key)
            yield from self.pause(None)

    def wait_release(self) -> Program:
        if self.held:
            yield WaitRelease()

    def loop_iteration(self, steps: tuple[Step, ...]) -> Program:
        started = self.host.now()
        yield from self.run_steps(steps)
        elapsed = self.host.now() - started
        if elapsed < MIN_LOOP_ITERATION:
            yield Sleep(MIN_LOOP_ITERATION - elapsed)

    def tapped(self, step: IfTap) -> Generator[Wait_, object, bool]:
        timeout = step.timeout_ms / 1000
        if self.held:
            return bool((yield WaitRelease(timeout)))
        started = self.host.now()
        if not (yield WaitPress(timeout)):
            return False
        remaining = timeout - (self.host.now() - started)
        return bool((yield WaitRelease(remaining)))

    def move_axis(self, step: MoveAxis) -> Program:
        key = (step.device, step.code)
        holder = self._axis_holders.get(key)
        if holder is None:
            holder = self.host.axes.acquire(key)
            self._axis_holders[key] = holder
        yield from self.ramp(holder, step.to, self.ms(step.over))

    def hold_axis(self, step: HoldAxis) -> Program:
        holder = self.host.axes.acquire((step.device, step.code))
        self._temp_holders.append(holder)
        yield from self.ramp(holder, step.value, self.ms(step.attack))
        yield from self.wait_release()
        yield from self.ramp(holder, self.host.axes.below(holder), self.ms(step.release))
        self._temp_holders.remove(holder)
        self.host.axes.release(holder)

    def ramp(self, holder: AxisHolder, target: float, ms: float) -> Program:
        if ms <= 0:
            self.host.axes.update(holder, target)
            return
        start_value = holder.value
        started = self.host.now()
        duration = ms / 1000
        while True:
            elapsed = self.host.now() - started
            yield Sleep(min(RAMP_INTERVAL, max(duration - elapsed, 0.0)) or RAMP_INTERVAL)
            elapsed = self.host.now() - started
            if elapsed >= duration - 1e-9:  # end exactly on target despite float error
                self.host.axes.update(holder, target)
                return
            fraction = elapsed / duration
            self.host.axes.update(holder, start_value + (target - start_value) * fraction)

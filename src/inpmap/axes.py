"""Ownership of gamepad axes by several holders (see docs/configuration.md §7.3).

Each axis has a stack of holders. The most recent holder's value is written;
when it lets go, the next holder's value applies again, or else the axis'
*base*: the value of a physical axis routed to it (§3.4), the most recently
updated one if several devices send to the same axis. Without a base the
axis returns to rest. Within :meth:`AxisStacks.batch`, writes are deferred and only the
final value of each axis is written, which avoids a jump to rest when a
holder is replaced (e.g. a macro restarting on a new press).
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager

from .macros import AXIS_REST

AxisKey = tuple[str, int]  # (output device id, axis code)


class AxisHolder:
    """One claim on an axis; its value can change over time (ramps)."""

    def __init__(self, key: AxisKey, value: float) -> None:
        self.key = key
        self.value = value


class AxisStacks:
    def __init__(self, write: Callable[[str, int, float], None]) -> None:
        self._write = write
        self._stacks: dict[AxisKey, list[AxisHolder]] = {}
        # Routed device values per axis, in the order they were last updated.
        self._bases: dict[AxisKey, dict[object, float]] = {}
        self._written: dict[AxisKey, float] = {}
        self._batch_depth = 0
        self._dirty: set[AxisKey] = set()

    def current(self, key: AxisKey) -> float:
        """The value last written to the axis."""
        return self._written.get(key, AXIS_REST)

    def acquire(self, key: AxisKey, value: float | None = None) -> AxisHolder:
        """Push a new holder (starting at the current value by default)."""
        holder = AxisHolder(key, self.current(key) if value is None else value)
        self._stacks.setdefault(key, []).append(holder)
        self._apply(key)
        return holder

    def update(self, holder: AxisHolder, value: float) -> None:
        holder.value = value
        self._apply(holder.key)

    def release(self, holder: AxisHolder) -> None:
        stack = self._stacks.get(holder.key, [])
        if holder in stack:
            stack.remove(holder)
            if not stack:
                del self._stacks[holder.key]
            self._apply(holder.key)

    def below(self, holder: AxisHolder) -> float:
        """Value the axis returns to when ``holder`` lets go."""
        stack = self._stacks.get(holder.key, [])
        others = [h for h in stack if h is not holder]
        return others[-1].value if others else self._base(holder.key)

    def set_base(self, key: AxisKey, owner: object, value: float) -> None:
        """Set the value a routed device gives the axis (shown while no holder holds it)."""
        bases = self._bases.setdefault(key, {})
        bases.pop(owner, None)  # re-insert: most recently updated last
        bases[owner] = value
        self._apply(key)

    def clear_base(self, key: AxisKey, owner: object) -> None:
        """Forget a device's value (device lost or detached)."""
        bases = self._bases.get(key, {})
        if owner in bases:
            del bases[owner]
            if not bases:
                del self._bases[key]
            self._apply(key)

    def _base(self, key: AxisKey) -> float:
        bases = self._bases.get(key)
        return next(reversed(bases.values())) if bases else AXIS_REST

    def holders(self) -> list[AxisHolder]:
        return [h for stack in self._stacks.values() for h in stack]

    @contextmanager
    def batch(self) -> Iterator[None]:
        self._batch_depth += 1
        try:
            yield
        finally:
            self._batch_depth -= 1
            if self._batch_depth == 0:
                dirty, self._dirty = self._dirty, set()
                for key in sorted(dirty):
                    self._apply(key)

    def _apply(self, key: AxisKey) -> None:
        if self._batch_depth:
            self._dirty.add(key)
            return
        stack = self._stacks.get(key)
        value = stack[-1].value if stack else self._base(key)
        if self._written.get(key, AXIS_REST) == value:
            return
        self._write(key[0], key[1], value)
        if value == AXIS_REST:
            self._written.pop(key, None)
        else:
            self._written[key] = value

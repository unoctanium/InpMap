"""Modifier state and trigger matching (docs/dsl.md §4.0).

The state is the set of modifier keys currently held on any input device.
A trigger matches when exactly its required modifiers are held: required
groups on the required side, every other modifier group released.
``any_modifiers`` (``modifiers(ignore)``) matches whatever is held.
"""

from __future__ import annotations

from collections.abc import Iterable

from .models import MODIFIER_KEYS, InputTrigger, KeyAction, MappingRule, Modifier, Side

HeldKey = tuple[str, int]  # (input device id, code)


class ModifierState:
    def __init__(self, active: Iterable[Modifier]) -> None:
        self._groups = frozenset(active)
        self._codes: dict[int, tuple[Modifier, Side]] = {}
        for modifier in self._groups:
            left, right = MODIFIER_KEYS[modifier]
            self._codes[left] = (modifier, Side.LEFT)
            self._codes[right] = (modifier, Side.RIGHT)
        self._held: set[HeldKey] = set()

    def is_modifier(self, code: int) -> bool:
        return code in self._codes

    def update(self, device: str, code: int, action: KeyAction) -> None:
        if code not in self._codes:
            return
        if action is KeyAction.PRESS:
            self._held.add((device, code))
        elif action is KeyAction.RELEASE:
            self._held.discard((device, code))

    def held_keys(self) -> frozenset[HeldKey]:
        return frozenset(self._held)

    def sides(self, modifier: Modifier) -> frozenset[Side]:
        held = (self._codes[code] for _device, code in self._held)
        return frozenset(side for group, side in held if group is modifier)

    def forget_device(self, device: str) -> None:
        self._held = {key for key in self._held if key[0] != device}

    def matches(self, trigger: InputTrigger) -> bool:
        if trigger.any_modifiers:
            return True
        required = {r.modifier: r.side for r in trigger.modifiers}
        for modifier in self._groups:
            held = self.sides(modifier)
            side = required.get(modifier)
            if side is None:
                if held:
                    return False
            elif side is Side.EITHER:
                if not held:
                    return False
            elif held != {side}:
                return False
        return True


def specificity(trigger: InputTrigger) -> tuple[int, int]:
    """Higher is more specific: exact before ignore, sided before either."""
    if trigger.any_modifiers:
        return (0, 0)
    return (1, sum(r.side is not Side.EITHER for r in trigger.modifiers))


def choose(candidates: list[MappingRule], state: ModifierState) -> MappingRule | None:
    """The best matching rule; on equal specificity the first defined wins."""
    best: MappingRule | None = None
    for rule in candidates:
        if state.matches(rule.trigger) and (
            best is None or specificity(rule.trigger) > specificity(best.trigger)
        ):
            best = rule
    return best

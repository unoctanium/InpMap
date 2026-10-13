"""Key and button code vocabulary.

Codes are identified by their Linux names (``KEY_X``, ``BTN_SOUTH``) and
integer values from ``linux/input-event-codes.h``. This module is pure data
and must not import evdev, so the core stays backend-independent.
"""

from __future__ import annotations

from ._linux_codes import CANONICAL_NAMES, CODES

# Inclusive ranges of EV_KEY codes that belong to joysticks/gamepads:
# BTN_TRIGGER..BTN_DEAD, BTN_SOUTH..BTN_THUMBR, BTN_DPAD_UP..BTN_DPAD_RIGHT,
# BTN_TRIGGER_HAPPY1..BTN_TRIGGER_HAPPY40.
GAMEPAD_BUTTON_RANGES: tuple[tuple[int, int], ...] = (
    (0x120, 0x12F),
    (0x130, 0x13E),
    (0x220, 0x223),
    (0x2C0, 0x2E7),
)


def code_from_name(name: str) -> int | None:
    """Return the code for a ``KEY_*``/``BTN_*`` name, or None if unknown."""
    return CODES.get(name)


def code_name(code: int) -> str:
    """Return the canonical name of a code (aliases resolve to one name)."""
    return CANONICAL_NAMES.get(code, f"{code:#x}")


def all_names() -> list[str]:
    """Return every known code name, including aliases."""
    return list(CODES)


def is_gamepad_button(code: int) -> bool:
    """Whether ``code`` lies in a joystick/gamepad button range."""
    return any(low <= code <= high for low, high in GAMEPAD_BUTTON_RANGES)

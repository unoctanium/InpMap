"""Key and button code vocabulary.

Codes are identified by their Linux names (``KEY_X``, ``BTN_SOUTH``) and
integer values from ``linux/input-event-codes.h``. This module is pure data
and must not import evdev, so the core stays backend-independent.
"""

from __future__ import annotations

from dataclasses import dataclass

from ._linux_codes import CANONICAL_NAMES, CODES

# Inclusive ranges of EV_KEY codes that belong to joysticks/gamepads:
# BTN_TRIGGER..BTN_DEAD, BTN_SOUTH..BTN_THUMBR, BTN_DPAD_UP..BTN_DPAD_RIGHT
# plus the back paddles BTN_GRIPL..BTN_GRIPR2, BTN_TRIGGER_HAPPY1..40.
GAMEPAD_BUTTON_RANGES: tuple[tuple[int, int], ...] = (
    (0x120, 0x12F),
    (0x130, 0x13E),
    (0x220, 0x227),
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


# What the virtual outputs always carry (docs/configuration.md §3.3): a
# keyboard every KEY_* code, a gamepad the standard buttons. Codes that
# mappings send are added on top.
KEYBOARD_OUTPUT_KEYS: frozenset[int] = frozenset(
    code for name, code in CODES.items() if name.startswith("KEY_")
)
GAMEPAD_OUTPUT_BUTTONS: frozenset[int] = frozenset(
    CODES[name]
    for name in (
        "BTN_SOUTH",
        "BTN_EAST",
        "BTN_X",
        "BTN_Y",
        "BTN_TL",
        "BTN_TR",
        "BTN_TL2",
        "BTN_TR2",
        "BTN_SELECT",
        "BTN_START",
        "BTN_MODE",
        "BTN_THUMBL",
        "BTN_THUMBR",
        "BTN_DPAD_UP",
        "BTN_DPAD_DOWN",
        "BTN_DPAD_LEFT",
        "BTN_DPAD_RIGHT",
    )
)


# An emulated DualSense Edge (configuration.md §3.5): the standard buttons
# plus its back paddles (BTN_GRIPL/R) and Fn buttons (BTN_GRIPL2/R2), always.
DUALSENSE_EDGE_BUTTONS: frozenset[int] = GAMEPAD_OUTPUT_BUTTONS | frozenset(
    CODES[name] for name in ("BTN_GRIPL", "BTN_GRIPR", "BTN_GRIPL2", "BTN_GRIPR2")
)


@dataclass(frozen=True)
class CodeEntry:
    """One key/button code for listings (``inpmap codes``)."""

    name: str  # canonical name
    code: int
    aliases: tuple[str, ...]
    sent_by: str  # output type that can send it: "keyboard", "gamepad", or "" (input only)


def catalog() -> list[CodeEntry]:
    """Every key/button code, ordered by value, with its aliases."""
    names: dict[int, list[str]] = {}
    for name, code in CODES.items():
        names.setdefault(code, []).append(name)
    entries = []
    for code in sorted(names):
        canonical = code_name(code)
        if canonical.startswith("KEY_"):
            sent_by = "keyboard"
        elif is_gamepad_button(code):
            sent_by = "gamepad"
        else:
            sent_by = ""  # e.g. mouse buttons: usable as mapping triggers only
        aliases = tuple(n for n in names[code] if n != canonical)
        entries.append(CodeEntry(canonical, code, aliases, sent_by))
    return entries


# Linux ABS codes that may be triggers (values from linux/input-event-codes.h).
TRIGGER_AXES: dict[str, int] = {
    "ABS_X": 0x00,
    "ABS_Y": 0x01,
    "ABS_Z": 0x02,
    "ABS_RX": 0x03,
    "ABS_RY": 0x04,
    "ABS_RZ": 0x05,
    "ABS_THROTTLE": 0x06,
    "ABS_RUDDER": 0x07,
    "ABS_WHEEL": 0x08,
    "ABS_GAS": 0x09,
    "ABS_BRAKE": 0x0A,
    "ABS_HAT0X": 0x10,
    "ABS_HAT0Y": 0x11,
    "ABS_HAT1X": 0x12,
    "ABS_HAT1Y": 0x13,
    "ABS_HAT2X": 0x14,
    "ABS_HAT2Y": 0x15,
    "ABS_HAT3X": 0x16,
    "ABS_HAT3Y": 0x17,
}
TRIGGER_AXIS_NAMES = {code: name for name, code in TRIGGER_AXES.items()}

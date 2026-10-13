import pytest

from inpmap import codes


def test_known_codes_match_linux_values():
    assert codes.code_from_name("KEY_X") == 45
    assert codes.code_from_name("KEY_Y") == 21
    assert codes.code_from_name("BTN_SOUTH") == 0x130


def test_alias_has_canonical_name():
    assert codes.code_from_name("BTN_A") == codes.code_from_name("BTN_SOUTH")
    assert codes.code_name(0x130) == "BTN_SOUTH"


def test_range_markers_are_not_names():
    for marker in ("KEY_MAX", "KEY_CNT", "KEY_RESERVED", "BTN_GAMEPAD", "BTN_MISC"):
        assert codes.code_from_name(marker) is None


def test_unknown_code_name_formatting():
    assert codes.code_name(0xFFFF) == "0xffff"


@pytest.mark.parametrize("name", ["BTN_SOUTH", "BTN_THUMBR", "BTN_TRIGGER", "BTN_DPAD_UP"])
def test_gamepad_buttons(name):
    assert codes.is_gamepad_button(codes.code_from_name(name))


@pytest.mark.parametrize("name", ["BTN_LEFT", "KEY_A", "BTN_TOOL_PEN"])
def test_non_gamepad_buttons(name):
    assert not codes.is_gamepad_button(codes.code_from_name(name))


def test_table_matches_installed_evdev():
    """The checked-in table must agree with the Linux backend library."""
    ecodes = pytest.importorskip("evdev.ecodes")
    mismatches = {
        name: (value, getattr(ecodes, name, None))
        for name in codes.all_names()
        if getattr(ecodes, name, None) != (value := codes.code_from_name(name))
    }
    assert mismatches == {}

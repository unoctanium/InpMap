import pytest

from inpmap import codes


def test_known_codes_match_linux_values():
    assert codes.code_from_name("KEY_X") == 45
    assert codes.code_from_name("KEY_Y") == 21
    assert codes.code_from_name("BTN_FACE_DOWN") == 0x130


def test_alias_has_canonical_name():
    assert codes.code_from_name("KEY_SCREENLOCK") == codes.code_from_name("KEY_COFFEE")
    assert codes.code_name(codes.code_from_name("KEY_SCREENLOCK")) == "KEY_COFFEE"


def test_face_buttons_have_position_names_only():
    """configuration.md §3.3: InpMap's own names; the Linux names are gone."""
    assert [codes.code_name(c) for c in (0x130, 0x131, 0x133, 0x134)] == [
        "BTN_FACE_DOWN",
        "BTN_FACE_RIGHT",
        "BTN_FACE_LEFT",
        "BTN_FACE_UP",
    ]
    for old, new in codes.RENAMED_FACE_BUTTONS.items():
        assert codes.code_from_name(old) is None
        assert codes.code_from_name(new) is not None


def test_range_markers_are_not_names():
    for marker in ("KEY_MAX", "KEY_CNT", "KEY_RESERVED", "BTN_GAMEPAD", "BTN_MISC"):
        assert codes.code_from_name(marker) is None


def test_unknown_code_name_formatting():
    assert codes.code_name(0xFFFF) == "0xffff"


@pytest.mark.parametrize(
    "name", ["BTN_FACE_DOWN", "BTN_THUMBR", "BTN_TRIGGER", "BTN_DPAD_UP", "BTN_GRIPL", "BTN_GRIPR2"]
)
def test_gamepad_buttons(name):
    assert codes.is_gamepad_button(codes.code_from_name(name))


@pytest.mark.parametrize("name", ["BTN_LEFT", "KEY_A", "BTN_TOOL_PEN"])
def test_non_gamepad_buttons(name):
    assert not codes.is_gamepad_button(codes.code_from_name(name))


def test_table_matches_installed_evdev():
    """The checked-in table must agree with the Linux backend library."""
    ecodes = pytest.importorskip("evdev.ecodes")
    # Names missing in evdev are fine: an evdev built against older kernel
    # headers (e.g. on the CI runner) simply does not know the newest keys.
    # A name with a *different* value would be a real error.
    mismatches = {
        name: (value, getattr(ecodes, name))
        for name in codes.all_names()
        if hasattr(ecodes, name) and getattr(ecodes, name) != (value := codes.code_from_name(name))
    }
    assert mismatches == {}
    assert hasattr(ecodes, "KEY_X") and hasattr(ecodes, "BTN_TRIGGER")  # the check ran
    # Our own face button names stand for the codes of evdev's Linux names.
    assert [codes.code_from_name(f"BTN_FACE_{p}") for p in ("DOWN", "RIGHT", "LEFT", "UP")] == [
        ecodes.BTN_SOUTH,
        ecodes.BTN_EAST,
        ecodes.BTN_NORTH,
        ecodes.BTN_WEST,
    ]


def test_catalog_lists_each_code_once_with_aliases_and_sender():
    from inpmap.codes import catalog

    entries = {entry.name: entry for entry in catalog()}
    assert len(entries) == len({entry.code for entry in catalog()})
    assert entries["BTN_FACE_DOWN"].aliases == () and entries["BTN_FACE_DOWN"].sent_by == "gamepad"
    assert entries["KEY_COFFEE"].aliases == ("KEY_SCREENLOCK",)
    assert entries["KEY_KP1"].sent_by == "keyboard"
    assert entries["BTN_LEFT"].sent_by == ""  # mouse button: only usable as a trigger
    assert "BTN_SOUTH" not in entries

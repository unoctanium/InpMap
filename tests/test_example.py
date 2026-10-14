"""The example that comes with InpMap (docs/configuration.md §10)."""

import pytest

from inpmap.data_files import example_text, syntax_file
from inpmap.dsl.compiler import compile_text
from inpmap.trace import trace

WITH_KEYBOARD = example_text().replace(
    "version 1\n", 'version 1\n\ninput kbd {\n    name = "Kbd"\n}\n', 1
)


def downs(mapping, **scenario):
    config = compile_text(WITH_KEYBOARD, "example.inpmap").config
    lines = [t.text for t in trace(config, mapping, seed=1, **scenario)]
    return [" ".join(line.split()[:2]) for line in lines if line.endswith("down")]


def test_valid_without_and_with_a_keyboard():
    compile_text(example_text(), "example.inpmap")
    compile_text(WITH_KEYBOARD, "example.inpmap")


@pytest.mark.parametrize(
    "mapping, scenario, expected",
    [
        ("KEY_F1", {}, ["keyboard KEY_A", "gamepad BTN_SOUTH"]),
        ("KEY_F2", {"press_at": [0, 150], "hold_ms": 50}, ["keyboard KEY_2"]),
        ("KEY_F2", {"hold_ms": 500}, ["keyboard KEY_3"]),
        ("KEY_F3", {}, ["keyboard KEY_Q", "gamepad BTN_EAST"]),
        ("KEY_F7+ctrl", {}, ["keyboard KEY_LEFTCTRL", "keyboard KEY_C"]),
        (
            "KEY_F8",
            {"press_at": [0, 300]},
            ["keyboard KEY_LEFTSHIFT", "keyboard KEY_H", "keyboard KEY_I"] * 2
            + ["keyboard KEY_LEFTSHIFT", "keyboard KEY_1"],
        ),
        ("KEY_CAPSLOCK", {"hold_ms": 50}, ["keyboard KEY_ESC"]),
        ("nav:KEY_W", {}, ["keyboard KEY_UP"]),
        ("KEY_INSERT", {}, []),
    ],
)
def test_the_tour_does_what_its_comments_say(mapping, scenario, expected):
    assert downs(mapping, **scenario) == expected


def test_gamepad_lines_work_when_uncommented():
    text = WITH_KEYBOARD.replace(
        'input kbd {\n    name = "Kbd"\n}\n',
        'input kbd {\n    name = "Kbd"\n}\n\ninput pad {\n    name = "Pad"\n}\n',
    ).replace("# map pad.", "map pad.")
    config = compile_text(text, "example.inpmap").config
    assert {"pad.ABS_RZ_above_0.5", "pad.ABS_HAT0Y_below_-0.5"} <= {m.id for m in config.mappings}


def test_syntax_files():
    assert syntax_file("kate").startswith("<?xml") and 'name="InpMap"' in syntax_file("kate")
    assert "syntax inpmap" in syntax_file("nano")

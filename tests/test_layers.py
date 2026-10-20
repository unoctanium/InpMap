"""Layers (docs/configuration.md §5.6, §6.10)."""

import pytest
from test_modifiers import Rig

from inpmap.config import ConfigError
from inpmap.dsl.compiler import compile_text

BASE = """
map kbd.KEY_CAPSLOCK { if single { tap KEY_ESC } else { hold layer nav } }
map kbd.KEY_F1 { layer nav toggle }
map kbd.KEY_F2 { layer nav off }
map kbd.KEY_F3 { if layer nav { tap KEY_1 } else { tap KEY_2 } }
map kbd.KEY_E { hold KEY_E }
layer nav {
    map kbd.KEY_W { hold KEY_UP }
    map KEY_E { hold KEY_END }
    map kbd.KEY_Q { disable }
}
"""


def names(rig):
    return [name for _, name in rig.log()]


def test_hold_layer_while_held_and_fall_through_to_the_base():
    rig = Rig(BASE)
    assert rig.press("KEY_W") is False  # layer off: W is not mapped, passes through
    rig.press("KEY_CAPSLOCK")
    assert rig.press("KEY_W") is True  # 'if single' chose the layer before W is looked up
    rig.release("KEY_W")
    assert rig.press("KEY_Q") is True  # disabled in the layer
    rig.release("KEY_Q")
    assert rig.press("KEY_R") is False  # mapped nowhere: passes through
    rig.release("KEY_CAPSLOCK")
    assert rig.press("KEY_W") is False  # layer gone again
    assert names(rig) == ["KEY_UP", "KEY_UP"]
    assert rig.engine.active_layers() == []


def test_layer_beats_base_and_held_keys_keep_their_mapping():
    rig = Rig(BASE)
    rig.press("KEY_F1")  # toggle on
    rig.release("KEY_F1")
    rig.press("KEY_E")  # layer mapping (every input) wins over the base's kbd.KEY_E
    rig.press("KEY_F1")  # toggle off while E is held
    rig.release("KEY_F1")
    rig.release("KEY_E")  # released through the layer mapping: END goes up
    rig.press("KEY_E")
    rig.release("KEY_E")
    assert names(rig) == ["KEY_END", "KEY_END", "KEY_E", "KEY_E"]


def test_off_does_not_end_a_hold_and_toggle_respects_it():
    rig = Rig(BASE + "map kbd.KEY_F4 { hold layer nav }\n")
    rig.press("KEY_F4")
    rig.press("KEY_F2")  # off: the hold keeps the layer
    assert rig.engine.active_layers() == ["nav"]
    rig.press("KEY_F1")  # toggle while active (held): switches 'on' off, still held
    assert rig.engine.active_layers() == ["nav"]
    rig.release("KEY_F4")
    assert rig.engine.active_layers() == []


def test_if_layer_condition():
    rig = Rig(BASE)
    rig.press("KEY_F3")
    rig.release("KEY_F3")
    rig.at(100)  # let the tap finish before F3 is pressed again
    rig.press("KEY_F1")
    rig.release("KEY_F1")
    rig.press("KEY_F3")
    rig.release("KEY_F3")
    rig.at(200)
    assert [n for n in names(rig) if n in ("KEY_1", "KEY_2")] == [
        "KEY_2",
        "KEY_2",
        "KEY_1",
        "KEY_1",
    ]


def test_most_recently_activated_layer_wins():
    body = """
map kbd.KEY_F5 { layer a toggle }
map kbd.KEY_F6 { layer b toggle }
layer a { map kbd.KEY_X { hold KEY_A } }
layer b { map kbd.KEY_X { hold KEY_B } }
"""
    rig = Rig(body)
    for key in ("KEY_F6", "KEY_F5"):  # b, then a
        rig.press(key)
        rig.release(key)
    rig.press("KEY_X")
    rig.release("KEY_X")
    rig.press("KEY_F5")  # a off: b is left
    rig.release("KEY_F5")
    rig.press("KEY_X")
    rig.release("KEY_X")
    assert names(rig) == ["KEY_A", "KEY_A", "KEY_B", "KEY_B"]


def test_layers_are_global_across_devices():
    rig = Rig("map pad.BTN_FACE_UP { hold layer nav }\nlayer nav { map kbd.KEY_W { hold KEY_UP } }")
    rig.press("BTN_FACE_UP", "pad")
    rig.press("KEY_W")
    rig.release("KEY_W")
    assert names(rig) == ["KEY_UP", "KEY_UP"]


def test_hold_is_given_back_when_the_run_is_cancelled():
    rig = Rig(BASE + "map kbd.KEY_F4 { hold layer nav }\n")
    rig.press("KEY_F4")
    assert rig.engine.active_layers() == ["nav"]
    rig.engine.release_device("kbd")  # device lost: its runs are cancelled
    assert rig.engine.active_layers() == []


# -- language --------------------------------------------------------------------------------

HEADER = 'version 1\ninput kbd { name = "K" }\noutput keyboard { type = keyboard }\n'


def problems(text):
    with pytest.raises(ConfigError) as info:
        compile_text(HEADER + text, "t.inpmap")
    return info.value.problems


def test_names_and_same_trigger_in_each_layer():
    config = compile_text(
        HEADER
        + "map KEY_X { hold KEY_Y }\nmap KEY_F1 { layer a on }\n"
        + "layer a { map KEY_X { hold KEY_Z }; map KEY_Y as named { tap KEY_A } }\n",
        "t.inpmap",
    ).config
    assert [(m.id, m.layer) for m in config.mappings] == [
        ("KEY_X", None),
        ("KEY_F1", None),
        ("a:KEY_X", "a"),
        ("named", "a"),
    ]
    assert config.layers == ("a",)


@pytest.mark.parametrize(
    "text, message",
    [
        ("map KEY_X { layer nope on }\n", "t.inpmap:4:19: unknown layer 'nope'"),
        ("map KEY_X { hold layer nope }\n", "unknown layer 'nope'"),
        ("map KEY_X { if layer nope { tap KEY_A } }\n", "unknown layer 'nope'"),
        ("layer a { }\nmap KEY_X { layer a on }\n", "layer 'a' has no mappings"),
        (
            "layer a { map KEY_X { tap KEY_A } }\nlayer a { map KEY_Y { tap KEY_A } }\n",
            "layer 'a' is already defined at line 4",
        ),
        (
            "layer a { map KEY_X { tap KEY_A }; map KEY_X { tap KEY_B } }\n",
            "already mapped at line 4",
        ),
        ("layer map { map KEY_X { tap KEY_A } }\n", "unexpected"),
    ],
)
def test_layer_errors(text, message):
    assert any(message in p for p in problems(text)), problems(text)

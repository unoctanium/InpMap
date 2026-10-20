"""Where unmapped input goes: `to` and its defaults (docs/configuration.md §3.4)."""

import pytest

from inpmap.config import ConfigError
from inpmap.dsl.compiler import compile_text
from inpmap.models import OutputKind

KEYBOARD, GAMEPAD = OutputKind.KEYBOARD, OutputKind.GAMEPAD


def config(text):
    return compile_text("version 1\n" + text, "t.inpmap").config


def problems(text):
    with pytest.raises(ConfigError) as info:
        config(text)
    return info.value.problems


def test_each_kind_goes_to_its_only_output():
    c = config(
        """input kbd { name = "K" }
output keyboard { type = keyboard }
output gamepad { type = gamepad }
map KEY_X { hold BTN_FACE_DOWN }
"""
    )
    spec = c.inputs["kbd"]
    assert not spec.own
    assert (spec.target(KEYBOARD), spec.target(GAMEPAD)) == ("keyboard", "gamepad")


def test_to_chooses_an_output_and_other_kinds_keep_their_default():
    c = config(
        """input pad1 { name = "P1"; to = gamepad1 }
input pad2 { name = "P2"; to = gamepad2 }
output keyboard { type = keyboard }
output gamepad1 { type = gamepad }
output gamepad2 { type = gamepad }
map pad1.BTN_FACE_RIGHT { hold gamepad1.BTN_FACE_DOWN }
map pad2.BTN_FACE_RIGHT { hold gamepad2.BTN_FACE_DOWN }
"""
    )
    assert c.inputs["pad1"].targets == ((GAMEPAD, "gamepad1"), (KEYBOARD, "keyboard"))
    assert c.inputs["pad2"].target(GAMEPAD) == "gamepad2"


def test_to_with_one_output_per_kind():
    c = config(
        """input kbd { name = "K"; to = keyboard2, gamepad2 }
output keyboard1 { type = keyboard }
output keyboard2 { type = keyboard }
output gamepad1 { type = gamepad }
output gamepad2 { type = gamepad }
map KEY_A { hold keyboard1.KEY_B; hold gamepad1.BTN_FACE_DOWN }
"""
    )
    assert c.inputs["kbd"].targets == ((GAMEPAD, "gamepad2"), (KEYBOARD, "keyboard2"))


def test_to_own_keeps_a_device_of_its_own():
    c = config(
        """input stick { name = "Flight Stick"; to = own }
output keyboard { type = keyboard }
map stick.BTN_TRIGGER { tap KEY_SPACE }
"""
    )
    assert c.inputs["stick"].own and c.inputs["stick"].targets == ()


def test_several_outputs_of_a_kind_require_to():
    found = problems(
        """input kbd { name = "K" }
output gamepad1 { type = gamepad }
output gamepad2 { type = gamepad }
map KEY_A { hold gamepad1.BTN_FACE_DOWN; hold gamepad2.BTN_FACE_DOWN }
"""
    )
    assert found == [
        "t.inpmap:2:1: there are several gamepad outputs (gamepad1, gamepad2); "
        "choose one, e.g. to = gamepad1"
    ]


@pytest.mark.parametrize(
    "to, message",
    [
        ("nowhere", "unknown output device 'nowhere' (defined outputs: gamepad, keyboard)"),
        ("keyboard, own", "'own' cannot be combined with outputs"),
        ("keyboard, keyboard", "'keyboard' and 'keyboard' are both keyboard outputs"),
        ('"keyboard"', "'to' takes output names or 'own'"),
    ],
)
def test_wrong_to(to, message):
    found = problems(
        f"""input kbd {{ name = "K"; to = {to} }}
output keyboard {{ type = keyboard }}
output gamepad {{ type = gamepad }}
map KEY_A {{ hold BTN_FACE_DOWN }}
"""
    )
    assert len(found) == 1 and found[0].startswith("t.inpmap:2:") and message in found[0]


def test_an_output_reached_only_by_unmapped_input_is_used():
    # No mapping sends keys, but the keyboard's other keys go to `keyboard`.
    c = config(
        """input kbd { name = "K" }
output keyboard { type = keyboard }
output gamepad { type = gamepad }
map KEY_W { hold BTN_DPAD_UP }
"""
    )
    assert set(c.outputs) == {"keyboard", "gamepad"}


def test_an_input_reaching_an_output_is_used_without_mappings():
    c = config(
        """input kbd { name = "K" }
input kbd2 { name = "K2" }
output keyboard { type = keyboard }
map kbd.KEY_CAPSLOCK { tap KEY_ESC }
"""
    )
    assert c.inputs["kbd2"].target(KEYBOARD) == "keyboard"


def test_own_is_reserved():
    assert "is a reserved word" in problems('input own { name = "K" }\n')[0]

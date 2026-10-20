"""`emulate = "dualsense-edge"` in the language and routing (configuration.md §3.5)."""

import pytest

from inpmap.codes import DUALSENSE_EDGE_BUTTONS, code_from_name
from inpmap.config import ConfigError
from inpmap.dsl.compiler import compile_text
from inpmap.models import OutputKind
from inpmap.output import output_capabilities
from inpmap.routing import DeviceCapabilities, InputRefused, plan_route

EDGE = """version 1
input pad { name = "Pad" }
output gamepad {
    type    = gamepad
    emulate = "dualsense-edge"
}
"""


def c(name):
    return code_from_name(name)


def config(text):
    return compile_text(text, "t.inpmap").config


def problems(text):
    with pytest.raises(ConfigError) as info:
        config(text)
    return info.value.problems


def test_emulate_is_recorded_on_the_output():
    spec = config(EDGE + "map pad.BTN_FACE_RIGHT { hold BTN_GRIPR }").outputs["gamepad"]
    assert (spec.kind, spec.emulate, spec.name) == (
        OutputKind.GAMEPAD,
        "dualsense-edge",
        "InpMap gamepad",
    )


def test_plain_gamepad_has_no_emulation():
    text = 'version 1\ninput pad { name = "Pad" }\noutput gamepad { type = gamepad }\n'
    assert (
        config(text + "map pad.BTN_FACE_RIGHT { hold BTN_FACE_DOWN }").outputs["gamepad"].emulate
        is None
    )


def test_paddles_and_fn_buttons_are_accepted():
    body = "\n".join(
        f"map pad.{trigger} {{ hold {code} }}"
        for trigger, code in (
            ("BTN_TRIGGER_HAPPY1", "BTN_GRIPL"),
            ("BTN_TRIGGER_HAPPY2", "BTN_GRIPR"),
            ("BTN_TRIGGER_HAPPY3", "BTN_GRIPL2"),
            ("BTN_TRIGGER_HAPPY4", "BTN_GRIPR2"),
        )
    )
    config(EDGE + body)


def test_buttons_the_edge_does_not_have_are_errors_with_position():
    found = problems(EDGE + "map pad.BTN_FACE_RIGHT { hold BTN_TRIGGER_HAPPY5 }")
    assert len(found) == 1
    assert found[0].startswith("t.inpmap:7:")
    assert "emulates a DualSense Edge, which has no BTN_TRIGGER_HAPPY5" in found[0]


def test_buttons_in_macros_are_checked_too():
    found = problems(EDGE + "map pad.BTN_FACE_RIGHT { tap BTN_TRIGGER_HAPPY5 }")
    assert any("has no BTN_TRIGGER_HAPPY5" in p for p in found)


def test_unknown_emulation_is_an_error():
    found = problems(
        EDGE.replace('"dualsense-edge"', '"dualshock"')
        + "map pad.BTN_FACE_RIGHT { hold BTN_FACE_DOWN }"
    )
    assert len(found) == 1
    assert found[0].startswith("t.inpmap:5:")
    assert "unknown controller 'dualshock' to emulate (expected one of: dualsense-edge)" in found[0]


def test_emulate_on_a_keyboard_is_an_error():
    text = (
        'version 1\ninput kbd { name = "K" }\n'
        'output keyboard { type = keyboard; emulate = "dualsense-edge" }\n'
        "map KEY_A { tap KEY_B }"
    )
    found = problems(text)
    assert len(found) == 1 and "only a gamepad output can emulate a controller" in found[0]


def test_fixed_capabilities():
    caps = output_capabilities(OutputKind.GAMEPAD, frozenset(), "dualsense-edge")
    assert caps.keys == DUALSENSE_EDGE_BUTTONS
    assert {c("BTN_GRIPL"), c("BTN_GRIPR2")} <= caps.keys
    plain = output_capabilities(OutputKind.GAMEPAD, frozenset())
    assert c("BTN_GRIPL") not in plain.keys  # only when mapped (§3.3)


def test_physical_paddles_route_to_the_emulated_pad():
    cfg = config(EDGE + "map pad.BTN_FACE_RIGHT { hold BTN_FACE_DOWN }")
    caps = DeviceCapabilities(
        keys=frozenset({c("BTN_FACE_DOWN"), c("BTN_FACE_RIGHT"), c("BTN_GRIPL")})
    )
    plan = plan_route(cfg.inputs["pad"], cfg, caps)
    assert plan.keys[c("BTN_GRIPL")] == "gamepad"  # without a mapping that sends it


def test_unmapped_buttons_the_edge_lacks_refuse_the_device():
    cfg = config(EDGE + "map pad.BTN_FACE_RIGHT { hold BTN_FACE_DOWN }")
    caps = DeviceCapabilities(keys=frozenset({c("BTN_FACE_DOWN"), c("BTN_TRIGGER_HAPPY1")}))
    with pytest.raises(InputRefused, match="BTN_TRIGGER_HAPPY1"):
        plan_route(cfg.inputs["pad"], cfg, caps)

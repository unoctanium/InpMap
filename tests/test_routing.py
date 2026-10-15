"""Route planning: where a device's unmapped input goes (docs/configuration.md §3.4)."""

import pytest

from inpmap.codes import TRIGGER_AXES as ABS
from inpmap.codes import code_from_name
from inpmap.dsl.compiler import compile_text
from inpmap.macros import AxisKind
from inpmap.routing import AxisRoute, DeviceCapabilities, InputRefused, plan_route


def c(name):
    return code_from_name(name)


def keys(*names):
    return frozenset(c(n) for n in names)


STICK = (-32768, 32767)
TRIGGER = (0, 255)
HAT = (-1, 1)
ABS_VOLUME, ABS_MISC, ABS_MT_SLOT = 0x20, 0x28, 0x2F
REL_X, REL_Y, REL_WHEEL = 0x00, 0x01, 0x08

KEYBOARD = DeviceCapabilities(keys=keys("KEY_ESC", "KEY_A", "KEY_F13", "KEY_LEFTCTRL"))
XBOX_PAD = DeviceCapabilities(
    keys=keys(
        "BTN_SOUTH",
        "BTN_EAST",
        "BTN_NORTH",
        "BTN_WEST",
        "BTN_TL",
        "BTN_TR",
        "BTN_SELECT",
        "BTN_START",
        "BTN_MODE",
        "BTN_THUMBL",
        "BTN_THUMBR",
    ),  # fmt: skip
    axes={
        ABS["ABS_X"]: STICK,
        ABS["ABS_Y"]: STICK,
        ABS["ABS_RX"]: STICK,
        ABS["ABS_RY"]: STICK,
        ABS["ABS_Z"]: TRIGGER,
        ABS["ABS_RZ"]: TRIGGER,
        ABS["ABS_HAT0X"]: HAT,
        ABS["ABS_HAT0Y"]: HAT,
    },  # fmt: skip
)
# The Raiju's keyboard interface: keys, a wheel and a volume axis.
PAD_KEYS = DeviceCapabilities(
    keys=keys("KEY_F13", "KEY_F14", "KEY_ENTER"),
    axes={ABS_VOLUME: (0, 1023)},
    relative=frozenset({REL_WHEEL, 0x06}),
)
GAMING_MOUSE = DeviceCapabilities(
    keys=keys("BTN_LEFT", "BTN_RIGHT", "BTN_SIDE", "KEY_VOLUMEUP"),
    axes={ABS_VOLUME: (0, 1023)},
    relative=frozenset({REL_X, REL_Y, REL_WHEEL}),
)
TOUCHPAD = DeviceCapabilities(
    keys=keys("BTN_LEFT", "BTN_TOUCH", "BTN_TOOL_FINGER"),
    axes={ABS["ABS_X"]: (0, 1920), ABS["ABS_Y"]: (0, 1080), ABS_MT_SLOT: (0, 4)},
)
DINPUT_PAD = DeviceCapabilities(
    keys=keys("BTN_TRIGGER", "BTN_THUMB", "BTN_THUMB2", "BTN_TOP"),
    axes={
        ABS["ABS_X"]: (0, 255),
        ABS["ABS_Y"]: (0, 255),
        ABS["ABS_Z"]: (0, 255),
        ABS["ABS_RZ"]: (0, 255),
    },  # fmt: skip
)
FLIGHT_STICK = DeviceCapabilities(
    keys=keys("BTN_SOUTH"),
    axes={ABS["ABS_X"]: STICK, ABS["ABS_THROTTLE"]: (0, 255)},
)

BOTH_OUTPUTS = """
output keyboard { type = keyboard }
output gamepad { type = gamepad }
"""


def plan(caps, text, device="dev"):
    config = compile_text(f'version 1\ninput {device} {{ name = "D" }}\n' + text, "t.inpmap").config
    return plan_route(config.inputs[device], config, caps)


def refusal(caps, text):
    with pytest.raises(InputRefused) as info:
        plan(caps, text)
    return str(info.value)


def test_keyboard_keys_go_to_the_keyboard_output():
    p = plan(KEYBOARD, BOTH_OUTPUTS + "map KEY_A { hold BTN_SOUTH }")
    assert p.keys == {code: "keyboard" for code in KEYBOARD.keys}
    assert not p.axes and not p.needs_passthrough


def test_xbox_pad_goes_completely_to_the_gamepad_output():
    p = plan(XBOX_PAD, BOTH_OUTPUTS + "map BTN_SOUTH { hold KEY_SPACE }")
    assert p.keys == {code: "gamepad" for code in XBOX_PAD.keys}
    assert {code: (r.output, r.kind) for code, r in p.axes.items()} == {
        ABS["ABS_X"]: ("gamepad", AxisKind.STICK),
        ABS["ABS_Y"]: ("gamepad", AxisKind.STICK),
        ABS["ABS_RX"]: ("gamepad", AxisKind.STICK),
        ABS["ABS_RY"]: ("gamepad", AxisKind.STICK),
        ABS["ABS_Z"]: ("gamepad", AxisKind.TRIGGER),
        ABS["ABS_RZ"]: ("gamepad", AxisKind.TRIGGER),
        ABS["ABS_HAT0X"]: ("gamepad", AxisKind.HAT),
        ABS["ABS_HAT0Y"]: ("gamepad", AxisKind.HAT),
    }
    assert not p.needs_passthrough


def test_pad_keyboard_interface_passes_wheel_and_volume_through():
    p = plan(PAD_KEYS, BOTH_OUTPUTS + "map KEY_F13 { hold BTN_GRIPL }")
    assert p.keys == {code: "keyboard" for code in PAD_KEYS.keys}
    assert p.passthrough_axes == {ABS_VOLUME}
    assert p.passthrough_relative == PAD_KEYS.relative
    assert p.needs_passthrough


def test_mouse_parts_pass_through_and_its_keys_go_to_the_keyboard():
    p = plan(GAMING_MOUSE, BOTH_OUTPUTS + "map BTN_SIDE { tap KEY_F5 }")
    assert p.passthrough_keys == keys("BTN_LEFT", "BTN_RIGHT", "BTN_SIDE")
    assert p.keys == {c("KEY_VOLUMEUP"): "keyboard"}
    assert p.passthrough_relative == {REL_X, REL_Y, REL_WHEEL}


def test_keys_without_keyboard_output_refuse_the_device():
    message = refusal(KEYBOARD, "output gamepad { type = gamepad }\nmap KEY_A { hold BTN_SOUTH }")
    assert message.startswith("input 'dev' is not taken over")
    assert "it has keys (KEY_ESC, KEY_LEFTCTRL, KEY_F13)" in message
    assert "add: output keyboard { type = keyboard }" in message


def test_keys_that_mappings_use_need_no_target():
    caps = DeviceCapabilities(keys=keys("KEY_W", "KEY_S"))
    p = plan(caps, "output gamepad { type = gamepad }\nmap KEY_W { hold BTN_DPAD_UP }\n"
                   "map KEY_S { hold BTN_DPAD_DOWN }")  # fmt: skip
    assert p.keys == {}


def test_pad_without_gamepad_output_is_refused():
    message = refusal(XBOX_PAD, "output keyboard { type = keyboard }\nmap BTN_SOUTH { tap KEY_A }")
    assert "gamepad or joystick parts (BTN_EAST, BTN_NORTH, BTN_WEST, BTN_TL, BTN_TR, … " in message
    assert "add: output gamepad { type = gamepad }, or use `to = own`" in message


def test_directinput_pad_is_refused_with_a_hint_to_own():
    message = refusal(DINPUT_PAD, BOTH_OUTPUTS + "map KEY_A { hold BTN_SOUTH }")
    assert "BTN_TRIGGER, BTN_THUMB, BTN_THUMB2, BTN_TOP" in message
    assert "use `to = own`" in message


def test_centred_axis_on_a_trigger_is_refused():
    caps = DeviceCapabilities(keys=keys("BTN_SOUTH"), axes={ABS["ABS_RZ"]: STICK})
    message = refusal(caps, BOTH_OUTPUTS + "map KEY_A { hold BTN_SOUTH }")
    assert "ABS_RZ is centred like a stick but is a trigger" in message


def test_flight_stick_axes_are_refused():
    message = refusal(FLIGHT_STICK, BOTH_OUTPUTS + "map KEY_A { hold BTN_SOUTH }")
    assert "gamepad or joystick parts (ABS_THROTTLE)" in message


def test_touchpad_is_refused():
    message = refusal(TOUCHPAD, BOTH_OUTPUTS + "map KEY_A { hold BTN_SOUTH }")
    assert "is a touchpad, touchscreen or tablet" in message and "`to = own`" in message


def test_own_passes_everything_through():
    config = compile_text(
        'version 1\ninput dev { name = "D"; to = own }\noutput keyboard { type = keyboard }\n'
        "map dev.BTN_TOUCH { tap KEY_A }",
        "t.inpmap",
    ).config
    p = plan_route(config.inputs["dev"], config, TOUCHPAD)
    assert p.own and p.needs_passthrough and not p.keys


def test_mapped_extra_button_needs_no_target_and_mapped_paddle_is_routed():
    caps = DeviceCapabilities(keys=keys("BTN_SOUTH", "BTN_TRIGGER_HAPPY1"))
    p = plan(caps, BOTH_OUTPUTS + "map BTN_TRIGGER_HAPPY1 { hold BTN_GRIPL }")
    assert p.keys == {c("BTN_SOUTH"): "gamepad"}
    # A paddle on the physical pad goes to the gamepad once a mapping adds it there.
    caps = DeviceCapabilities(keys=keys("BTN_SOUTH", "BTN_GRIPL"))
    p = plan(caps, BOTH_OUTPUTS + "map KEY_F13 { hold BTN_GRIPL }")
    assert p.keys[c("BTN_GRIPL")] == "gamepad"


def test_axes_used_as_triggers_are_not_routed():
    p = plan(XBOX_PAD, BOTH_OUTPUTS + "map dev.ABS_RZ above 0.5 { hold KEY_SPACE }")
    assert ABS["ABS_RZ"] not in p.axes and ABS["ABS_Z"] in p.axes


def test_explicit_target():
    text = (
        'version 1\ninput dev { name = "D"; to = gamepad2 }\n'
        "output keyboard { type = keyboard }\noutput gamepad1 { type = gamepad }\n"
        "output gamepad2 { type = gamepad }\n"
        "map KEY_A { hold gamepad1.BTN_SOUTH; hold gamepad2.BTN_SOUTH }"
    )
    config = compile_text(text, "t.inpmap").config
    p = plan_route(config.inputs["dev"], config, XBOX_PAD)
    assert set(p.keys.values()) == {"gamepad2"}
    assert {r.output for r in p.axes.values()} == {"gamepad2"}


def test_misc_axis_passes_through():
    caps = DeviceCapabilities(keys=keys("KEY_A"), axes={ABS_MISC: (0, 255)})
    assert plan(caps, BOTH_OUTPUTS + "map KEY_A { hold BTN_SOUTH }").passthrough_axes == {ABS_MISC}


@pytest.mark.parametrize(
    "kind, low, high, raw, value",
    [
        (AxisKind.STICK, -32768, 32767, 0, 0.0),
        (AxisKind.STICK, -32768, 32767, 32767, 1.0),
        (AxisKind.STICK, -32768, 32767, -16384, -0.5),
        (AxisKind.STICK, 0, 255, 0, -1.0),  # unsigned stick, centre at 127.5
        (AxisKind.STICK, 0, 255, 255, 1.0),
        (AxisKind.TRIGGER, 0, 255, 255, 1.0),
        (AxisKind.TRIGGER, 0, 1023, 0, 0.0),
        (AxisKind.TRIGGER, 0, 255, 300, 1.0),  # out of range: clamped
        (AxisKind.HAT, -1, 1, -1, -1.0),
        (AxisKind.HAT, -1, 1, 0, 0.0),
        (AxisKind.HAT, -1, 1, 1, 1.0),
        (AxisKind.STICK, 5, 5, 5, 0.0),  # broken range
    ],
)
def test_axis_values(kind, low, high, raw, value):
    assert AxisRoute("gamepad", kind, low, high).value(raw) == pytest.approx(value)

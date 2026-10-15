"""Route planning: where a device's unmapped input goes (docs/configuration.md §3.4)."""

import pytest

from inpmap.axis_triggers import normalize
from inpmap.codes import TRIGGER_AXES as ABS
from inpmap.codes import code_from_name
from inpmap.dsl.compiler import compile_text
from inpmap.engine import MappingEngine
from inpmap.macros import AxisKind
from inpmap.models import InputEvent, KeyAction
from inpmap.routing import AxisRoute, DeviceCapabilities, InputRefused, Router, plan_route


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
# The Raiju's keyboard interface: keys, a misc button, a wheel and a volume axis.
PAD_KEYS = DeviceCapabilities(
    keys=keys("KEY_F13", "KEY_F14", "KEY_ENTER", "BTN_0"),
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
    assert p.keys == {code: "keyboard" for code in keys("KEY_F13", "KEY_F14", "KEY_ENTER")}
    assert p.passthrough_keys == keys("BTN_0")
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
    normalized = normalize(raw, low, high)
    assert AxisRoute("gamepad", kind, low, high).value(normalized) == pytest.approx(value)


# -- the router -------------------------------------------------------------


PRESS, RELEASE, REPEAT = KeyAction.PRESS, KeyAction.RELEASE, KeyAction.REPEAT


class Sink:
    def __init__(self):
        self.events = []

    def press(self, device, code):
        self.events.append((device, code, 1))

    def release(self, device, code):
        self.events.append((device, code, 0))

    def set_axis(self, device, code, value):
        self.events.append((device, code, value))


def routed(text, caps, device="dev"):
    """Engine + router as the runtime wires them: the router hides modifiers."""
    config = compile_text(f'version 1\ninput {device} {{ name = "D" }}\n' + text, "t.inpmap").config
    sink = Sink()
    router_box = []
    engine = MappingEngine(config, sink, clock=lambda: 0.0, inputs=_Control(router_box))
    router = Router(engine)
    router_box.append(router)
    router.attach(device, plan_route(config.inputs[device], config, caps))
    return engine, router, sink


class _Control:
    def __init__(self, box):
        self.box = box

    def mask(self, device, code):
        self.box[0].mask(device, code)

    def unmask(self, device, code):
        self.box[0].unmask(device, code)


def feed(engine, router, device, code, action):
    """What the runtime does with a key event: engine first, then the router."""
    event = InputEvent(device, code, action)
    if not engine.handle(event):
        assert router.key(event)


def test_unmapped_keys_go_to_the_keyboard_output_and_repeats_are_dropped():
    engine, router, sink = routed(BOTH_OUTPUTS + "map KEY_ESC { hold BTN_SOUTH }", KEYBOARD)
    a = c("KEY_A")
    for action in (PRESS, REPEAT, REPEAT, RELEASE):
        feed(engine, router, "dev", a, action)
    assert sink.events == [("keyboard", a, 1), ("keyboard", a, 0)]


def test_button_held_on_the_pad_and_by_a_mapping_stays_down_until_both_let_go():
    engine, router, sink = routed(BOTH_OUTPUTS + "map BTN_TL { hold BTN_SOUTH }", XBOX_PAD)
    south, tl = c("BTN_SOUTH"), c("BTN_TL")
    feed(engine, router, "dev", south, PRESS)
    feed(engine, router, "dev", tl, PRESS)
    feed(engine, router, "dev", south, RELEASE)
    assert sink.events == [("gamepad", south, 1)]  # still held by the mapping
    feed(engine, router, "dev", tl, RELEASE)
    assert sink.events == [("gamepad", south, 1), ("gamepad", south, 0)]


def test_modifier_is_hidden_while_a_mapping_with_modifiers_runs():
    engine, router, sink = routed(
        "output keyboard { type = keyboard }\nmap KEY_F7 modifiers(ctrl) { hold KEY_C }",
        DeviceCapabilities(keys=keys("KEY_LEFTCTRL", "KEY_F7", "KEY_C")),
    )
    ctrl, f7, key_c = c("KEY_LEFTCTRL"), c("KEY_F7"), c("KEY_C")
    feed(engine, router, "dev", ctrl, PRESS)
    feed(engine, router, "dev", f7, PRESS)
    feed(engine, router, "dev", f7, RELEASE)
    feed(engine, router, "dev", ctrl, RELEASE)
    assert sink.events == [
        ("keyboard", ctrl, 1),
        ("keyboard", ctrl, 0),  # hidden: the mapping's output is a plain C
        ("keyboard", key_c, 1),
        ("keyboard", key_c, 0),
        ("keyboard", ctrl, 1),  # given back while still held
        ("keyboard", ctrl, 0),
    ]


def test_axes_go_to_the_gamepad_and_a_mapping_overrides_them():
    engine, router, sink = routed(BOTH_OUTPUTS + "map BTN_TL { axis ABS_X 1.0 }", XBOX_PAD)
    x = ABS["ABS_X"]
    assert router.axis("dev", x, -0.5)
    feed(engine, router, "dev", c("BTN_TL"), PRESS)
    assert router.axis("dev", x, 1.0)  # moved while overridden: not visible
    feed(engine, router, "dev", c("BTN_TL"), RELEASE)
    assert sink.events == [("gamepad", x, -0.5), ("gamepad", x, 1.0)]
    assert router.axis("dev", ABS["ABS_HAT0Y"], -1.0)
    assert sink.events[-1] == ("gamepad", ABS["ABS_HAT0Y"], -1.0)


def test_detach_releases_held_keys_and_returns_axes_to_rest():
    engine, router, sink = routed(BOTH_OUTPUTS + "map BTN_TL { hold KEY_A }", XBOX_PAD)
    feed(engine, router, "dev", c("BTN_SOUTH"), PRESS)
    router.axis("dev", ABS["ABS_RZ"], 1.0)
    router.detach("dev")
    assert sink.events[-2:] == [("gamepad", c("BTN_SOUTH"), 0), ("gamepad", ABS["ABS_RZ"], 0.0)]
    assert not router.routes("dev")


def test_mouse_parts_belong_on_the_pass_through_device():
    engine, router, sink = routed(BOTH_OUTPUTS + "map BTN_SIDE { tap KEY_F5 }", GAMING_MOUSE)
    assert not router.key(InputEvent("dev", c("BTN_LEFT"), PRESS))
    assert not router.axis("dev", ABS_VOLUME, 0.5)
    assert sink.events == []


def test_unmapped_press_of_a_key_without_target_is_dropped():
    caps = DeviceCapabilities(keys=keys("KEY_W"))
    engine, router, sink = routed(
        "output gamepad { type = gamepad }\nmap KEY_W modifiers(ctrl) { hold BTN_DPAD_UP }", caps
    )
    assert router.key(InputEvent("dev", c("KEY_W"), PRESS))  # handled: dropped
    assert sink.events == []

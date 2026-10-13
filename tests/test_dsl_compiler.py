import pytest

from inpmap.codes import code_from_name as c
from inpmap.config import ConfigError
from inpmap.dsl.compiler import compile_text
from inpmap.macros import (
    GAMEPAD_AXES,
    AddVar,
    HoldAxis,
    HoldKeys,
    IfEq,
    IfLed,
    IfSingle,
    IfTap,
    KeyRef,
    Led,
    MoveAxis,
    OnRelease,
    OnRetrigger,
    Parallel,
    RandomRange,
    Repeat,
    SetVar,
    Tap,
    Toggle,
    VarRef,
    Wait,
)
from inpmap.models import Modifier, ModifierRequirement, Side

HEADER = """version 1
input kbd { name = "Kbd" }
output keyboard { type = keyboard }
output gamepad { type = gamepad }
"""


# Keeps both outputs in use, so tests may use just one of them.
ANCHOR = "\nmap KEY_F24 { hold KEY_F23; hold BTN_MODE }\n"


def compile_maps(body: str, header: str = HEADER, **kw):
    return compile_text(header + body + ANCHOR, "t.inpmap", **kw).config


def macro_of(body: str, header: str = HEADER):
    return compile_maps(body, header).mappings[0].macros[0]


def problems(text: str) -> list[str]:
    with pytest.raises(ConfigError) as info:
        compile_text(text, "t.inpmap")
    return info.value.problems


def K(name, device="keyboard"):
    return KeyRef(device, c(name))


# -- top level -------------------------------------------------------------------------


def test_settings_variables_devices():
    config = compile_text(
        """version 1
settings { key_pause = 5ms; modifiers = ctrl, alt }
let n = 0
let f = 1.5
let d = 50ms
let s = "game"
let b = false
input kbd { path = "/dev/input/by-id/x" }
output keyboard { type = keyboard; name = "My Keyboard" }
map KEY_A { tap KEY_B }
""",
        "t.inpmap",
    ).config
    assert config.settings.key_pause_ms == 5
    assert config.settings.modifiers == {Modifier.CTRL, Modifier.ALT}
    assert config.variables == {"n": 0, "f": 1.5, "d": 50.0, "s": "game", "b": False}
    assert config.inputs["kbd"].path == "/dev/input/by-id/x"
    assert config.outputs["keyboard"].name == "My Keyboard"


# -- mappings ----------------------------------------------------------------------------


def test_plain_outputs_and_default_ids():
    config = compile_maps(
        """
map KEY_X { hold KEY_Y; hold BTN_SOUTH }
map KEY_W { axis ABS_Y { target = -1.0; attack = 150ms; release = 50ms } }
map KEY_D { axis ABS_X 1.0 (attack 10ms) }
"""
    )
    x, w, d = config.mappings[:-1]  # without the anchor
    assert x.id == "KEY_X" and not x.macros
    assert [(o.device, o.code) for o in x.outputs] == [
        ("keyboard", c("KEY_Y")),
        ("gamepad", c("BTN_SOUTH")),
    ]
    assert (w.axes[0].value, w.axes[0].attack_ms, w.axes[0].release_ms) == (-1.0, 150, 50)
    assert (d.axes[0].code, d.axes[0].attack_ms) == (GAMEPAD_AXES["ABS_X"][0], 10)


def test_modifiers_on_triggers():
    config = compile_maps(
        """
map KEY_A modifiers(right_shift) { tap KEY_B }
map KEY_A modifiers(ctrl, shift) as two { tap KEY_C }
map KEY_A modifiers(ignore) { tap KEY_D }
map KEY_A { tap KEY_E }
map KEY_B modifiers(ctrl) { keep modifiers; tap KEY_F }
"""
    )
    one, two, ignore, plain, keep = config.mappings[:-1]  # without the anchor
    assert one.id == "KEY_A+right_shift"
    assert one.trigger.modifiers == {ModifierRequirement(Modifier.SHIFT, Side.RIGHT)}
    assert two.id == "two"
    assert ignore.id == "KEY_A+ignore" and ignore.trigger.any_modifiers
    assert plain.trigger.modifiers == frozenset() and not plain.trigger.any_modifiers
    assert keep.keep_modifiers


def test_device_inference_and_aliases():
    m = macro_of("map KEY_X { tap ctrl + KEY_C; tap BTN_EAST; tap keyboard.KEY_Q }")
    assert m.steps == (
        Tap((K("KEY_LEFTCTRL"), K("KEY_C"))),
        Tap((K("BTN_EAST", "gamepad"),)),
        Tap((K("KEY_Q"),)),
    )


def test_options_and_release_block():
    m = macro_of(
        """map KEY_X {
    cancel on release
    restart on press
    key_pause 5ms
    max_run none
    tap KEY_A (pause 30ms)
    on release { tap KEY_B }
}"""
    )
    assert (m.on_release, m.on_retrigger) == (OnRelease.CANCEL, OnRetrigger.RESTART)
    assert (m.key_pause_ms, m.max_run_ms) == (5, None)
    assert m.steps == (Tap((K("KEY_A"),), 30.0),)
    assert m.release_steps == (Tap((K("KEY_B"),)),)


def test_only_release_block():
    m = macro_of("map KEY_X { on release { tap KEY_B } }")
    assert m.steps == (Wait(0.0),)
    assert m.release_steps == (Tap((K("KEY_B"),)),)


def test_non_blocking_hold_becomes_parallel():
    m = macro_of("map KEY_X { hold KEY_LEFTSHIFT; tap KEY_A; wait 10ms }")
    assert m.steps == (
        Parallel(((HoldKeys((K("KEY_LEFTSHIFT"),)),), (Tap((K("KEY_A"),)), Wait(10.0)))),
    )
    last = macro_of("map KEY_X { tap KEY_A; hold KEY_B }")
    assert last.steps == (Tap((K("KEY_A"),)), HoldKeys((K("KEY_B"),)))
    axis = macro_of("map KEY_X { axis ABS_X 1.0; tap KEY_A }")
    held = axis.steps[0].branches[0][0]
    assert held == HoldAxis("gamepad", GAMEPAD_AXES["ABS_X"][0], 1.0, 0.0, 0.0)


def test_flow_statements():
    m = macro_of(
        """map KEY_X {
    wait random(40ms, 60ms)
    wait 1.5s
    repeat 3 { tap KEY_A }
    move ABS_X to 0.5 over 1s
    parallel { branch { wait 1ms }; branch { wait 2ms } }
}"""
    )
    assert m.steps[0] == Wait(RandomRange(40.0, 60.0))
    assert m.steps[1] == Wait(1500.0)
    assert isinstance(m.steps[2], Repeat) and m.steps[2].count == 3
    assert m.steps[3] == MoveAxis("gamepad", GAMEPAD_AXES["ABS_X"][0], 0.5, 1000.0)
    assert isinstance(m.steps[4], Parallel) and len(m.steps[4].branches) == 2
    assert isinstance(macro_of("map KEY_X { toggle { tap KEY_A } }").steps[0], Toggle)


def test_variables():
    header = HEADER + "let n = 0\nlet d = 10ms\nlet f = 0.5\nlet on_ = true\n"
    m = macro_of(
        """map KEY_X {
    n += 2
    n -= 1
    d += 5ms
    f = 2
    on_ = false
    wait d
    repeat n { tap KEY_A }
}""",
        header,
    )
    assert m.steps[:5] == (
        AddVar("n", 2),
        AddVar("n", -1),
        AddVar("d", 5.0),
        SetVar("f", 2.0),
        SetVar("on_", False),
    )
    assert m.steps[5] == Wait(VarRef("d"))
    assert m.steps[6].count == VarRef("n")


def test_conditions():
    header = HEADER + "let mode = 0\nlet flag = false\n"
    m = macro_of(
        """map KEY_X {
    if tap within 200ms { tap KEY_1 }
    else if single { tap KEY_2 }
    else if not capslock { tap KEY_3 }
    else if mode != 2 { tap KEY_4 }
    else if flag { tap KEY_5 }
    else { tap KEY_6 }
}""",
        header,
    )
    tap = m.steps[0]
    assert isinstance(tap, IfTap) and tap.timeout_ms == 200 and tap.then == (Tap((K("KEY_1"),)),)
    single = tap.otherwise[0]
    assert isinstance(single, IfSingle) and single.then == (Tap((K("KEY_2"),)),)
    led = single.otherwise[0]
    # `not capslock`: the statement block runs when the LED is off
    assert isinstance(led, IfLed) and led.led is Led.CAPSLOCK
    assert led.otherwise == (Tap((K("KEY_3"),)),)
    ne = led.then[0]
    assert ne == IfEq("mode", 2, ne.then, (Tap((K("KEY_4"),)),))
    flag = ne.then[0]
    assert isinstance(flag, IfEq) and (flag.var, flag.value) == ("flag", True)
    assert flag.otherwise == (Tap((K("KEY_6"),)),)


def test_gestures():
    m = macro_of(
        """map KEY_X {
    on tap { tap KEY_1 }
    on double_tap within 250ms { tap KEY_2 }
    on long_press after 250ms { tap KEY_3 }
}"""
    )
    outer = m.steps[0]
    assert isinstance(outer, IfTap) and outer.timeout_ms == 250
    assert outer.otherwise == (Tap((K("KEY_3"),)),)
    inner = outer.then[0]
    assert inner.then == (Tap((K("KEY_2"),)),) and inner.otherwise == (Tap((K("KEY_1"),)),)
    only_tap = macro_of("map KEY_X { on tap { tap KEY_1 } }").steps[0]
    assert only_tap == IfTap((Tap((K("KEY_1"),)),), (), 300.0)


def test_warning_for_btn_x():
    result = compile_text(HEADER + "map KEY_X { tap BTN_X }" + ANCHOR, "t.inpmap")
    assert len(result.warnings) == 1
    assert result.warnings[0].startswith("t.inpmap:5:17: warning: BTN_X is the top button")


# -- errors with positions -------------------------------------------------------------------


@pytest.mark.parametrize(
    "body, line, column, message",
    [
        ("map KEY_X { tap KEY_QQ }", 5, 17, "unknown key code 'KEY_QQ' (did you mean 'KEY_Q'?)"),
        ("map KEY_X {\n  tap BTN_LEFT\n}", 6, 7, "is not a gamepad/joystick button"),
        ("map KEY_X { tap mouse.KEY_A }", 5, 17, "unknown output device 'mouse'"),
        ("map KEY_X { wait d }", 5, 18, "unknown variable 'd'"),
        ("map KEY_X {\n tap KEY_A\n cancel on release\n}", 7, 2, "options must come before"),
        ("map KEY_X { toggle { tap KEY_A }; tap KEY_B }", 5, 13, "'toggle' must be the only"),
        ("map KEY_X { repeat 2 { toggle { tap KEY_A } } }", 5, 24, "'toggle' must be the only"),
        ("map KEY_X { }", 5, 11, "this mapping does nothing"),
        ("map KEY_X { on tap { tap KEY_A }; on tap { tap KEY_B } }", 5, 35, "appears twice"),
        ("map KEY_X { on long_press within 1s { tap KEY_A } }", 5, 27, "use 'after'"),
        ("map KEY_X { frob 5ms }", 5, 13, "unknown option 'frob'"),
        ("map KEY_X { repeat 2.5 { tap KEY_A } }", 5, 20, "whole number"),
        ("map KEY_LEFTCTRL { tap KEY_A }", 5, 5, "is a modifier key and cannot be a trigger"),
        ("map ctrl { tap KEY_A }", 5, 5, "is a modifier and cannot be a trigger"),
        ("map KEY_X modifiers(ctrl, left_ctrl) { tap KEY_A }", 5, 11, "listed twice"),
        ("map KEY_X modifiers(ignore, ctrl) { tap KEY_A }", 5, 11, "cannot be combined"),
        ("map KEY_X { tap KEY_A }\nmap KEY_X { tap KEY_B }", 6, 5, "already mapped at line 5"),
        ("map KEY_X { keep modifiers; tap KEY_A }", 5, 1, "only possible when the input requires"),
        ("map KEY_X { axis ABS_Y { attack = 10ms } }", 5, 13, "axis needs 'target"),
        ("map KEY_X { axis ABS_Z { target = -1 } }", 5, 13, "from 0 to 1 for a trigger"),
        ("let map_ = 1\nlet x = map_", 6, 9, "must be a number, duration"),
    ],
)
def test_errors_have_positions(body, line, column, message):
    found = problems(HEADER + body)
    assert any(p.startswith(f"t.inpmap:{line}:{column}: ") and message in p for p in found), found


def test_missing_version_and_reserved_names():
    found = problems(
        'input kbd { name = "K" }\noutput ctrl { type = keyboard }\nmap KEY_X { tap KEY_A }'
    )
    text = "\n".join(found)
    assert "t.inpmap:1:1: the file must start with 'version 1'" in text
    assert "'ctrl' is a reserved word" in text


def test_ambiguous_devices():
    header = HEADER.replace("output gamepad", "output kb2 { type = keyboard }\noutput gamepad")
    found = problems(header + "map KEY_X { tap KEY_A }")
    assert any("KEY_A could go to kb2 or keyboard" in p for p in found)
    two_inputs = HEADER + 'input pad { name = "P" }\n'
    found = problems(two_inputs + "map KEY_X { tap KEY_A }")
    assert any("several input devices are declared" in p for p in found)


def test_syntax_error_is_a_config_error():
    found = problems(HEADER + "map KEY_X { tap }")
    assert found == ["t.inpmap:5:17: unexpected '}'; expected a name"]

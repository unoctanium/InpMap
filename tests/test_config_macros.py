import copy

import pytest

from inpmap.codes import code_from_name as c
from inpmap.config import ConfigError, parse_config
from inpmap.macros import (
    GAMEPAD_AXES,
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
    WhileHeld,
)

BASE = {
    "version": 1,
    "inputs": {"kbd": {"name": "Kbd"}},
    "outputs": {"keyboard": {"type": "keyboard"}, "gamepad": {"type": "gamepad"}},
    "mappings": [
        {
            "id": "base",
            "input": {"device": "kbd", "type": "key", "code": "KEY_Z"},
            "outputs": [
                {"device": "keyboard", "type": "key", "code": "KEY_Y"},
                {"device": "gamepad", "type": "button", "code": "BTN_FACE_DOWN"},
            ],
        }
    ],
}


def config_with(*outputs, **top):
    data = copy.deepcopy(BASE)
    data.update(top)
    data["mappings"].append(
        {
            "id": "m",
            "input": {"device": "kbd", "type": "key", "code": "KEY_X"},
            "outputs": list(outputs),
        }
    )
    return data


def macro(steps, **fields):
    return {"macro": {"device": "keyboard", "steps": steps, **fields}}


def parse_macro(steps, **fields):
    config = parse_config(config_with(macro(steps, **fields)))
    return config.mappings[1].macros[0]


def problems(data):
    with pytest.raises(ConfigError) as info:
        parse_config(data)
    return "\n".join(info.value.problems)


def macro_problems(steps, **fields):
    return problems(config_with(macro(steps, **fields)))


# -- settings and variables ------------------------------------------------


def test_settings_default_and_custom():
    assert parse_config(config_with(macro([{"tap": "KEY_A"}]))).settings.key_pause_ms == 10
    config = parse_config(config_with(macro([{"tap": "KEY_A"}]), settings={"key_pause_ms": 25}))
    assert config.settings.key_pause_ms == 25
    assert config.mappings[1].macros[0].key_pause_ms == 25  # inherited


@pytest.mark.parametrize("bad", [-1, "10", True, None])
def test_invalid_key_pause(bad):
    data = config_with(macro([{"tap": "KEY_A"}]), settings={"key_pause_ms": bad})
    assert "settings.key_pause_ms" in problems(data)


def test_unknown_setting():
    data = config_with(macro([{"tap": "KEY_A"}]), settings={"key_pause": 5})
    assert "unknown key 'key_pause'" in problems(data)


def test_variables_types():
    data = config_with(
        macro([{"tap": "KEY_A"}]),
        variables={"n": 0, "f": 1.5, "s": "game", "b": False},
    )
    assert parse_config(data).variables == {"n": 0, "f": 1.5, "s": "game", "b": False}


@pytest.mark.parametrize(
    "variables, message",
    [
        ({"1x": 0}, "invalid variable name"),
        ({"x": None}, "initial value must be"),
        ({"x": [1]}, "initial value must be"),
    ],
)
def test_invalid_variables(variables, message):
    data = config_with(macro([{"tap": "KEY_A"}]), variables=variables)
    assert message in problems(data)


# -- axis outputs ------------------------------------------------------------


def test_axis_output():
    axis = {"device": "gamepad", "type": "axis", "code": "ABS_Y", "value": -1.0}
    rule = parse_config(config_with(axis)).mappings[1]
    assert rule.axes[0].code == GAMEPAD_AXES["ABS_Y"][0]
    assert rule.axes[0].value == -1.0
    assert (rule.axes[0].attack_ms, rule.axes[0].release_ms) == (0, 0)


@pytest.mark.parametrize(
    "axis, message",
    [
        ({"device": "keyboard", "code": "ABS_X", "value": 1}, "axes need a gamepad device"),
        ({"device": "gamepad", "code": "ABS_HAT0X", "value": 1}, "unknown axis 'ABS_HAT0X'"),
        ({"device": "gamepad", "code": "ABS_X", "value": 1.5}, "from -1 to 1 for a stick"),
        ({"device": "gamepad", "code": "ABS_Z", "value": -0.5}, "from 0 to 1 for a trigger"),
        ({"device": "gamepad", "code": "ABS_X", "value": 1, "attack_ms": -1}, "attack_ms"),
        ({"device": "gamepad", "code": "ABS_X", "value": 1, "mode": "tap"}, "unknown key 'mode'"),
    ],
)
def test_invalid_axis_output(axis, message):
    assert message in problems(config_with({"type": "axis", **axis}))


def test_duplicate_axis_output():
    axis = {"device": "gamepad", "type": "axis", "code": "ABS_X", "value": 1}
    assert "duplicate axis gamepad ABS_X" in problems(config_with(axis, dict(axis)))


# -- macro structure -------------------------------------------------------------


def test_macro_defaults():
    m = parse_macro([{"tap": "KEY_A"}])
    assert m.on_release is OnRelease.FINISH
    assert m.on_retrigger is OnRetrigger.IGNORE
    assert m.max_run_ms == 60000
    assert m.steps == (Tap((KeyRef("keyboard", c("KEY_A")),)),)


def test_macro_options():
    m = parse_macro(
        [{"tap": "KEY_A"}],
        on_release="cancel",
        on_retrigger="restart",
        key_pause_ms=5,
        max_run_ms=None,
        release_steps=[{"tap": "KEY_B"}],
    )
    assert (m.on_release, m.on_retrigger) == (OnRelease.CANCEL, OnRetrigger.RESTART)
    assert (m.key_pause_ms, m.max_run_ms) == (5, None)
    assert m.release_steps == (Tap((KeyRef("keyboard", c("KEY_B")),)),)


@pytest.mark.parametrize(
    "fields, message",
    [
        ({"on_release": "stop"}, "on_release: must be one of: finish, cancel"),
        ({"on_retrigger": "queue"}, "on_retrigger: must be one of: ignore, restart"),
        ({"max_run_ms": 0}, "max_run_ms: must be a number of milliseconds > 0, or null"),
        ({"device": "mouse"}, "unknown output device 'mouse'"),
        ({"loop": True}, "unknown key 'loop'"),
    ],
)
def test_invalid_macro_options(fields, message):
    assert message in macro_problems([{"tap": "KEY_A"}], **fields)


def test_missing_and_empty_steps():
    assert "missing required key 'steps'" in problems(config_with({"macro": {}}))
    assert "must contain at least one step" in macro_problems([])


def test_unknown_step_and_several_step_keys():
    assert "unknown step; expected one of" in macro_problems([{"type": "KEY_A"}])
    assert "found: tap, press" in macro_problems([{"tap": "KEY_A", "press": "KEY_B"}])
    assert "unknown key 'pause'" in macro_problems([{"tap": "KEY_A", "pause": 1}])


def test_error_paths_name_mapping_and_step():
    text = macro_problems([{"tap": "KEY_A"}, {"repeat": 2, "steps": [{"tap": "KEY_NOPE"}]}])
    assert "mappings[1] ('m').outputs[0].macro.steps[1].steps[0].tap" in text


# -- keys ---------------------------------------------------------------------------


def test_keys_devices_and_chords():
    m = parse_macro(
        [
            {"tap": ["KEY_LEFTCTRL", "KEY_C"]},
            {"tap": {"code": "BTN_FACE_RIGHT", "device": "gamepad"}},
            {"press": "BTN_FACE_LEFT", "device": "gamepad"},
            {"release": "BTN_FACE_LEFT", "device": "gamepad"},
            {"hold_keys": ["KEY_LEFTSHIFT", {"code": "BTN_TL", "device": "gamepad"}]},
            {"with_keys": "KEY_LEFTALT", "steps": [{"tap": "KEY_TAB"}]},
        ]
    )
    assert m.steps[0].keys == (
        KeyRef("keyboard", c("KEY_LEFTCTRL")),
        KeyRef("keyboard", c("KEY_C")),
    )
    assert m.steps[1].keys == (KeyRef("gamepad", c("BTN_FACE_RIGHT")),)
    assert m.steps[2].keys == (KeyRef("gamepad", c("BTN_FACE_LEFT")),)
    assert isinstance(m.steps[4], HoldKeys) and m.steps[4].keys[1].device == "gamepad"
    assert m.steps[5].steps == (Tap((KeyRef("keyboard", c("KEY_TAB")),)),)


def test_key_needs_a_device():
    data = config_with({"macro": {"steps": [{"tap": "KEY_A"}]}})
    assert "no output device" in problems(data)


def test_key_must_suit_device():
    assert "is not a gamepad/joystick button" in macro_problems(
        [{"tap": "BTN_LEFT", "device": "gamepad"}]
    )
    assert "'BTN_FACE_DOWN' is not a key code" in macro_problems([{"tap": "BTN_FACE_DOWN"}])
    assert "unknown key code 'KEY_NOPE'" in macro_problems([{"tap": "KEY_NOPE"}])


def test_invalid_step_device_is_reported_once():
    text = macro_problems([{"tap": "KEY_A", "device": "mouse"}])
    assert text.count("mouse") == 1
    assert "no output device" not in text


def test_release_of_never_pressed_key():
    assert "releases keyboard KEY_B, which this macro never presses" in macro_problems(
        [{"press": "KEY_A"}, {"release": "KEY_B"}]
    )


def test_pause_override():
    m = parse_macro([{"tap": "KEY_A", "pause_ms": {"min": 5, "max": 15}}])
    assert m.steps[0].pause == RandomRange(5, 15)


# -- axes in macros --------------------------------------------------------------------


def test_axis_steps():
    m = parse_macro(
        [
            {"axis": "ABS_X", "device": "gamepad", "to": 1.0, "over_ms": 1000},
            {"hold_axis": "ABS_RZ", "device": "gamepad", "value": 1, "release_ms": 100},
        ]
    )
    assert m.steps[0] == MoveAxis("gamepad", GAMEPAD_AXES["ABS_X"][0], 1.0, 1000.0)
    assert m.steps[1] == HoldAxis("gamepad", GAMEPAD_AXES["ABS_RZ"][0], 1.0, 0.0, 100.0)


def test_axis_step_errors():
    assert "axes need a gamepad device" in macro_problems([{"axis": "ABS_X", "to": 1}])
    assert "missing required key 'to'" in macro_problems([{"axis": "ABS_X", "device": "gamepad"}])
    assert "from -1 to 1" in macro_problems([{"axis": "ABS_X", "device": "gamepad", "to": -2}])


# -- timing and flow -------------------------------------------------------------------------


def test_flow_steps():
    m = parse_macro(
        [
            {"wait_ms": 100},
            {"wait_ms": {"min": 50, "max": 150}},
            {"repeat": 3, "steps": [{"tap": "KEY_A"}]},
            {"while_held": [{"tap": "KEY_B"}]},
            {"parallel": [[{"tap": "KEY_C"}], [{"wait_ms": 5}]]},
        ]
    )
    assert m.steps[0] == Wait(100.0)
    assert m.steps[1] == Wait(RandomRange(50.0, 150.0))
    assert isinstance(m.steps[2], Repeat) and m.steps[2].count == 3
    assert isinstance(m.steps[3], WhileHeld)
    assert isinstance(m.steps[4], Parallel) and len(m.steps[4].branches) == 2


@pytest.mark.parametrize(
    "step, message",
    [
        ({"wait_ms": -1}, "must not be negative"),
        ({"wait_ms": {"min": 10, "max": 5}}, "'min' must not be greater than 'max'"),
        ({"wait_ms": {"min": 10}}, "missing required key 'max'"),
        ({"wait_ms": "100"}, 'must be milliseconds, {"min"'),
        ({"repeat": 10001, "steps": [{"tap": "KEY_A"}]}, "integer from 0 to 10000"),
        ({"repeat": 2.5, "steps": [{"tap": "KEY_A"}]}, "integer from 0 to 10000"),
        ({"repeat": 2, "steps": []}, "must contain at least one step"),
        ({"parallel": []}, "non-empty array of step arrays"),
        ({"while_held": []}, "must contain at least one step"),
    ],
)
def test_flow_errors(step, message):
    assert message in macro_problems([step])


def test_toggle_only_as_single_step():
    assert isinstance(parse_macro([{"toggle": [{"tap": "KEY_A"}]}]).steps[0], Toggle)
    message = "'toggle' must be the only step"
    assert message in macro_problems([{"toggle": [{"tap": "KEY_A"}]}, {"tap": "KEY_B"}])
    nested = [{"repeat": 2, "steps": [{"toggle": [{"tap": "KEY_A"}]}]}]
    assert message in macro_problems(nested)
    in_release = [{"tap": "KEY_A"}]
    assert message in macro_problems(in_release, release_steps=[{"toggle": [{"tap": "KEY_A"}]}])


# -- conditions and variables ------------------------------------------------------------------


def test_conditions():
    steps = [
        {"if_tap": {"then": [{"tap": "KEY_A"}]}},
        {"if_single": {"else": [{"tap": "KEY_B"}], "timeout_ms": 500}},
        {"if_led": {"led": "capslock", "then": [{"tap": "KEY_C"}]}},
        {"if_eq": {"var": "mode", "value": 1, "then": [{"tap": "KEY_D"}]}},
    ]
    config = parse_config(config_with(macro(steps), variables={"mode": 0}))
    tap, single, led, eq = config.mappings[1].macros[0].steps
    assert isinstance(tap, IfTap) and tap.timeout_ms == 300 and tap.otherwise == ()
    assert isinstance(single, IfSingle) and single.timeout_ms == 500 and single.then == ()
    assert isinstance(led, IfLed) and led.led is Led.CAPSLOCK
    assert isinstance(eq, IfEq) and (eq.var, eq.value) == ("mode", 1)


@pytest.mark.parametrize(
    "step, message",
    [
        ({"if_tap": {"timeout_ms": 0}}, "timeout_ms: must be a number of milliseconds > 0"),
        ({"if_led": {"led": "kana"}}, "led: must be one of: capslock, numlock, scrolllock"),
        ({"if_tap": {"then": [], "otherwise": []}}, "unknown key 'otherwise'"),
        ({"if_eq": {"var": "nope", "value": 1}}, "unknown variable 'nope' (declared: f, n, s)"),
        ({"if_eq": {"var": "n", "value": "1"}}, "variable 'n' is a int, got string"),
        ({"set": {"var": "s", "value": 2}}, "variable 's' is a string, got int"),
        ({"add": {"var": "s", "value": 2}}, "variable 's' is a string, expected"),
        ({"add": {"var": "n", "value": 1.5}}, "variable 'n' is a int, got float"),
        ({"wait_ms": {"var": "s"}}, "variable 's' is a string"),
        ({"repeat": {"var": "f"}, "steps": [{"tap": "KEY_A"}]}, "variable 'f' is a float"),
    ],
)
def test_condition_and_variable_errors(step, message):
    data = config_with(macro([step]), variables={"n": 0, "f": 0.5, "s": "x"})
    assert message in problems(data)


def test_float_variable_accepts_int_values():
    data = config_with(
        macro([{"set": {"var": "f", "value": 2}}, {"wait_ms": {"var": "f"}}]),
        variables={"f": 0.5},
    )
    m = parse_config(data).mappings[1].macros[0]
    assert m.steps[0] == SetVar("f", 2.0)
    assert m.steps[1] == Wait(VarRef("f"))


# -- integration with the rest of the configuration ---------------------------------------------


def test_macro_keys_become_device_capabilities():
    data = copy.deepcopy(BASE)
    data["mappings"][0]["outputs"] = [{"device": "keyboard", "type": "key", "code": "KEY_Y"}]
    data["mappings"].append(
        {
            "id": "m",
            "input": {"device": "kbd", "type": "key", "code": "KEY_X"},
            "outputs": [macro([{"tap": "BTN_START", "device": "gamepad"}])],
        }
    )
    config = parse_config(data)  # gamepad counts as used through the macro
    assert config.output_codes("gamepad") == {c("BTN_START")}


def test_mapping_mixing_outputs_axes_and_macros():
    rule = parse_config(
        config_with(
            {"device": "keyboard", "type": "key", "code": "KEY_A"},
            {"device": "gamepad", "type": "axis", "code": "ABS_X", "value": 1},
            macro([{"tap": "KEY_B"}]),
        )
    ).mappings[1]
    assert (len(rule.outputs), len(rule.axes), len(rule.macros)) == (1, 1, 1)

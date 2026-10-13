import copy
import json
from pathlib import Path

import pytest

from inpmap.codes import code_from_name
from inpmap.config import ConfigError, load_config, parse_config
from inpmap.models import OutputKind

EXAMPLE = Path(__file__).resolve().parent.parent / "config" / "example.json"

VALID = {
    "version": 1,
    "inputs": {"kbd": {"name": "Some Keyboard"}},
    "outputs": {
        "vkbd": {"type": "keyboard", "name": "Test Keyboard"},
        "pad": {"type": "gamepad", "name": "Test Gamepad"},
    },
    "mappings": [
        {
            "id": "x",
            "input": {"device": "kbd", "type": "key", "code": "KEY_X"},
            "outputs": [
                {"device": "vkbd", "type": "key", "code": "KEY_Y"},
                {"device": "pad", "type": "button", "code": "BTN_SOUTH"},
            ],
        }
    ],
}


def valid():
    return copy.deepcopy(VALID)


def problems_of(data):
    with pytest.raises(ConfigError) as info:
        parse_config(data)
    return "\n".join(info.value.problems)


# -- valid configurations ------------------------------------------------


@pytest.mark.parametrize("name", ["example.json", "example-macros.json"])
def test_all_example_configs_are_valid(name):
    load_config(EXAMPLE.parent / name)


def test_example_config_is_valid():
    config = load_config(EXAMPLE)
    assert config.version == 1
    assert [rule.id for rule in config.mappings] == ["keyboard-x-to-y-and-gamepad-a"]


def test_valid_config_is_converted_to_models():
    config = parse_config(valid())
    assert config.inputs["kbd"].name == "Some Keyboard"
    assert config.inputs["kbd"].path is None
    assert config.outputs["vkbd"].kind is OutputKind.KEYBOARD
    assert config.outputs["pad"].kind is OutputKind.GAMEPAD
    (rule,) = config.mappings
    assert rule.trigger.device == "kbd"
    assert rule.trigger.code == code_from_name("KEY_X")
    assert [(a.device, a.code) for a in rule.outputs] == [
        ("vkbd", code_from_name("KEY_Y")),
        ("pad", code_from_name("BTN_SOUTH")),
    ]
    assert rule.consume is True


def test_output_and_input_codes_per_device():
    data = valid()
    data["mappings"].append(
        {
            "id": "z",
            "input": {"device": "kbd", "type": "key", "code": "KEY_Z"},
            "outputs": [{"device": "vkbd", "type": "key", "code": "KEY_Y"}],
        }
    )
    config = parse_config(data)
    assert config.output_codes("vkbd") == {code_from_name("KEY_Y")}
    assert config.output_codes("pad") == {code_from_name("BTN_SOUTH")}
    assert config.input_codes("kbd") == {code_from_name("KEY_X"), code_from_name("KEY_Z")}


def test_input_device_by_path():
    data = valid()
    data["inputs"]["kbd"] = {"path": "/dev/input/by-id/usb-Foo-event-kbd"}
    config = parse_config(data)
    assert config.inputs["kbd"].path == "/dev/input/by-id/usb-Foo-event-kbd"


def test_output_name_defaults_to_device_id():
    data = valid()
    del data["outputs"]["pad"]["name"]
    assert parse_config(data).outputs["pad"].name == "InpMap pad"


def test_code_aliases_resolve_to_same_code():
    data = valid()
    data["mappings"][0]["outputs"][1]["code"] = "BTN_A"
    rule = parse_config(data).mappings[0]
    assert rule.outputs[1].code == code_from_name("BTN_SOUTH")


def test_gamepad_buttons_as_input():
    data = valid()
    data["inputs"]["pad-in"] = {"name": "Physical Pad"}
    data["mappings"].append(
        {
            "id": "pad-east",
            "input": {"device": "pad-in", "type": "button", "code": "BTN_EAST"},
            "outputs": [{"device": "vkbd", "type": "key", "code": "KEY_ESC"}],
        }
    )
    assert len(parse_config(data).mappings) == 2


# -- file-level errors ---------------------------------------------------


def test_missing_file(tmp_path):
    with pytest.raises(ConfigError, match="cannot read file"):
        load_config(tmp_path / "missing.json")


def test_invalid_json_reports_position(tmp_path):
    path = tmp_path / "bad.json"
    path.write_text('{"version": 1,\n  "inputs": }')
    with pytest.raises(ConfigError) as info:
        load_config(path)
    assert str(path) in str(info.value)
    assert "line 2" in str(info.value)


def test_error_message_includes_source_path(tmp_path):
    data = valid()
    data["mappings"][0]["outputs"][0]["device"] = "nope"
    path = tmp_path / "cfg.json"
    path.write_text(json.dumps(data))
    with pytest.raises(ConfigError) as info:
        load_config(path)
    message = str(info.value)
    assert message.startswith(f"{path}: invalid configuration")
    assert "'x'" in message


# -- structural errors ---------------------------------------------------


def test_top_level_must_be_object():
    assert "must be a JSON object" in problems_of([])


@pytest.mark.parametrize("version", [0, 2, "1", True, None, 1.0])
def test_unsupported_version(version):
    data = valid()
    data["version"] = version
    assert "unsupported version" in problems_of(data)


def test_missing_version():
    data = valid()
    del data["version"]
    assert "missing required key 'version'" in problems_of(data)


def test_unknown_top_level_key_with_suggestion():
    data = valid()
    data["mapings"] = []
    assert "unknown key 'mapings' (did you mean 'mappings'?)" in problems_of(data)


def test_unknown_key_in_mapping():
    data = valid()
    data["mappings"][0]["output"] = []
    assert "unknown key 'output'" in problems_of(data)


def test_empty_mappings_rejected():
    data = valid()
    data["mappings"] = []
    assert "at least one mapping" in problems_of(data)


def test_all_problems_reported_together():
    data = valid()
    data["mappings"][0]["input"]["code"] = "KEY_NOPE"
    data["mappings"][0]["outputs"][0]["device"] = "ghost"
    problems = problems_of(data)
    assert "KEY_NOPE" in problems
    assert "ghost" in problems


# -- devices -------------------------------------------------------------


def test_input_device_needs_exactly_one_selector():
    data = valid()
    data["inputs"]["kbd"] = {"name": "A", "path": "/dev/input/event3"}
    assert "exactly one of 'name' or 'path'" in problems_of(data)
    data["inputs"]["kbd"] = {}
    assert "exactly one of 'name' or 'path'" in problems_of(data)


def test_input_path_must_be_absolute():
    data = valid()
    data["inputs"]["kbd"] = {"path": "event3"}
    assert "absolute path" in problems_of(data)


def test_unknown_output_device_type():
    data = valid()
    data["outputs"]["pad"]["type"] = "joystick"
    assert "unknown device type 'joystick'" in problems_of(data)


def test_output_name_too_long():
    data = valid()
    data["outputs"]["pad"]["name"] = "x" * 80
    assert "at most 79 bytes" in problems_of(data)


def test_duplicate_output_names():
    data = valid()
    data["outputs"]["pad"]["name"] = "Test Keyboard"
    assert "already used by 'vkbd'" in problems_of(data)


def test_device_id_used_for_input_and_output():
    data = valid()
    data["outputs"]["kbd"] = {"type": "keyboard", "name": "Other"}
    assert "used for both an input and an output" in problems_of(data)


def test_invalid_device_id():
    data = valid()
    data["outputs"]["bad id!"] = data["outputs"].pop("pad")
    assert "invalid id 'bad id!'" in problems_of(data)


def test_unused_output_device_rejected():
    data = valid()
    data["outputs"]["spare"] = {"type": "keyboard", "name": "Spare"}
    assert "outputs.spare: not used by any mapping" in problems_of(data)


def test_unused_input_device_rejected():
    data = valid()
    data["inputs"]["mouse"] = {"name": "Some Mouse"}
    assert "inputs.mouse: not used by any mapping" in problems_of(data)


# -- device references ---------------------------------------------------


def test_unknown_input_device_reference():
    data = valid()
    data["mappings"][0]["input"]["device"] = "physical-keyboard"
    problems = problems_of(data)
    assert "unknown input device 'physical-keyboard'" in problems
    assert "defined inputs: kbd" in problems


def test_output_device_used_as_input():
    data = valid()
    data["mappings"][0]["input"]["device"] = "vkbd"
    assert "unknown input device 'vkbd'" in problems_of(data)


def test_unknown_output_device_reference():
    data = valid()
    data["mappings"][0]["outputs"][1]["device"] = "gamepad"
    assert "unknown output device 'gamepad'" in problems_of(data)


# -- event types and codes -----------------------------------------------


def test_unsupported_event_type():
    data = valid()
    data["mappings"][0]["input"]["type"] = "axis"
    assert "unsupported event type 'axis'" in problems_of(data)


def test_unknown_code_with_suggestion():
    data = valid()
    data["mappings"][0]["input"]["code"] = "key_x"
    assert "unknown key code 'key_x' (did you mean 'KEY_X'?)" in problems_of(data)


def test_code_must_be_string():
    data = valid()
    data["mappings"][0]["input"]["code"] = 45
    assert "must be a code name string" in problems_of(data)


def test_code_prefix_must_match_type():
    data = valid()
    data["mappings"][0]["input"]["code"] = "BTN_SOUTH"
    assert "'BTN_SOUTH' is not a key code" in problems_of(data)


def test_keyboard_output_rejects_button_type():
    data = valid()
    data["mappings"][0]["outputs"][0] = {"device": "vkbd", "type": "button", "code": "BTN_SOUTH"}
    assert "accepts type 'key', not 'button'" in problems_of(data)


def test_gamepad_output_rejects_key_type():
    data = valid()
    data["mappings"][0]["outputs"][1] = {"device": "pad", "type": "key", "code": "KEY_A"}
    assert "accepts type 'button', not 'key'" in problems_of(data)


def test_gamepad_output_rejects_non_gamepad_button():
    data = valid()
    data["mappings"][0]["outputs"][1]["code"] = "BTN_LEFT"
    assert "BTN_LEFT is not a gamepad/joystick button" in problems_of(data)


# -- mapping rules -------------------------------------------------------


def test_missing_mapping_id():
    data = valid()
    del data["mappings"][0]["id"]
    assert "missing required key 'id'" in problems_of(data)


def test_duplicate_mapping_id():
    data = valid()
    second = copy.deepcopy(data["mappings"][0])
    second["input"]["code"] = "KEY_Z"
    data["mappings"].append(second)
    assert "duplicate mapping id 'x'" in problems_of(data)


def test_same_input_in_two_mappings_rejected():
    data = valid()
    second = copy.deepcopy(data["mappings"][0])
    second["id"] = "x2"
    data["mappings"].append(second)
    assert "already mapped by 'x'" in problems_of(data)


def test_same_input_via_alias_rejected():
    data = valid()
    data["inputs"]["pad-in"] = {"name": "Physical Pad"}
    for rule_id, code in (("a", "BTN_SOUTH"), ("b", "BTN_A")):
        data["mappings"].append(
            {
                "id": rule_id,
                "input": {"device": "pad-in", "type": "button", "code": code},
                "outputs": [{"device": "vkbd", "type": "key", "code": "KEY_ENTER"}],
            }
        )
    assert "already mapped by 'a'" in problems_of(data)


def test_empty_outputs_rejected():
    data = valid()
    data["mappings"][0]["outputs"] = []
    assert "non-empty JSON array" in problems_of(data)


def test_duplicate_output_in_mapping():
    data = valid()
    data["mappings"][0]["outputs"].append({"device": "vkbd", "type": "key", "code": "KEY_Y"})
    assert "duplicate output vkbd KEY_Y" in problems_of(data)


def test_consume_must_be_boolean():
    data = valid()
    data["mappings"][0]["consume"] = "yes"
    assert "must be true or false" in problems_of(data)


def test_consume_false_not_supported_yet():
    data = valid()
    data["mappings"][0]["consume"] = False
    assert "'false' is not supported yet" in problems_of(data)


def test_output_mode_defaults_to_hold_and_accepts_tap():
    from inpmap.models import OutputMode

    data = valid()
    data["mappings"][0]["outputs"][1]["mode"] = "tap"
    first, second = parse_config(data).mappings[0].outputs
    assert first.mode is OutputMode.HOLD
    assert second.mode is OutputMode.TAP


def test_unknown_output_mode():
    data = valid()
    data["mappings"][0]["outputs"][0]["mode"] = "toggle"
    assert "unknown mode 'toggle' (expected one of: hold, tap)" in problems_of(data)


def test_mode_not_allowed_on_input():
    data = valid()
    data["mappings"][0]["input"]["mode"] = "tap"
    assert "input: unknown key 'mode'" in problems_of(data)


def test_same_output_twice_with_different_modes_rejected():
    data = valid()
    data["mappings"][0]["outputs"].append(
        {"device": "vkbd", "type": "key", "code": "KEY_Y", "mode": "tap"}
    )
    assert "duplicate output vkbd KEY_Y" in problems_of(data)


def test_description_must_be_string():
    data = valid()
    data["mappings"][0]["description"] = 5
    assert "description: must be a string" in problems_of(data)

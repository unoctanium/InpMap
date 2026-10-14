"""Axes as triggers (docs/configuration.md §5.5): values, thresholds, configuration."""

import pytest

from inpmap.axis_triggers import (
    VIRTUAL_CODE_BASE,
    AxisEvent,
    AxisRow,
    AxisTriggers,
    normalize,
    problem,
)
from inpmap.codes import TRIGGER_AXES
from inpmap.config import ConfigError
from inpmap.dsl.compiler import compile_text
from inpmap.models import AxisThreshold, InputEvent, KeyAction

ABS_RZ, ABS_HAT0Y, ABS_X = TRIGGER_AXES["ABS_RZ"], TRIGGER_AXES["ABS_HAT0Y"], TRIGGER_AXES["ABS_X"]
PRESS, RELEASE = KeyAction.PRESS, KeyAction.RELEASE

HEADER = """version 1
input pad { name = "Pad" }
output keyboard { type = keyboard }
"""


def test_axis_codes_match_the_kernel():
    ecodes = pytest.importorskip("evdev").ecodes
    for name, code in TRIGGER_AXES.items():
        assert getattr(ecodes, name) == code, name


@pytest.mark.parametrize(
    "raw, minimum, maximum, expected",
    [
        (0, -32768, 32767, 0.0),
        (32767, -32768, 32767, 1.0),
        (-32768, -32768, 32767, -1.0),
        (-16384, -32768, 32767, -0.5),
        (0, 0, 255, 0.0),
        (255, 0, 255, 1.0),
        (-1, -1, 1, -1.0),  # D-pad hat
        (5, 5, 5, 0.0),  # degenerate range
    ],
)
def test_normalize(raw, minimum, maximum, expected):
    assert normalize(raw, minimum, maximum) == pytest.approx(expected, abs=1e-4)


def test_problem_only_for_unreachable_thresholds():
    assert problem(AxisThreshold(ABS_RZ, True, 0.5), 0, 255) is None
    assert "can never fire" in problem(AxisThreshold(ABS_RZ, False, 0.5), 0, 255)
    assert "can never fire" in problem(AxisThreshold(ABS_RZ, True, -0.5), 0, 255)
    assert problem(AxisThreshold(ABS_HAT0Y, False, -0.5), -1, 1) is None


def triggers(*thresholds):
    return AxisTriggers({VIRTUAL_CODE_BASE + i: t for i, t in enumerate(thresholds)})


def test_press_and_release_with_hysteresis():
    above = triggers(AxisThreshold(ABS_RZ, True, 0.5))
    code = VIRTUAL_CODE_BASE

    def at(value):
        return above.update(AxisEvent("pad", ABS_RZ, value))

    assert at(0.5) == []  # must rise above the value
    assert at(0.51) == [InputEvent("pad", code, PRESS)]
    assert at(0.47) == []  # within the 0.05 hysteresis
    assert at(0.6) == []  # still pressed
    assert at(0.44) == [InputEvent("pad", code, RELEASE)]
    assert at(0.48) == []  # not pressed again below the value


def test_below_and_devices_are_independent():
    up = triggers(AxisThreshold(ABS_HAT0Y, False, -0.5))
    code = VIRTUAL_CODE_BASE
    assert up.update(AxisEvent("pad", ABS_HAT0Y, -1.0)) == [InputEvent("pad", code, PRESS)]
    assert up.update(AxisEvent("pad2", ABS_HAT0Y, -1.0)) == [InputEvent("pad2", code, PRESS)]
    assert up.update(AxisEvent("pad", ABS_HAT0Y, 0.0)) == [InputEvent("pad", code, RELEASE)]
    assert up.update(AxisEvent("pad", ABS_X, -1.0)) == []  # other axis


def test_two_stage_trigger():
    stages = triggers(AxisThreshold(ABS_RZ, True, 0.3), AxisThreshold(ABS_RZ, True, 0.9))
    first, second = VIRTUAL_CODE_BASE, VIRTUAL_CODE_BASE + 1
    assert stages.update(AxisEvent("pad", ABS_RZ, 1.0)) == [
        InputEvent("pad", first, PRESS),
        InputEvent("pad", second, PRESS),
    ]
    assert stages.update(AxisEvent("pad", ABS_RZ, 0.5)) == [InputEvent("pad", second, RELEASE)]


def test_forget_device_drops_state():
    above = triggers(AxisThreshold(ABS_RZ, True, 0.5))
    above.update(AxisEvent("pad", ABS_RZ, 1.0))
    above.forget_device("pad")
    assert above.update(AxisEvent("pad", ABS_RZ, 1.0)) == [
        InputEvent("pad", VIRTUAL_CODE_BASE, PRESS)
    ]


def test_axis_row_text():
    row = AxisRow("pad", ABS_RZ, 0, 255, 0.73, [("r2", AxisThreshold(ABS_RZ, True, 0.5))])
    assert row.text() == "pad        ABS_RZ       +0.73   (0..255)   r2: above 0.5 ON"


# -- configuration ---------------------------------------------------------------------------


def test_compile_axis_triggers():
    config = compile_text(
        HEADER
        + "map pad.ABS_RZ above 0.5 { tap KEY_A }\n"
        + "map ABS_RZ above 0.5 { tap KEY_B }\n"
        + "map pad.ABS_HAT0Y below -0.5 modifiers(ctrl) as up { tap KEY_C }\n"
        + "map pad.ABS_RZ above 0.9 { tap KEY_D }\n",
        "t.inpmap",
    ).config
    named, every, up, stage2 = config.mappings
    assert named.id == "pad.ABS_RZ_above_0.5" and named.trigger.device == "pad"
    assert every.id == "ABS_RZ_above_0.5" and every.trigger.device is None
    assert named.trigger.code == every.trigger.code == VIRTUAL_CODE_BASE  # same threshold
    assert up.trigger.axis == AxisThreshold(ABS_HAT0Y, False, -0.5)
    assert up.trigger.modifiers and up.trigger.code == VIRTUAL_CODE_BASE + 1
    assert stage2.trigger.code == VIRTUAL_CODE_BASE + 2
    assert config.input_codes("pad") == frozenset()  # thresholds are not key codes
    assert config.input_axes("pad") == {named.trigger.axis, up.trigger.axis, stage2.trigger.axis}
    assert config.shared_axes() == {every.trigger.axis}
    assert config.watched_axes("pad") == {ABS_RZ, ABS_HAT0Y}


@pytest.mark.parametrize(
    "line, message",
    [
        ("map pad.ABS_RZ { tap KEY_A }", "an axis needs 'above' or 'below'"),
        ("map pad.KEY_A above 0.5 { tap KEY_A }", "'above' and 'below' are only for axes"),
        ("map pad.ABS_RZ above 0 { tap KEY_A }", "between -1.0 and 1.0, other than 0"),
        ("map pad.ABS_RZ above 1.5 { tap KEY_A }", "between -1.0 and 1.0, other than 0"),
        ("map pad.ABS_MISC above 0.5 { tap KEY_A }", "'ABS_MISC' cannot be a trigger"),
    ],
)
def test_axis_trigger_errors(line, message):
    with pytest.raises(ConfigError) as info:
        compile_text(HEADER + line + "\n", "t.inpmap")
    assert any(message in p and p.startswith("t.inpmap:4:") for p in info.value.problems), (
        info.value.problems
    )


def test_same_threshold_twice_is_an_error():
    with pytest.raises(ConfigError) as info:
        compile_text(
            HEADER + "map pad.ABS_RZ above 0.5 { tap KEY_A }\n"
            "map pad.ABS_RZ above 0.5 { tap KEY_B }\n",
            "t.inpmap",
        )
    assert any("already mapped at line 4" in p for p in info.value.problems)

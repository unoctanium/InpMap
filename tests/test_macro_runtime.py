"""Macro execution through the engine, on a fake clock (docs/macros.md)."""

import logging
import random

import pytest

from inpmap.codes import code_from_name as c
from inpmap.config import parse_config
from inpmap.engine import MappingEngine
from inpmap.macros import GAMEPAD_AXES, Led
from inpmap.models import InputEvent, KeyAction
from inpmap.output import OutputError

ABS_X = GAMEPAD_AXES["ABS_X"][0]
ABS_Y = GAMEPAD_AXES["ABS_Y"][0]


class Clock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


class Sink:
    """Records output events with their time in ms."""

    def __init__(self, clock):
        self.clock = clock
        self.log = []
        self.fail = False

    def _record(self, *entry):
        if self.fail:
            raise OutputError("simulated failure")
        self.log.append((round(self.clock.now * 1000, 3), *entry))

    def press(self, device, code):
        self._record(device, code, "down")

    def release(self, device, code):
        self._record(device, code, "up")

    def set_axis(self, device, code, value):
        self._record(device, code, round(value, 4))


class Rig:
    def __init__(self, mappings, variables=None, leds=None, settings=None):
        data = {
            "version": 1,
            "inputs": {"kbd": {"name": "Kbd"}, "pad": {"name": "Pad"}},
            "outputs": {"kb": {"type": "keyboard"}, "gp": {"type": "gamepad"}},
            "mappings": mappings
            + [
                {  # keeps both output devices and the pad input in use
                    "id": "anchor",
                    "input": {"device": "pad", "type": "button", "code": "BTN_MODE"},
                    "outputs": [
                        {"device": "kb", "type": "key", "code": "KEY_F24"},
                        {"device": "gp", "type": "button", "code": "BTN_MODE"},
                    ],
                }
            ],
        }
        if variables:
            data["variables"] = variables
        if settings:
            data["settings"] = settings
        self.config = parse_config(data)
        self.clock = Clock()
        self.sink = Sink(self.clock)
        self.led_state = leds or {}
        self.engine = MappingEngine(
            self.config,
            self.sink,
            clock=self.clock,
            leds=lambda device: frozenset(self.led_state.get(device, ())),
            rng=random.Random(1),
        )

    def press(self, code="KEY_X", device="kbd"):
        return self.engine.handle(InputEvent(device, c(code), KeyAction.PRESS))

    def release(self, code="KEY_X", device="kbd"):
        return self.engine.handle(InputEvent(device, c(code), KeyAction.RELEASE))

    def at(self, ms):
        """Advance the clock to ``ms``, running every timer on the way."""
        target = ms / 1000
        while True:
            due = self.engine.next_deadline()
            if due is None or due > target:
                break
            self.clock.now = max(self.clock.now, due)
            self.engine.tick()
        self.clock.now = target
        self.engine.tick()

    def keys(self):
        """(ms, code name, down/up) for key events."""
        return [
            (t, codes_name(code), what)
            for t, _dev, code, what in self.sink.log
            if isinstance(what, str)
        ]

    def axis(self, code=ABS_X):
        return [(t, v) for t, _dev, k, v in self.sink.log if not isinstance(v, str) and k == code]


def codes_name(code):
    from inpmap.codes import code_name

    return code_name(code)


def mapping(steps=None, code="KEY_X", device="kbd", outputs=None, **macro_fields):
    if outputs is None:
        outputs = [{"macro": {"device": "kb", "steps": steps, **macro_fields}}]
    kind = "key" if code.startswith("KEY_") else "button"
    return {
        "id": f"m-{code}",
        "input": {"device": device, "type": kind, "code": code},
        "outputs": outputs,
    }


# -- keys --------------------------------------------------------------------------


def test_tap_with_default_key_pause():
    rig = Rig([mapping([{"tap": "KEY_A"}, {"tap": "KEY_B"}])])
    assert rig.press() is True  # trigger is consumed
    rig.at(100)
    assert rig.keys() == [
        (0, "KEY_A", "down"),
        (10, "KEY_A", "up"),
        (20, "KEY_B", "down"),
        (30, "KEY_B", "up"),
    ]
    assert rig.engine.running_macros() == []


def test_global_and_step_pause():
    rig = Rig(
        [mapping([{"tap": "KEY_A"}, {"tap": "KEY_B", "pause_ms": 0}])],
        settings={"key_pause_ms": 5},
    )
    rig.press()
    rig.at(100)
    assert rig.keys() == [
        (0, "KEY_A", "down"),
        (5, "KEY_A", "up"),
        (10, "KEY_B", "down"),
        (10, "KEY_B", "up"),
    ]


def test_chord_tap_releases_in_reverse_order():
    rig = Rig([mapping([{"tap": ["KEY_LEFTCTRL", "KEY_C"]}])])
    rig.press()
    rig.at(100)
    assert rig.keys() == [
        (0, "KEY_LEFTCTRL", "down"),
        (10, "KEY_C", "down"),
        (20, "KEY_C", "up"),
        (30, "KEY_LEFTCTRL", "up"),
    ]


def test_multi_device_steps():
    rig = Rig(
        [mapping([{"tap": "KEY_Q"}, {"tap": {"code": "BTN_EAST", "device": "gp"}, "pause_ms": 0}])]
    )
    rig.press()
    rig.at(100)
    devices = [(dev, codes_name(code), what) for _t, dev, code, what in rig.sink.log]
    assert devices == [
        ("kb", "KEY_Q", "down"),
        ("kb", "KEY_Q", "up"),
        ("gp", "BTN_EAST", "down"),
        ("gp", "BTN_EAST", "up"),
    ]


def test_press_without_release_is_released_at_run_end():
    rig = Rig([mapping([{"press": "KEY_A", "pause_ms": 0}, {"wait_ms": 50}])])
    rig.press()
    rig.at(200)
    assert rig.keys() == [(0, "KEY_A", "down"), (50, "KEY_A", "up")]


def test_hold_keys_until_trigger_release():
    rig = Rig([mapping([{"hold_keys": "KEY_LEFTSHIFT"}], key_pause_ms=0)])
    rig.press()
    rig.at(300)
    assert rig.keys() == [(0, "KEY_LEFTSHIFT", "down")]
    rig.release()
    rig.at(400)
    assert rig.keys()[-1] == (300, "KEY_LEFTSHIFT", "up")


def test_hold_keys_after_release_presses_and_releases_at_once():
    rig = Rig([mapping([{"wait_ms": 50}, {"hold_keys": "KEY_A"}], key_pause_ms=0)])
    rig.press()
    rig.at(10)
    rig.release()
    rig.at(100)
    assert rig.keys() == [(50, "KEY_A", "down"), (50, "KEY_A", "up")]


def test_with_keys_wraps_steps():
    rig = Rig([mapping([{"with_keys": "KEY_LEFTSHIFT", "steps": [{"tap": "KEY_A"}]}])])
    rig.press()
    rig.at(100)
    assert [k[1:] for k in rig.keys()] == [
        ("KEY_LEFTSHIFT", "down"),
        ("KEY_A", "down"),
        ("KEY_A", "up"),
        ("KEY_LEFTSHIFT", "up"),
    ]


def test_macro_key_shared_with_plain_hold_output_is_not_released_early():
    rig = Rig(
        [
            mapping([{"tap": "KEY_Y"}], code="KEY_X"),
            mapping(code="KEY_C", outputs=[{"device": "kb", "type": "key", "code": "KEY_Y"}]),
        ]
    )
    rig.press("KEY_C")  # holds KEY_Y
    rig.press("KEY_X")  # macro taps KEY_Y: already down, so no events
    rig.at(100)
    assert rig.keys() == [(0, "KEY_Y", "down")]
    rig.release("KEY_C")
    assert rig.keys()[-1] == (100, "KEY_Y", "up")


# -- timing and run policies ----------------------------------------------------------


def test_wait_and_random_wait_are_deterministic_with_seed():
    rig = Rig([mapping([{"wait_ms": 100}, {"wait_ms": {"min": 50, "max": 60}}, {"tap": "KEY_A"}])])
    rig.press()
    rig.at(500)
    first = rig.keys()[0][0]
    assert 150 <= first <= 160


def test_on_release_finish_runs_to_end():
    rig = Rig([mapping([{"tap": "KEY_A"}, {"wait_ms": 100}, {"tap": "KEY_B"}])])
    rig.press()
    rig.at(5)
    rig.release()
    rig.at(500)
    assert [k[1] for k in rig.keys() if k[2] == "down"] == ["KEY_A", "KEY_B"]


def test_on_release_cancel_stops_and_releases_owned_keys():
    rig = Rig(
        [mapping([{"press": "KEY_A"}, {"wait_ms": 1000}, {"tap": "KEY_B"}], on_release="cancel")]
    )
    rig.press()
    rig.at(50)
    rig.release()
    rig.at(2000)
    assert rig.keys() == [(0, "KEY_A", "down"), (50, "KEY_A", "up")]
    assert rig.engine.running_macros() == []


def test_retrigger_ignore_and_restart():
    steps = [{"tap": "KEY_A"}, {"wait_ms": 100}]
    rig = Rig([mapping(steps)])
    rig.press()
    rig.release()
    rig.at(30)
    rig.press()  # still running: ignored
    rig.release()
    rig.at(500)
    assert [k for k in rig.keys() if k[2] == "down"] == [(0, "KEY_A", "down")]

    rig = Rig([mapping(steps, on_retrigger="restart")])
    rig.press()
    rig.release()
    rig.at(30)
    rig.press()  # restarts
    rig.release()
    rig.at(500)
    assert [k for k in rig.keys() if k[2] == "down"] == [
        (0, "KEY_A", "down"),
        (30, "KEY_A", "down"),
    ]


def test_restart_releases_keys_of_cancelled_run():
    rig = Rig([mapping([{"press": "KEY_A"}, {"wait_ms": 1000}], on_retrigger="restart")])
    rig.press()
    rig.release()
    rig.at(30)
    rig.press()
    rig.at(31)
    assert rig.keys() == [(0, "KEY_A", "down"), (30, "KEY_A", "up"), (30, "KEY_A", "down")]


def test_release_steps_after_steps_and_release():
    rig = Rig([mapping([{"tap": "KEY_A"}], release_steps=[{"tap": "KEY_B"}])])
    rig.press()
    rig.at(200)
    assert [k[1] for k in rig.keys() if k[2] == "down"] == ["KEY_A"]
    rig.release()
    rig.at(400)
    assert [k for k in rig.keys() if k[2] == "down"][-1] == (200, "KEY_B", "down")


def test_release_steps_with_cancel():
    rig = Rig(
        [
            mapping(
                [{"press": "KEY_A"}, {"wait_ms": 1000}],
                release_steps=[{"tap": "KEY_B"}],
                on_release="cancel",
            )
        ]
    )
    rig.press()
    rig.at(50)
    rig.release()
    rig.at(200)
    assert [k[1:] for k in rig.keys()] == [
        ("KEY_A", "down"),
        ("KEY_A", "up"),
        ("KEY_B", "down"),
        ("KEY_B", "up"),
    ]


def test_max_run_ms_cancels(caplog):
    rig = Rig([mapping([{"press": "KEY_A"}, {"wait_ms": 10000}], max_run_ms=500)])
    rig.press()
    with caplog.at_level(logging.WARNING):
        rig.at(1000)
    assert rig.keys()[-1] == (500, "KEY_A", "up")
    assert "exceeded max_run_ms" in caplog.text


# -- loops ---------------------------------------------------------------------------


def test_repeat_and_variable_count():
    rig = Rig(
        [mapping([{"repeat": {"var": "n"}, "steps": [{"tap": "KEY_A"}]}])], variables={"n": 3}
    )
    rig.press()
    rig.at(1000)
    assert len([k for k in rig.keys() if k[2] == "down"]) == 3


def test_while_held_finishes_iteration_after_release():
    rig = Rig([mapping([{"while_held": [{"tap": "KEY_A", "pause_ms": 25}]}])])
    rig.press()
    rig.at(110)  # iterations start at 0, 50, 100
    rig.release()
    rig.at(500)
    downs = [k[0] for k in rig.keys() if k[2] == "down"]
    assert downs == [0, 50, 100]
    assert rig.keys()[-1] == (125, "KEY_A", "up")  # third iteration completed


def test_while_held_with_instant_body_does_not_spin():
    rig = Rig([mapping([{"while_held": [{"set": {"var": "n", "value": 1}}]}])], variables={"n": 0})
    rig.press()
    rig.at(50)
    rig.release()
    rig.at(60)
    assert rig.engine.running_macros() == []  # ended; at most ~50 iterations ran


def test_toggle_starts_and_stops_on_presses():
    rig = Rig([mapping([{"toggle": [{"tap": "KEY_A", "pause_ms": 50}]}])])
    rig.press()
    rig.release()  # release has no effect on a toggle
    rig.at(250)
    assert len([k for k in rig.keys() if k[2] == "down"]) == 3  # at 0, 100, 200
    rig.press()  # stop after the current iteration
    rig.release()
    rig.at(1000)
    assert len([k for k in rig.keys() if k[2] == "down"]) == 3
    assert rig.engine.running_macros() == []


def test_parallel_waits_for_all_branches():
    rig = Rig(
        [
            mapping(
                [
                    {
                        "parallel": [
                            [{"wait_ms": 100}, {"tap": "KEY_A", "pause_ms": 0}],
                            [{"tap": "KEY_B", "pause_ms": 0}],
                        ]
                    },
                    {"tap": "KEY_C", "pause_ms": 0},
                ]
            )
        ]
    )
    rig.press()
    rig.at(500)
    assert [k for k in rig.keys() if k[2] == "down"] == [
        (0, "KEY_B", "down"),
        (100, "KEY_A", "down"),
        (100, "KEY_C", "down"),
    ]


# -- conditions -------------------------------------------------------------------------

TAP_DOUBLE_LONG = [
    {
        "if_tap": {
            "then": [
                {
                    "if_tap": {
                        "then": [{"tap": "KEY_2", "pause_ms": 0}],
                        "else": [{"tap": "KEY_1", "pause_ms": 0}],
                    }
                }
            ],
            "else": [{"tap": "KEY_3", "pause_ms": 0}],
        }
    }
]


def downs(rig):
    return [k[1] for k in rig.keys() if k[2] == "down"]


def test_if_tap_single_double_and_long():
    rig = Rig([mapping(TAP_DOUBLE_LONG)])
    rig.press()
    rig.at(50)
    rig.release()
    rig.at(1000)
    assert downs(rig) == ["KEY_1"]

    rig = Rig([mapping(TAP_DOUBLE_LONG)])
    rig.press()
    rig.at(50)
    rig.release()
    rig.at(120)
    rig.press()
    rig.at(160)
    rig.release()
    rig.at(1000)
    assert downs(rig) == ["KEY_2"]

    rig = Rig([mapping(TAP_DOUBLE_LONG)])
    rig.press()
    rig.at(1000)
    assert downs(rig) == ["KEY_3"]
    assert rig.keys()[0][0] == 300  # decided at the timeout


IF_SINGLE = [
    {
        "if_single": {
            "then": [{"tap": "KEY_ESC", "pause_ms": 0}],
            "else": [{"hold_keys": "KEY_LEFTCTRL"}],
        }
    }
]


def test_if_single_alone():
    rig = Rig([mapping(IF_SINGLE, code="KEY_CAPSLOCK", key_pause_ms=0)])
    rig.press("KEY_CAPSLOCK")
    rig.at(100)
    rig.release("KEY_CAPSLOCK")
    rig.at(200)
    assert downs(rig) == ["KEY_ESC"]


def test_if_single_with_other_key_acts_before_that_key():
    rig = Rig([mapping(IF_SINGLE, code="KEY_CAPSLOCK", key_pause_ms=0)])
    rig.press("KEY_CAPSLOCK")
    rig.at(100)
    handled = rig.press("KEY_C")  # unmapped: the runtime forwards it after handle()
    assert handled is False
    assert rig.keys() == [(100, "KEY_LEFTCTRL", "down")]  # Ctrl already down
    rig.release("KEY_C")
    rig.at(300)
    rig.release("KEY_CAPSLOCK")  # Ctrl is held until the trigger is released
    assert rig.keys()[-1] == (300, "KEY_LEFTCTRL", "up")


def test_if_single_timeout():
    steps = [
        {"if_single": {"then": [{"tap": "KEY_A"}], "else": [{"tap": "KEY_B"}], "timeout_ms": 200}}
    ]
    rig = Rig([mapping(steps)])
    rig.press()
    rig.at(1000)
    assert downs(rig) == ["KEY_B"]
    assert rig.keys()[0][0] == 200


def test_variables_set_add_if_eq_shared_between_macros():
    rig = Rig(
        [
            mapping([{"add": {"var": "n", "value": 1}}], code="KEY_F1"),
            mapping(
                [
                    {
                        "if_eq": {
                            "var": "n",
                            "value": 2,
                            "then": [{"tap": "KEY_A"}],
                            "else": [{"tap": "KEY_B"}],
                        }
                    }
                ],
                code="KEY_F2",
            ),
        ],
        variables={"n": 0},
    )
    for _ in range(2):
        rig.press("KEY_F1")
        rig.release("KEY_F1")
    rig.press("KEY_F2")
    rig.at(100)
    assert downs(rig) == ["KEY_A"]
    assert rig.engine.variables["n"] == 2


def test_if_led_uses_trigger_device():
    steps = [
        {"if_led": {"led": "capslock", "then": [{"tap": "KEY_A"}], "else": [{"tap": "KEY_B"}]}}
    ]
    rig = Rig([mapping(steps)], leds={"kbd": {Led.CAPSLOCK}})
    rig.press()
    rig.at(100)
    assert downs(rig) == ["KEY_A"]
    rig = Rig([mapping(steps)], leds={"pad": {Led.CAPSLOCK}})  # other device's LED
    rig.press()
    rig.at(100)
    assert downs(rig) == ["KEY_B"]


# -- axes ---------------------------------------------------------------------------------


def test_axis_ramp_and_return_to_rest_at_run_end():
    steps = [{"axis": "ABS_X", "device": "gp", "to": 1.0, "over_ms": 40}, {"wait_ms": 100}]
    rig = Rig([mapping(steps)])
    rig.press()
    rig.at(500)
    assert rig.axis() == [(10, 0.25), (20, 0.5), (30, 0.75), (40, 1.0), (140, 0.0)]


def test_hold_axis_attack_hold_release():
    steps = [
        {"hold_axis": "ABS_X", "device": "gp", "value": -1.0, "attack_ms": 20, "release_ms": 20}
    ]
    rig = Rig([mapping(steps)])
    rig.press()
    rig.at(100)
    rig.release()
    rig.at(300)
    assert rig.axis() == [(10, -0.5), (20, -1.0), (110, -0.5), (120, 0.0)]


def test_plain_axis_output_and_holder_stack():
    rig = Rig(
        [
            mapping(
                code="KEY_A",
                outputs=[{"device": "gp", "type": "axis", "code": "ABS_X", "value": -1}],
            ),
            mapping(
                code="KEY_D",
                outputs=[{"device": "gp", "type": "axis", "code": "ABS_X", "value": 1}],
            ),
        ]
    )
    rig.press("KEY_A")
    rig.press("KEY_D")  # most recent holder wins
    rig.release("KEY_D")  # back to the previous holder
    rig.release("KEY_A")  # back to rest
    rig.at(10)
    assert [v for _t, v in rig.axis()] == [-1.0, 1.0, -1.0, 0.0]


def test_plain_axis_retrigger_during_release_ramp_does_not_jump_to_rest():
    outputs = [
        {
            "device": "gp",
            "type": "axis",
            "code": "ABS_Y",
            "value": -1,
            "attack_ms": 20,
            "release_ms": 40,
        }
    ]
    rig = Rig([mapping(code="KEY_W", outputs=outputs)])
    rig.press("KEY_W")
    rig.at(100)
    rig.release("KEY_W")
    rig.at(120)  # halfway back (-0.5)
    rig.press("KEY_W")  # restart from the current value
    rig.at(200)
    values = [v for _t, v in rig.axis(ABS_Y)]
    assert 0.0 not in values
    assert values[-1] == -1.0


# -- shutdown, device loss, errors -------------------------------------------------------------


def test_release_all_cancels_runs_and_gives_back_everything():
    steps = [
        {"press": "KEY_A"},
        {"axis": "ABS_X", "device": "gp", "to": 1},
        {"wait_ms": 10000},
    ]
    rig = Rig([mapping(steps)])
    rig.press()
    rig.at(100)
    rig.engine.release_all()
    assert rig.keys()[-1][1:] == ("KEY_A", "up")
    assert rig.axis()[-1][1] == 0.0
    assert rig.engine.running_macros() == []
    assert rig.engine.held_outputs() == set()


def test_device_loss_cancels_runs_of_that_device_only():
    rig = Rig(
        [
            mapping([{"press": "KEY_A"}, {"wait_ms": 10000}], code="KEY_X"),
            mapping([{"press": "KEY_B"}, {"wait_ms": 10000}], code="BTN_EAST", device="pad"),
        ]
    )
    rig.press("KEY_X")
    rig.press("BTN_EAST", device="pad")
    rig.at(50)
    rig.engine.release_device("kbd")
    assert rig.engine.held_outputs() == {("kb", c("KEY_B"))}
    assert len(rig.engine.running_macros()) == 1


def test_output_error_in_timed_step_is_raised_from_tick():
    rig = Rig([mapping([{"wait_ms": 100}, {"tap": "KEY_A"}])])
    rig.press()
    rig.sink.fail = True
    with pytest.raises(OutputError):
        rig.at(200)

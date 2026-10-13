"""Modifier matching (docs/configuration.md §5.2) and masking in the engine."""

import pytest

from inpmap.codes import code_from_name as c
from inpmap.dsl.compiler import compile_text
from inpmap.engine import MappingEngine
from inpmap.models import InputEvent, KeyAction, Modifier
from inpmap.modifiers import ModifierState, choose

PRESS, RELEASE, REPEAT = KeyAction.PRESS, KeyAction.RELEASE, KeyAction.REPEAT

HEADER = """version 1
input kbd { name = "Kbd" }
input pad { name = "Pad" }
output keyboard { type = keyboard }
output gamepad { type = gamepad }
map pad.BTN_MODE { hold BTN_MODE; hold KEY_F24 }
"""


def config(body: str, header: str = HEADER):
    return compile_text(header + body, "t.inpmap").config


class Sink:
    def __init__(self):
        self.log = []

    def press(self, device, code):
        self.log.append(("down", device, code))

    def release(self, device, code):
        self.log.append(("up", device, code))

    def set_axis(self, device, code, value):
        self.log.append(("axis", device, code, value))


class Control:
    """Records mask/unmask calls into the same log as the sink."""

    def __init__(self, log):
        self.log = log

    def mask(self, device, code):
        self.log.append(("mask", device, code))

    def unmask(self, device, code):
        self.log.append(("unmask", device, code))


class Rig:
    def __init__(self, body, header=HEADER):
        self.now = 0.0
        self.sink = Sink()
        self.engine = MappingEngine(
            config(body, header), self.sink, clock=lambda: self.now, inputs=Control(self.sink.log)
        )

    def ev(self, name, action, device="kbd"):
        return self.engine.handle(InputEvent(device, c(name), action))

    def press(self, name, device="kbd"):
        return self.ev(name, PRESS, device)

    def release(self, name, device="kbd"):
        return self.ev(name, RELEASE, device)

    def at(self, ms):
        target = ms / 1000
        while (due := self.engine.next_deadline()) is not None and due <= target:
            self.now = max(self.now, due)
            self.engine.tick()
        self.now = target
        self.engine.tick()

    def log(self):
        def name(code):
            from inpmap.codes import code_name

            return code_name(code)

        return [(entry[0], name(entry[2])) for entry in self.sink.log]


# -- matching ---------------------------------------------------------------------------


def state_with(*keys):
    state = ModifierState(Modifier)
    for device, name in keys:
        state.update(device, c(name), PRESS)
    return state


def rules(body):
    return [m for m in config(body).mappings if m.id != "pad.BTN_MODE"]


ALL = """
map kbd.KEY_A { tap KEY_1 }
map kbd.KEY_A modifiers(shift) { tap KEY_2 }
map kbd.KEY_A modifiers(right_shift) { tap KEY_3 }
map kbd.KEY_A modifiers(ctrl, shift) { tap KEY_4 }
map kbd.KEY_A modifiers(ignore) { tap KEY_5 }
"""


@pytest.mark.parametrize(
    "held, expected",
    [
        ((), "kbd.KEY_A"),
        ((("kbd", "KEY_LEFTSHIFT"),), "kbd.KEY_A+shift"),
        ((("kbd", "KEY_RIGHTSHIFT"),), "kbd.KEY_A+right_shift"),  # sided beats either
        ((("kbd", "KEY_LEFTSHIFT"), ("kbd", "KEY_RIGHTSHIFT")), "kbd.KEY_A+shift"),
        ((("kbd", "KEY_LEFTCTRL"), ("kbd", "KEY_RIGHTSHIFT")), "kbd.KEY_A+ctrl+shift"),
        ((("kbd", "KEY_LEFTALT"),), "kbd.KEY_A+ignore"),  # nothing exact: fallback
        (
            (("kbd", "KEY_LEFTCTRL"), ("kbd", "KEY_LEFTSHIFT"), ("kbd", "KEY_LEFTMETA")),
            "kbd.KEY_A+ignore",
        ),
    ],
)
def test_choose_best_match(held, expected):
    assert choose(rules(ALL), state_with(*held)).id == expected


def test_no_match_without_fallback():
    candidates = rules("map kbd.KEY_A { tap KEY_1 }")
    assert choose(candidates, state_with(("kbd", "KEY_LEFTSHIFT"))) is None


def test_exact_side_requires_only_that_side():
    candidates = rules("map kbd.KEY_A modifiers(left_ctrl) { tap KEY_1 }")
    assert choose(candidates, state_with(("kbd", "KEY_LEFTCTRL"))) is not None
    assert choose(candidates, state_with(("kbd", "KEY_RIGHTCTRL"))) is None
    both = state_with(("kbd", "KEY_LEFTCTRL"), ("kbd", "KEY_RIGHTCTRL"))
    assert choose(candidates, both) is None


def test_modifiers_from_another_device_and_release_updates_state():
    candidates = rules("map pad.BTN_SOUTH modifiers(ctrl) { tap KEY_1 }")
    state = state_with(("kbd", "KEY_RIGHTCTRL"))
    assert choose(candidates, state) is not None
    state.update("kbd", c("KEY_RIGHTCTRL"), RELEASE)
    assert choose(candidates, state) is None


def test_tie_goes_to_first_defined():
    candidates = rules(
        """
map kbd.KEY_A modifiers(left_ctrl, shift) as first { tap KEY_1 }
map kbd.KEY_A modifiers(ctrl, left_shift) as second { tap KEY_2 }
"""
    )
    held = state_with(("kbd", "KEY_LEFTCTRL"), ("kbd", "KEY_LEFTSHIFT"))
    assert choose(candidates, held).id == "first"


def test_inactive_modifier_group_is_a_normal_key():
    header = HEADER.replace("version 1\n", "version 1\nsettings { modifiers = ctrl, alt, meta }\n")
    candidates = [
        m for m in config("map kbd.KEY_A { tap KEY_1 }", header).mappings if m.id == "kbd.KEY_A"
    ]
    state = ModifierState({Modifier.CTRL, Modifier.ALT, Modifier.META})
    state.update("kbd", c("KEY_LEFTSHIFT"), PRESS)  # not a modifier here
    assert choose(candidates, state) is not None


# -- engine: matching, passthrough, masking --------------------------------------------------

CASE_1 = """
map kbd.KEY_LEFTBRACE modifiers(ctrl, shift) as bracket_combo {
    tap KEY_ENTER (pause 0ms)
    wait 20ms
    hold ctrl + shift + KEY_LEFTBRACE
    on release {
        wait 200ms
        tap KEY_ENTER (pause 0ms)
    }
}
"""


def test_users_case_1_masks_modifiers_until_the_run_has_finished():
    rig = Rig(CASE_1)
    assert rig.press("KEY_LEFTCTRL") is False  # modifiers pass through
    assert rig.press("KEY_LEFTSHIFT") is False
    assert rig.press("KEY_LEFTBRACE") is True
    # Ctrl and Shift are hidden before the first output
    assert rig.log()[:3] == [
        ("mask", "KEY_LEFTCTRL"),
        ("mask", "KEY_LEFTSHIFT"),
        ("down", "KEY_ENTER"),
    ]
    rig.at(100)
    assert ("down", "KEY_LEFTBRACE") in rig.log()  # the held chord on the virtual keyboard
    rig.release("KEY_LEFTBRACE")
    rig.at(150)
    assert ("unmask", "KEY_LEFTCTRL") not in rig.log()  # release steps still running
    rig.at(500)
    log = rig.log()
    assert log[-2:] == [("unmask", "KEY_LEFTCTRL"), ("unmask", "KEY_LEFTSHIFT")]
    assert log.index(("up", "KEY_ENTER"), 2) < log.index(("unmask", "KEY_LEFTCTRL"))


def test_plain_mapping_fires_only_without_modifiers():
    rig = Rig("map kbd.KEY_X { hold KEY_Y }")
    rig.press("KEY_LEFTSHIFT")
    assert rig.press("KEY_X") is False  # Shift+X passes through unchanged
    assert rig.ev("KEY_X", REPEAT) is False
    assert rig.release("KEY_X") is False
    rig.release("KEY_LEFTSHIFT")
    assert rig.press("KEY_X") is True
    assert rig.log() == [("down", "KEY_Y")]


def test_ignore_does_not_mask():
    rig = Rig("map kbd.KEY_A modifiers(ignore) { hold KEY_B }")
    rig.press("KEY_LEFTSHIFT")
    assert rig.press("KEY_A") is True
    rig.release("KEY_A")
    assert rig.log() == [("down", "KEY_B"), ("up", "KEY_B")]


def test_keep_modifiers_does_not_mask():
    rig = Rig("map kbd.KEY_A modifiers(shift) { keep modifiers; hold KEY_B }")
    rig.press("KEY_LEFTSHIFT")
    rig.press("KEY_A")
    rig.release("KEY_A")
    assert rig.log() == [("down", "KEY_B"), ("up", "KEY_B")]


def test_plain_output_with_modifiers_unmasks_on_release():
    rig = Rig("map pad.BTN_SOUTH modifiers(ctrl) { hold KEY_C }")
    rig.press("KEY_RIGHTCTRL")
    rig.press("BTN_SOUTH", device="pad")
    rig.release("BTN_SOUTH", device="pad")
    assert rig.log() == [
        ("mask", "KEY_RIGHTCTRL"),
        ("down", "KEY_C"),
        ("up", "KEY_C"),
        ("unmask", "KEY_RIGHTCTRL"),
    ]


def test_overlapping_activations_share_one_mask():
    rig = Rig(
        """
map kbd.KEY_A modifiers(ctrl) { hold KEY_1 }
map kbd.KEY_B modifiers(ctrl) { hold KEY_2 }
"""
    )
    rig.press("KEY_LEFTCTRL")
    rig.press("KEY_A")
    rig.press("KEY_B")
    rig.release("KEY_A")
    assert ("unmask", "KEY_LEFTCTRL") not in rig.log()  # B still holds it
    rig.release("KEY_B")
    assert rig.log().count(("mask", "KEY_LEFTCTRL")) == 1
    assert rig.log()[-1] == ("unmask", "KEY_LEFTCTRL")


def test_modifier_change_while_held_does_not_affect_running_mapping():
    rig = Rig("map kbd.KEY_A modifiers(ctrl) { hold KEY_1 }")
    rig.press("KEY_LEFTCTRL")
    rig.press("KEY_A")
    rig.release("KEY_LEFTCTRL")  # trigger stays active
    assert rig.release("KEY_A") is True
    assert ("up", "KEY_1") in rig.log()


def test_device_loss_drops_modifier_state_and_masks():
    rig = Rig("map pad.BTN_SOUTH modifiers(ctrl) { hold KEY_C }")
    rig.press("KEY_LEFTCTRL")
    rig.engine.release_device("kbd")
    assert rig.press("BTN_SOUTH", device="pad") is False  # Ctrl is gone with the keyboard
    rig.release("BTN_SOUTH", device="pad")
    rig = Rig("map pad.BTN_SOUTH modifiers(ctrl) { hold KEY_C }")
    rig.press("KEY_LEFTCTRL")
    rig.press("BTN_SOUTH", device="pad")
    rig.engine.release_device("kbd")
    rig.release("BTN_SOUTH", device="pad")
    assert ("unmask", "KEY_LEFTCTRL") not in rig.log()  # never re-pressed on a lost device

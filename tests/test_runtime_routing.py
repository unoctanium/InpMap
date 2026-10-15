"""The runtime routes unmapped input to the outputs (docs/configuration.md §3.4)."""

import logging
import threading

import pytest
from fakes import SYN, FakeInputBackend, FakeInputSource, FakeOutputBackend, abs_raw, key_raw

from inpmap.codes import code_from_name as c
from inpmap.dsl.compiler import compile_text
from inpmap.input import InputError
from inpmap.macros import Led
from inpmap.routing import InputRefused
from inpmap.runtime import Runtime

KEY_A, KEY_X, KEY_Y = c("KEY_A"), c("KEY_X"), c("KEY_Y")
CTRL, KEY_F7, KEY_C = c("KEY_LEFTCTRL"), c("KEY_F7"), c("KEY_C")
BTN_SOUTH, BTN_EAST, BTN_LEFT = c("BTN_SOUTH"), c("BTN_EAST"), c("BTN_LEFT")
ABS_X, ABS_HAT0Y = 0x00, 0x11
REL_X = 0x00
PAD_KEYS = frozenset({BTN_SOUTH, BTN_EAST})
PAD_AXES = {ABS_X: (-32768, 32767), ABS_HAT0Y: (-1, 1)}

TEXT = """version 1
input kbd { name = "Kbd" }
input pad { name = "Pad" }
output keyboard { type = keyboard }
output gamepad { type = gamepad }
map kbd.KEY_X { hold KEY_Y }
map pad.BTN_EAST { hold KEY_Y }
map kbd.KEY_F7 modifiers(ctrl) { hold KEY_C }
"""


class Setup:
    def __init__(self, text=TEXT, pad_keys=PAD_KEYS, kbd_keys=None):
        self.config = compile_text(text, "t.inpmap").config
        self.journal = []
        self.stop = threading.Event()
        self.kbd = FakeInputSource(self.config.inputs["kbd"], journal=self.journal, keys=kbd_keys)
        self.sources = {"kbd": self.kbd}
        if "pad" in self.config.inputs:
            self.pad = FakeInputSource(
                self.config.inputs["pad"], journal=self.journal, keys=pad_keys, axes=PAD_AXES
            )
            self.sources["pad"] = self.pad
        self.inputs = FakeInputBackend(self.sources, stop=self.stop)
        self.outputs = FakeOutputBackend(journal=self.journal)

    def step(self, fn):
        self.inputs.script.append(fn)

    def run(self, **options):
        runtime = Runtime(self.config, self.inputs, self.outputs, reconnect_interval=0.0, **options)
        return runtime.run(self.stop)

    def events(self, output):
        return self.outputs.created[output].events


def test_unmapped_keys_reach_the_keyboard_output_and_nothing_is_passed_through():
    s = Setup()
    s.step(lambda: s.kbd.queue.extend([key_raw(KEY_A, 1), SYN, key_raw(KEY_A, 2), SYN]))
    s.step(lambda: s.kbd.queue.extend([key_raw(KEY_A, 0), SYN, key_raw(KEY_X, 1), SYN]))
    s.step(lambda: s.kbd.queue.extend([key_raw(KEY_X, 0), SYN]))
    s.run()
    assert s.events("keyboard") == [(KEY_A, True), (KEY_A, False), (KEY_Y, True), (KEY_Y, False)]
    assert s.kbd.forwarded == []


def test_pad_buttons_and_axes_reach_the_gamepad_output():
    s = Setup()
    s.step(lambda: s.pad.queue.extend([key_raw(BTN_SOUTH, 1), abs_raw(ABS_X, -16384), SYN]))
    s.step(lambda: s.pad.queue.extend([abs_raw(ABS_HAT0Y, -1), key_raw(BTN_SOUTH, 0), SYN]))
    s.step(lambda: s.pad.queue.extend([key_raw(BTN_EAST, 1), key_raw(BTN_EAST, 0), SYN]))
    s.run()
    gamepad = s.outputs.created["gamepad"]
    assert gamepad.events == [(BTN_SOUTH, True), (BTN_SOUTH, False)]
    # Axis values, then the axes return to rest when InpMap stops.
    assert gamepad.axis_events == [(ABS_X, -0.5), (ABS_HAT0Y, -1.0), (ABS_X, 0.0), (ABS_HAT0Y, 0.0)]
    assert s.events("keyboard") == [(KEY_Y, True), (KEY_Y, False)]  # BTN_EAST is mapped


def test_device_loss_releases_routed_keys_and_axes():
    s = Setup()
    s.step(lambda: s.pad.queue.extend([key_raw(BTN_SOUTH, 1), abs_raw(ABS_X, 32767), SYN]))

    def unplug():
        s.pad.lost = True
        s.inputs.open_error["pad"] = InputError("gone")  # stays away

    s.step(unplug)
    s.run()
    gamepad = s.outputs.created["gamepad"]
    assert gamepad.events == [(BTN_SOUTH, True), (BTN_SOUTH, False)]
    assert gamepad.axis_events == [(ABS_X, 1.0), (ABS_X, 0.0)]


def test_modifier_is_hidden_on_the_keyboard_output_while_a_mapping_runs():
    s = Setup()
    s.step(lambda: s.kbd.queue.extend([key_raw(CTRL, 1), SYN, key_raw(KEY_F7, 1), SYN]))
    s.step(lambda: s.kbd.queue.extend([key_raw(KEY_F7, 0), SYN, key_raw(CTRL, 0), SYN]))
    s.run()
    assert s.events("keyboard") == [
        (CTRL, True),
        (CTRL, False),
        (KEY_C, True),
        (KEY_C, False),
        (CTRL, True),
        (CTRL, False),
    ]


def test_keyboard_without_keyboard_output_is_refused_at_start_and_never_grabbed():
    s = Setup(
        """version 1
input kbd { name = "Kbd" }
output gamepad { type = gamepad }
map KEY_W { hold BTN_DPAD_UP }
"""
    )
    with pytest.raises(InputRefused, match="there is no keyboard output"):
        s.run()
    assert not any(entry.startswith("grab") for entry in s.journal)
    assert s.kbd.closed


def test_refused_at_start_is_an_error_also_when_waiting_for_devices():
    s = Setup(TEXT, pad_keys=frozenset({c("BTN_TRIGGER_HAPPY1"), BTN_EAST}))
    with pytest.raises(InputRefused, match="BTN_TRIGGER_HAPPY1"):
        s.run(wait_for_inputs=True)


def test_device_refused_when_it_appears_later_is_left_alone(caplog):
    s = Setup()
    s.inputs.open_error["pad"] = InputError("not connected")
    refused = FakeInputSource(
        s.config.inputs["pad"], keys=frozenset({c("BTN_TRIGGER_HAPPY1")}), journal=s.journal
    )

    def plug_in():
        del s.inputs.open_error["pad"]
        s.inputs.open_count["pad"] = 1  # the next open returns a replacement
        s.inputs.replacements["pad"] = [refused, refused]

    s.step(plug_in)
    s.step(lambda: s.kbd.queue.extend([key_raw(KEY_A, 1), key_raw(KEY_A, 0), SYN]))
    with caplog.at_level(logging.WARNING):
        s.run(wait_for_inputs=True)
    assert "not taken over" in caplog.text and "BTN_TRIGGER_HAPPY1" in caplog.text
    assert "grab pad" not in s.journal
    assert s.events("keyboard") == [(KEY_A, True), (KEY_A, False)]  # the keyboard kept running


def test_leds_set_on_the_keyboard_output_are_shown_on_routed_keyboards():
    s = Setup()

    def caps_lock_on():
        s.outputs.created["keyboard"].pending_leds = frozenset({Led.CAPSLOCK})

    s.step(lambda: None)
    s.step(caps_lock_on)
    s.step(lambda: None)
    s.run()
    assert "leds kbd ['capslock']" in s.journal
    assert "leds pad ['capslock']" in s.journal  # harmless: a pad has no LEDs
    assert s.kbd.lit == {Led.CAPSLOCK}


def test_mouse_parts_go_to_the_pass_through_device():
    s = Setup(kbd_keys=frozenset({KEY_A, KEY_X, KEY_F7, CTRL, BTN_LEFT}))
    s.kbd.relative = frozenset({REL_X})
    s.step(lambda: s.kbd.queue.extend([("rel", REL_X, 5), key_raw(BTN_LEFT, 1), SYN]))
    s.step(lambda: s.kbd.queue.extend([key_raw(BTN_LEFT, 0), key_raw(KEY_A, 1), SYN]))
    s.run()
    assert s.kbd.forwarded == [("rel", REL_X, 5), key_raw(BTN_LEFT, 1), key_raw(BTN_LEFT, 0)]
    assert (KEY_A, True) in s.events("keyboard")

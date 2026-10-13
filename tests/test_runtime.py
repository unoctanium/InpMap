import threading

import pytest
from fakes import SYN, FakeInputBackend, FakeInputSource, FakeOutputBackend, key_raw

from inpmap.codes import code_from_name as c
from inpmap.config import parse_config
from inpmap.input import InputError
from inpmap.output import OutputError
from inpmap.runtime import CleanupError, Runtime, StopReason

CONFIG = parse_config(
    {
        "version": 1,
        "inputs": {"kbd": {"name": "Kbd"}, "pad": {"name": "Pad"}},
        "outputs": {"vkbd": {"type": "keyboard"}, "vpad": {"type": "gamepad"}},
        "mappings": [
            {
                "id": "x",
                "input": {"device": "kbd", "type": "key", "code": "KEY_X"},
                "outputs": [
                    {"device": "vkbd", "type": "key", "code": "KEY_Y"},
                    {"device": "vpad", "type": "button", "code": "BTN_SOUTH"},
                ],
            },
            {
                "id": "east",
                "input": {"device": "pad", "type": "button", "code": "BTN_EAST"},
                "outputs": [{"device": "vkbd", "type": "key", "code": "KEY_Y"}],
            },
        ],
    }
)

KEY_X, KEY_A, KEY_Y = c("KEY_X"), c("KEY_A"), c("KEY_Y")
BTN_SOUTH, BTN_EAST = c("BTN_SOUTH"), c("BTN_EAST")


class Harness:
    def __init__(self):
        self.journal: list[str] = []
        self.stop = threading.Event()
        self.kbd = FakeInputSource(CONFIG.inputs["kbd"], journal=self.journal)
        self.pad = FakeInputSource(CONFIG.inputs["pad"], journal=self.journal)
        self.inputs = FakeInputBackend({"kbd": self.kbd, "pad": self.pad}, stop=self.stop)
        self.outputs = FakeOutputBackend(journal=self.journal)
        self.now = 0.0

    def clock(self):
        self.now += 0.01
        return self.now

    def step(self, fn):
        self.inputs.script.append(fn)

    def idle(self, count=1):
        for _ in range(count):
            self.step(lambda: None)

    def run(self, timeout=None, wait_for_inputs=False):
        runtime = Runtime(
            CONFIG,
            self.inputs,
            self.outputs,
            clock=self.clock,
            reconnect_interval=0.0,
            wait_for_inputs=wait_for_inputs,
        )
        return runtime.run(self.stop, timeout=timeout)

    def vkbd_events(self):
        return self.outputs.created["vkbd"].events

    def vpad_events(self):
        return self.outputs.created["vpad"].events

    def assert_all_cleaned_up(self):
        assert self.kbd.closed and self.pad.closed
        assert not self.kbd.grabbed and not self.pad.grabbed
        assert all(d.closed for d in self.outputs.created.values())


@pytest.fixture
def h():
    return Harness()


def test_mapped_key_is_remapped_and_suppressed(h):
    h.step(lambda: h.kbd.queue.extend([key_raw(KEY_X, 1), SYN]))
    h.step(lambda: h.kbd.queue.extend([key_raw(KEY_X, 2), SYN, key_raw(KEY_X, 0), SYN]))
    assert h.run() is StopReason.STOPPED
    assert h.vkbd_events() == [(KEY_Y, True), (KEY_Y, False)]
    assert h.vpad_events() == [(BTN_SOUTH, True), (BTN_SOUTH, False)]
    # the original X never reaches the desktop; SYN frames are passed through
    assert all(raw[0] != "key" for raw in h.kbd.forwarded)
    assert h.kbd.forwarded == [SYN, SYN, SYN]
    h.assert_all_cleaned_up()


def test_unmapped_events_are_forwarded_unchanged(h):
    msc = ("msc", 4, 0x70004)
    h.step(lambda: h.kbd.queue.extend([msc, key_raw(KEY_A, 1), SYN, key_raw(KEY_A, 2), SYN]))
    h.step(lambda: h.kbd.queue.extend([key_raw(KEY_A, 0), SYN]))
    h.run()
    assert h.kbd.forwarded == [
        msc,
        key_raw(KEY_A, 1),
        SYN,
        key_raw(KEY_A, 2),
        SYN,
        key_raw(KEY_A, 0),
        SYN,
    ]
    assert h.vkbd_events() == []


def test_mapped_codes_are_passed_to_backend(h):
    h.run()
    assert h.inputs.opened_codes == {"kbd": {KEY_X}, "pad": {BTN_EAST}}


def test_outputs_created_before_any_grab_and_cleanup_order(h):
    h.run()
    assert h.journal[:4] == ["create vkbd", "create vpad", "grab kbd", "grab pad"]
    assert h.journal[-2:] == ["close kbd", "close pad"]
    h.assert_all_cleaned_up()


def test_waits_for_held_keys_before_grabbing_and_discards_seen_events(h):
    h.kbd.held = {KEY_A}
    h.kbd.queue = [key_raw(KEY_A, 1), SYN]  # already delivered to the desktop
    h.idle()

    def release_a():
        assert not h.kbd.grabbed
        h.kbd.held.clear()
        h.kbd.queue += [key_raw(KEY_A, 0), SYN]

    h.step(release_a)
    h.idle()
    h.run()
    assert "grab kbd" in h.journal
    assert h.kbd.discarded == [key_raw(KEY_A, 1), SYN, key_raw(KEY_A, 0), SYN]
    assert h.kbd.forwarded == []  # nothing replayed to the desktop


def test_other_device_works_while_one_waits_for_release(h):
    h.kbd.held = {KEY_A}
    h.step(lambda: h.pad.queue.extend([key_raw(BTN_EAST, 1), SYN, key_raw(BTN_EAST, 0), SYN]))
    h.run()
    assert "grab kbd" not in h.journal
    assert h.vkbd_events() == [(KEY_Y, True), (KEY_Y, False)]


def test_stop_while_waiting_for_release(h):
    h.kbd.held = {KEY_A}
    h.step(h.stop.set)
    assert h.run() is StopReason.STOPPED
    assert "grab kbd" not in h.journal
    h.assert_all_cleaned_up()


def test_timeout(h):
    h.inputs.stop = None  # never stop via script; rely on the timeout
    assert h.run(timeout=1.0) is StopReason.TIMEOUT
    h.assert_all_cleaned_up()


def test_shared_output_across_devices(h):
    h.step(lambda: h.kbd.queue.extend([key_raw(KEY_X, 1), SYN]))
    h.step(lambda: h.pad.queue.extend([key_raw(BTN_EAST, 1), SYN]))
    h.step(lambda: h.kbd.queue.extend([key_raw(KEY_X, 0), SYN]))
    h.step(lambda: None)
    h.step(lambda: h.pad.queue.extend([key_raw(BTN_EAST, 0), SYN]))
    h.run()
    assert h.vkbd_events() == [(KEY_Y, True), (KEY_Y, False)]
    assert h.vpad_events() == [(BTN_SOUTH, True), (BTN_SOUTH, False)]


def test_stop_while_key_held_releases_outputs(h):
    h.step(lambda: h.kbd.queue.extend([key_raw(KEY_X, 1), SYN]))
    h.run()
    assert h.vkbd_events() == [(KEY_Y, True), (KEY_Y, False)]
    assert h.vpad_events() == [(BTN_SOUTH, True), (BTN_SOUTH, False)]
    h.assert_all_cleaned_up()


def test_device_loss_releases_outputs_and_reconnects(h):
    kbd2 = FakeInputSource(CONFIG.inputs["kbd"], journal=h.journal)
    h.inputs.replacements["kbd"] = [kbd2]
    h.step(lambda: h.kbd.queue.extend([key_raw(KEY_X, 1), SYN]))

    def unplug():
        h.kbd.lost = True
        h.inputs.open_error["kbd"] = InputError("not found")

    h.step(unplug)

    def check_released_while_absent():
        assert h.vkbd_events() == [(KEY_Y, True), (KEY_Y, False)]
        assert h.vpad_events() == [(BTN_SOUTH, True), (BTN_SOUTH, False)]
        assert h.kbd.closed
        assert h.pad.grabbed  # the other device keeps working

    h.step(check_released_while_absent)

    def replug():
        del h.inputs.open_error["kbd"]

    h.step(replug)
    h.idle()  # reopen + grab happen at the start of the next loop iteration

    def press_on_reconnected():
        assert kbd2.grabbed
        kbd2.queue.extend([key_raw(KEY_X, 1), SYN, key_raw(KEY_X, 0), SYN])

    h.step(press_on_reconnected)
    assert h.run() is StopReason.STOPPED
    assert h.vkbd_events()[2:] == [(KEY_Y, True), (KEY_Y, False)]
    assert h.inputs.open_count["kbd"] == 2  # initial + reconnect
    assert h.inputs.open_attempts["kbd"] >= 3  # ... with at least one failed retry between
    assert kbd2.closed and h.pad.closed


def test_shared_output_survives_loss_of_one_holder(h):
    h.inputs.replacements["kbd"] = []
    h.step(lambda: h.kbd.queue.extend([key_raw(KEY_X, 1), SYN]))
    h.step(lambda: h.pad.queue.extend([key_raw(BTN_EAST, 1), SYN]))

    def unplug():
        h.kbd.lost = True
        h.inputs.open_error["kbd"] = InputError("not found")

    h.step(unplug)

    def check():
        # KEY_Y is still held by the pad's mapping; BTN_SOUTH was released.
        assert h.vkbd_events() == [(KEY_Y, True)]
        assert h.vpad_events() == [(BTN_SOUTH, True), (BTN_SOUTH, False)]

    h.step(check)
    h.run()
    assert h.vkbd_events()[-1] == (KEY_Y, False)  # released at shutdown


def test_device_lost_while_waiting_for_release(h):
    h.kbd.held = {KEY_A}

    def unplug():
        h.kbd.lost = True
        h.inputs.open_error["kbd"] = InputError("not found")  # stays absent

    h.step(unplug)
    h.idle()
    assert h.run() is StopReason.STOPPED
    assert h.kbd.closed
    assert "grab kbd" not in h.journal


def test_input_open_failure_cleans_up_without_grabbing(h):
    h.inputs.open_error["pad"] = InputError("no such device")
    with pytest.raises(InputError, match="no such device"):
        h.run()
    assert not any(entry.startswith("grab") for entry in h.journal)
    assert h.kbd.closed  # already opened source is closed again
    assert all(d.closed for d in h.outputs.created.values())


def test_wait_for_inputs_starts_without_a_missing_device(h, caplog):
    h.inputs.open_error["pad"] = InputError("no such device")
    h.step(lambda: h.kbd.queue.extend([key_raw(KEY_X, 1), SYN, key_raw(KEY_X, 0), SYN]))
    h.idle(2)  # retries fail with the same reason: logged only once

    def plug_in():
        del h.inputs.open_error["pad"]

    h.step(plug_in)
    h.idle()  # opened and grabbed at the start of the next iteration

    def press_on_pad():
        assert h.pad.grabbed
        h.pad.queue.extend([key_raw(BTN_EAST, 1), SYN, key_raw(BTN_EAST, 0), SYN])

    h.step(press_on_pad)
    with caplog.at_level("INFO", logger="inpmap.runtime"):
        assert h.run(wait_for_inputs=True) is StopReason.STOPPED
    assert h.vkbd_events() == [(KEY_Y, True), (KEY_Y, False)] * 2
    waiting = [r for r in caplog.records if r.getMessage().startswith("waiting for input")]
    assert [r.getMessage() for r in waiting] == ["waiting for input 'pad': no such device"]
    assert h.inputs.open_attempts["pad"] >= 3
    h.assert_all_cleaned_up()


def test_wait_for_inputs_logs_a_changed_reason_again(h, caplog):
    h.inputs.open_error["pad"] = InputError("no such device")
    h.step(lambda: h.inputs.open_error.update(pad=InputError("no read access")))
    h.idle()
    with caplog.at_level("WARNING", logger="inpmap.runtime"):
        h.run(wait_for_inputs=True)
    assert [r.getMessage() for r in caplog.records] == [
        "waiting for input 'pad': no such device",
        "waiting for input 'pad': no read access",
    ]


def test_grab_failure_releases_earlier_grab(h):
    h.pad.grab_error = InputError("busy")
    with pytest.raises(InputError, match="busy"):
        h.run()
    h.assert_all_cleaned_up()


def test_output_creation_failure_opens_no_inputs(h):
    h.outputs.fail_on = "vpad"
    with pytest.raises(OutputError):
        h.run()
    assert h.inputs.opened_codes == {}
    assert h.outputs.created["vkbd"].closed


def test_output_error_during_remapping_cleans_up(h):
    def press_x_with_broken_pad():
        h.outputs.created["vpad"].fail_writes = True
        h.kbd.queue.extend([key_raw(KEY_X, 1), SYN])

    h.step(press_x_with_broken_pad)
    with pytest.raises(OutputError):
        h.run()
    assert h.vkbd_events() == [(KEY_Y, True), (KEY_Y, False)]
    h.assert_all_cleaned_up()


def test_cleanup_error_is_reported_after_full_cleanup(h):
    h.kbd.close_error = InputError("ungrab failed")
    with pytest.raises(CleanupError):
        h.run()
    assert h.pad.closed
    assert all(d.closed for d in h.outputs.created.values())


def test_keyboard_interrupt_cleans_up(h):
    def interrupt():
        h.kbd.queue.extend([key_raw(KEY_X, 1), SYN])
        raise KeyboardInterrupt

    h.step(lambda: h.kbd.queue.extend([key_raw(KEY_X, 1), SYN]))
    h.step(interrupt)
    with pytest.raises(KeyboardInterrupt):
        h.run()
    assert h.vkbd_events()[-1] == (KEY_Y, False)
    h.assert_all_cleaned_up()


def test_tap_output_is_released_by_the_loop():
    config = parse_config(
        {
            "version": 1,
            "inputs": {"kbd": {"name": "Kbd"}},
            "outputs": {"vkbd": {"type": "keyboard"}},
            "mappings": [
                {
                    "id": "x",
                    "input": {"device": "kbd", "type": "key", "code": "KEY_X"},
                    "outputs": [{"device": "vkbd", "type": "key", "code": "KEY_Y", "mode": "tap"}],
                }
            ],
        }
    )
    stop = threading.Event()
    kbd = FakeInputSource(config.inputs["kbd"])
    inputs = FakeInputBackend({"kbd": kbd}, stop=stop)
    outputs = FakeOutputBackend()
    now = [0.0]

    def clock():
        now[0] += 0.005
        return now[0]

    inputs.script.append(lambda: kbd.queue.extend([key_raw(KEY_X, 1), SYN]))
    inputs.script += [lambda: None] * 10  # ~10 loop iterations > tap duration
    Runtime(config, inputs, outputs, clock=clock).run(stop)
    assert outputs.created["vkbd"].events == [(KEY_Y, True), (KEY_Y, False)]


# -- macros through the runtime ------------------------------------------------------

MACRO_CONFIG = parse_config(
    {
        "version": 1,
        "inputs": {"kbd": {"name": "Kbd"}, "pad": {"name": "Pad"}},
        "outputs": {"vkbd": {"type": "keyboard"}},
        "mappings": [
            {
                "id": "led",
                "input": {"device": "kbd", "type": "key", "code": "KEY_X"},
                "outputs": [
                    {
                        "macro": {
                            "device": "vkbd",
                            "steps": [
                                {"wait_ms": 50},
                                {
                                    "if_led": {
                                        "led": "capslock",
                                        "then": [{"tap": "KEY_Y"}],
                                        "else": [{"tap": "KEY_N"}],
                                    }
                                },
                            ],
                        }
                    }
                ],
            },
            {
                "id": "single",
                "input": {"device": "pad", "type": "button", "code": "BTN_EAST"},
                "outputs": [
                    {
                        "macro": {
                            "device": "vkbd",
                            "steps": [
                                {
                                    "if_single": {
                                        "then": [{"tap": "KEY_ESC"}],
                                        "else": [{"hold_keys": "KEY_LEFTCTRL"}],
                                    }
                                }
                            ],
                        }
                    }
                ],
            },
        ],
    }
)


def macro_harness():
    from inpmap.macros import Led

    stop = threading.Event()
    kbd = FakeInputSource(MACRO_CONFIG.inputs["kbd"], lit={Led.CAPSLOCK})
    pad = FakeInputSource(MACRO_CONFIG.inputs["pad"])
    inputs = FakeInputBackend({"kbd": kbd, "pad": pad}, stop=stop)
    outputs = FakeOutputBackend()
    now = [0.0]

    def clock():
        now[0] += 0.002
        return now[0]

    def run():
        Runtime(MACRO_CONFIG, inputs, outputs, clock=clock).run(stop)

    return kbd, pad, inputs, outputs, run


def test_timed_macro_and_if_led_through_runtime():
    kbd, _pad, inputs, outputs, run = macro_harness()
    inputs.script.append(lambda: kbd.queue.extend([key_raw(KEY_X, 1), SYN, key_raw(KEY_X, 0), SYN]))
    inputs.script += [lambda: None] * 60  # the loop wakes for the macro's timers
    run()
    assert outputs.created["vkbd"].events == [(c("KEY_Y"), True), (c("KEY_Y"), False)]


def test_if_single_reacts_to_key_on_another_device_before_forwarding_it():
    kbd, pad, inputs, outputs, run = macro_harness()
    order = []
    original_forward = kbd.forward

    def forward(raw):
        order.append(("forward", raw))
        original_forward(raw)

    kbd.forward = forward
    inputs.script.append(lambda: pad.queue.extend([key_raw(BTN_EAST, 1), SYN]))

    def press_a():
        kbd.queue.extend([key_raw(KEY_A, 1), SYN])

    inputs.script.append(press_a)

    def check():
        assert outputs.created["vkbd"].events == [(c("KEY_LEFTCTRL"), True)]
        assert order[0] == ("forward", key_raw(KEY_A, 1))

    inputs.script.append(check)
    run()
    assert outputs.created["vkbd"].events[-1] == (c("KEY_LEFTCTRL"), False)  # released at stop


# -- modifiers through the runtime ------------------------------------------------------------


def test_modifiers_are_hidden_on_the_forwarding_device_and_restored():
    from inpmap.dsl.compiler import compile_text

    config = compile_text(
        """version 1
input kbd { name = "Kbd" }
output keyboard { type = keyboard }
map KEY_LEFTBRACE modifiers(ctrl, shift) { tap KEY_ENTER (pause 0ms) }
""",
        "t.inpmap",
    ).config
    stop = threading.Event()
    kbd = FakeInputSource(config.inputs["kbd"])
    inputs = FakeInputBackend({"kbd": kbd}, stop=stop)
    outputs = FakeOutputBackend()
    ctrl, shift, brace = c("KEY_LEFTCTRL"), c("KEY_LEFTSHIFT"), c("KEY_LEFTBRACE")

    inputs.script.append(lambda: kbd.queue.extend([key_raw(ctrl, 1), SYN, key_raw(shift, 1), SYN]))
    inputs.script.append(lambda: kbd.queue.extend([key_raw(brace, 1), SYN]))

    def check_hidden():
        # desktop saw Ctrl and Shift go down, then up again before the Enter
        assert [r for r in kbd.forwarded if r[0] == "key"] == [
            key_raw(ctrl, 1),
            key_raw(shift, 1),
            key_raw(ctrl, 0),
            key_raw(shift, 0),
        ]
        assert outputs.created["keyboard"].events == [
            (c("KEY_ENTER"), True),
            (c("KEY_ENTER"), False),
        ]
        kbd.queue.extend(
            [key_raw(brace, 0), SYN, key_raw(shift, 0), SYN]
        )  # Shift let go while hidden

    inputs.script.append(check_hidden)
    inputs.script.append(lambda: None)

    def check_restored():
        keys = [r for r in kbd.forwarded if r[0] == "key"]
        # only Ctrl is still held: pressed again; Shift's release was hidden
        assert keys[4:] == [key_raw(ctrl, 1)]
        kbd.queue.extend([key_raw(ctrl, 0), SYN])

    inputs.script.append(check_restored)
    inputs.script.append(lambda: None)
    Runtime(config, inputs, outputs).run(stop)
    assert [r for r in kbd.forwarded if r[0] == "key"][-1] == key_raw(ctrl, 0)

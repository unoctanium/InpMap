import threading

import pytest
from fakes import SYN, FakeInputBackend, FakeInputSource, FakeOutputBackend, key_raw

from inpmap.codes import code_from_name as c
from inpmap.config import parse_config
from inpmap.input import InputDeviceLost, InputError
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
        self.sleep_hook = None

    def clock(self):
        self.now += 0.01
        return self.now

    def sleep(self, seconds):
        self.now += seconds
        if self.sleep_hook:
            self.sleep_hook()

    def step(self, fn):
        self.inputs.script.append(fn)

    def run(self, timeout=None):
        runtime = Runtime(CONFIG, self.inputs, self.outputs, clock=self.clock, sleep=self.sleep)
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
    sleeps = []

    def release_after_three():
        sleeps.append(1)
        if len(sleeps) == 3:
            h.kbd.held.clear()
            h.kbd.queue += [key_raw(KEY_A, 0), SYN]

    h.sleep_hook = release_after_three
    h.run()
    assert len(sleeps) == 3
    assert h.kbd.discarded == [key_raw(KEY_A, 1), SYN, key_raw(KEY_A, 0), SYN]
    assert h.kbd.forwarded == []  # nothing replayed to the desktop


def test_stop_while_waiting_for_release(h):
    h.kbd.held = {KEY_A}
    h.sleep_hook = h.stop.set
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


def test_device_loss_releases_outputs_and_raises(h):
    h.step(lambda: h.kbd.queue.extend([key_raw(KEY_X, 1), SYN]))

    def lose():
        h.kbd.lost = True

    h.step(lose)
    with pytest.raises(InputDeviceLost):
        h.run()
    assert h.vkbd_events()[-1] == (KEY_Y, False)
    assert h.vpad_events()[-1] == (BTN_SOUTH, False)
    h.assert_all_cleaned_up()


def test_input_open_failure_cleans_up_without_grabbing(h):
    h.inputs.open_error["pad"] = InputError("no such device")
    with pytest.raises(InputError, match="no such device"):
        h.run()
    assert not any(entry.startswith("grab") for entry in h.journal)
    assert h.kbd.closed  # already opened source is closed again
    assert all(d.closed for d in h.outputs.created.values())


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

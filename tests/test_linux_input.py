"""Linux input backend tests.

The ``hardware`` test runs the real runtime against a *synthetic* physical
keyboard created via uinput. It grabs every output and forwarding device
itself before any event is emitted, so nothing reaches the desktop, and it
never touches real hardware.
"""

import contextlib
import select
import threading
import time
from itertools import pairwise

import pytest

evdev = pytest.importorskip("evdev")
from evdev import InputDevice, UInput, ecodes, list_devices  # noqa: E402
from hardware import output_backend  # noqa: E402

from inpmap.backends.linux_input import (  # noqa: E402
    FORWARD_NAME_PREFIX,
    LinuxInputBackend,
    forward_name,
)
from inpmap.config import MAX_DEVICE_NAME_BYTES, parse_config  # noqa: E402
from inpmap.input import InputError  # noqa: E402
from inpmap.models import InputDeviceSpec  # noqa: E402
from inpmap.runtime import Runtime, StopReason  # noqa: E402


def test_forward_name_fits_uinput_limit():
    name = forward_name("ä" * 100)
    assert name.startswith(FORWARD_NAME_PREFIX)
    assert len(name.encode("utf-8")) <= MAX_DEVICE_NAME_BYTES


def test_missing_path_is_reported():
    spec = InputDeviceSpec(id="kbd", path="/dev/input/by-id/does-not-exist")
    with pytest.raises(InputError, match="does not exist"):
        LinuxInputBackend().open(spec, frozenset())


def test_unknown_name_is_reported():
    spec = InputDeviceSpec(id="kbd", name="No Such Device 4f2a")
    with pytest.raises(InputError, match="no readable device named"):
        LinuxInputBackend().open(spec, frozenset())


# -- end-to-end with a synthetic physical keyboard ------------------------

PHYSICAL_NAME = "InpMap Test Synthetic Physical Keyboard"
# `to = own`: the device's unmapped input goes to its own pass-through device
# (the routed default is tested in the "routing" section below).
CONFIG = parse_config(
    {
        "version": 1,
        "inputs": {"kbd": {"name": PHYSICAL_NAME, "to": ["own"]}},
        "outputs": {
            "keyboard": {"type": "keyboard", "name": "InpMap Test E2E Keyboard"},
            "gamepad": {"type": "gamepad", "name": "InpMap Test E2E Gamepad"},
        },
        "mappings": [
            {
                "id": "x",
                "input": {"device": "kbd", "type": "key", "code": "KEY_X"},
                "outputs": [
                    {"device": "keyboard", "type": "key", "code": "KEY_Y"},
                    {"device": "gamepad", "type": "button", "code": "BTN_SOUTH"},
                ],
            }
        ],
    }
)


def find_device(name: str, timeout: float = 3.0) -> InputDevice:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        for path in list_devices(writable=False):
            device = InputDevice(path)
            if device.name == name:
                return device
            device.close()
        time.sleep(0.05)
    raise AssertionError(f"device '{name}' did not appear")


def read_key_events(device: InputDevice, count: int, timeout: float = 2.0):
    events = []
    deadline = time.monotonic() + timeout
    while len(events) < count and time.monotonic() < deadline:
        ready, _, _ = select.select([device.fd], [], [], deadline - time.monotonic())
        if ready:
            events += [(e.code, e.value) for e in device.read() if e.type == ecodes.EV_KEY]
    return events


def emit(uinput: UInput, code: int, value: int) -> None:
    uinput.write(ecodes.EV_KEY, code, value)
    uinput.syn()


@pytest.mark.hardware
def test_runtime_remaps_suppresses_and_forwards():
    keys = [ecodes.KEY_X, ecodes.KEY_A, ecodes.KEY_ESC]
    physical = UInput({ecodes.EV_KEY: keys}, name=PHYSICAL_NAME, phys="pytest-physical")
    stop = threading.Event()
    result: dict = {}
    grabbed: list[InputDevice] = []

    def run():
        try:
            runtime = Runtime(CONFIG, LinuxInputBackend(), output_backend())
            result["reason"] = runtime.run(stop, timeout=20)
        except BaseException as exc:  # reported by the main thread
            result["error"] = exc

    thread = threading.Thread(target=run, daemon=True)
    try:
        thread.start()
        # Grab our outputs and the forwarder before anything is emitted.
        for name in (
            "InpMap Test E2E Keyboard",
            "InpMap Test E2E Gamepad",
            forward_name(PHYSICAL_NAME),
        ):
            device = find_device(name)
            device.grab()
            grabbed.append(device)
        vkbd, vpad, forwarder = grabbed
        time.sleep(0.3)  # runtime grabs the physical device right after the forwarder exists
        assert "error" not in result, result.get("error")

        emit(physical, ecodes.KEY_X, 1)
        emit(physical, ecodes.KEY_A, 1)
        emit(physical, ecodes.KEY_A, 0)
        emit(physical, ecodes.KEY_X, 0)

        assert read_key_events(vkbd, 2) == [(ecodes.KEY_Y, 1), (ecodes.KEY_Y, 0)]
        assert read_key_events(vpad, 2) == [(ecodes.BTN_SOUTH, 1), (ecodes.BTN_SOUTH, 0)]
        # Forwarder carries KEY_A but never the remapped KEY_X.
        assert read_key_events(forwarder, 2) == [(ecodes.KEY_A, 1), (ecodes.KEY_A, 0)]
        assert read_key_events(forwarder, 1, timeout=0.3) == []
    finally:
        stop.set()
        thread.join(timeout=5)
        for device in grabbed:
            try:
                device.ungrab()
            except OSError:
                pass
            device.close()
        physical.close()
    assert not thread.is_alive()
    assert result.get("reason") is StopReason.STOPPED, result.get("error")


@pytest.mark.hardware
def test_runtime_survives_unplug_and_reconnects():
    def plug():
        return UInput({ecodes.EV_KEY: [ecodes.KEY_X]}, name=PHYSICAL_NAME, phys="pytest-physical")

    physical = plug()
    stop = threading.Event()
    result: dict = {}
    grabbed: list[InputDevice] = []

    def run():
        try:
            runtime = Runtime(CONFIG, LinuxInputBackend(), output_backend(), reconnect_interval=0.2)
            result["reason"] = runtime.run(stop, timeout=20)
        except BaseException as exc:
            result["error"] = exc

    thread = threading.Thread(target=run, daemon=True)
    try:
        thread.start()
        for name in ("InpMap Test E2E Keyboard", "InpMap Test E2E Gamepad"):
            device = find_device(name)
            device.grab()
            grabbed.append(device)
        vkbd, vpad = grabbed
        time.sleep(0.3)

        emit(physical, ecodes.KEY_X, 1)  # hold X ...
        assert read_key_events(vkbd, 1) == [(ecodes.KEY_Y, 1)]
        physical.close()  # ... and unplug while held
        assert read_key_events(vkbd, 1) == [(ecodes.KEY_Y, 0)]
        assert read_key_events(vpad, 2) == [(ecodes.BTN_SOUTH, 1), (ecodes.BTN_SOUTH, 0)]

        physical = plug()  # replug: same name, new event node
        time.sleep(1.0)  # > reconnect_interval + grab
        assert "error" not in result, result.get("error")
        emit(physical, ecodes.KEY_X, 1)
        emit(physical, ecodes.KEY_X, 0)
        assert read_key_events(vkbd, 2) == [(ecodes.KEY_Y, 1), (ecodes.KEY_Y, 0)]
    finally:
        stop.set()
        thread.join(timeout=5)
        for device in grabbed:
            try:
                device.ungrab()
            except OSError:
                pass
            device.close()
        physical.close()
    assert result.get("reason") is StopReason.STOPPED, result.get("error")


@pytest.mark.hardware
def test_led_state_set_on_forwarder_reaches_physical_keyboard():
    physical = UInput(
        {ecodes.EV_KEY: [ecodes.KEY_X], ecodes.EV_LED: [ecodes.LED_CAPSL, ecodes.LED_NUML]},
        name=PHYSICAL_NAME,
        phys="pytest-physical",
        max_effects=0,
    )
    stop = threading.Event()
    result: dict = {}
    forwarder = None

    def run():
        try:
            runtime = Runtime(CONFIG, LinuxInputBackend(), output_backend())
            result["reason"] = runtime.run(stop, timeout=20)
        except BaseException as exc:
            result["error"] = exc

    thread = threading.Thread(target=run, daemon=True)
    try:
        thread.start()
        forwarder = find_device(forward_name(PHYSICAL_NAME))
        time.sleep(0.3)
        # drain LED writes the desktop may have made on its own
        while select.select([physical.fd], [], [], 0.2)[0]:
            list(physical.read())
        forwarder.set_led(ecodes.LED_CAPSL, 1)  # what the desktop does on Caps Lock
        leds = []
        deadline = time.monotonic() + 2.0
        while (ecodes.LED_CAPSL, 1) not in leds and time.monotonic() < deadline:
            if select.select([physical.fd], [], [], 0.2)[0]:
                leds += [(e.code, e.value) for e in physical.read() if e.type == ecodes.EV_LED]
        assert (ecodes.LED_CAPSL, 1) in leds
        forwarder.set_led(ecodes.LED_CAPSL, 0)
    finally:
        stop.set()
        thread.join(timeout=5)
        if forwarder is not None:
            forwarder.close()
        physical.close()
    assert result.get("reason") is StopReason.STOPPED, result.get("error")


@pytest.mark.hardware
def test_tap_output_released_while_input_still_held():
    tap_config = parse_config(
        {
            "version": 1,
            "inputs": {"kbd": {"name": PHYSICAL_NAME}},
            "outputs": {"keyboard": {"type": "keyboard", "name": "InpMap Test E2E Keyboard"}},
            "mappings": [
                {
                    "id": "x",
                    "input": {"device": "kbd", "type": "key", "code": "KEY_X"},
                    "outputs": [
                        {"device": "keyboard", "type": "key", "code": "KEY_Y", "mode": "tap"}
                    ],
                }
            ],
        }
    )
    physical = UInput({ecodes.EV_KEY: [ecodes.KEY_X]}, name=PHYSICAL_NAME, phys="pytest-physical")
    stop = threading.Event()
    result: dict = {}
    vkbd = None

    def run():
        try:
            runtime = Runtime(tap_config, LinuxInputBackend(), output_backend())
            result["reason"] = runtime.run(stop, timeout=20)
        except BaseException as exc:
            result["error"] = exc

    thread = threading.Thread(target=run, daemon=True)
    try:
        thread.start()
        vkbd = find_device("InpMap Test E2E Keyboard")
        vkbd.grab()
        time.sleep(0.3)
        emit(physical, ecodes.KEY_X, 1)  # press and keep holding
        start = time.monotonic()
        assert read_key_events(vkbd, 2) == [(ecodes.KEY_Y, 1), (ecodes.KEY_Y, 0)]
        assert time.monotonic() - start < 0.5  # released by the timer, not by the input
        emit(physical, ecodes.KEY_X, 0)
        assert read_key_events(vkbd, 1, timeout=0.3) == []  # release of X emits nothing
    finally:
        stop.set()
        thread.join(timeout=5)
        if vkbd is not None:
            try:
                vkbd.ungrab()
            except OSError:
                pass
            vkbd.close()
        physical.close()
    assert result.get("reason") is StopReason.STOPPED, result.get("error")


@pytest.mark.hardware
def test_macro_and_axis_output_through_runtime():
    config = parse_config(
        {
            "version": 1,
            "inputs": {"kbd": {"name": PHYSICAL_NAME}},
            "outputs": {
                "keyboard": {"type": "keyboard", "name": "InpMap Test E2E Keyboard"},
                "gamepad": {"type": "gamepad", "name": "InpMap Test E2E Gamepad"},
            },
            "mappings": [
                {
                    "id": "combo",
                    "input": {"device": "kbd", "type": "key", "code": "KEY_X"},
                    "outputs": [
                        {
                            "macro": {
                                "steps": [
                                    {"tap": {"code": "KEY_A", "device": "keyboard"}},
                                    {"tap": {"code": "BTN_EAST", "device": "gamepad"}},
                                ]
                            }
                        }
                    ],
                },
                {
                    "id": "stick",
                    "input": {"device": "kbd", "type": "key", "code": "KEY_W"},
                    "outputs": [
                        {
                            "device": "gamepad",
                            "type": "axis",
                            "code": "ABS_Y",
                            "value": -1.0,
                            "attack_ms": 30,
                            "release_ms": 30,
                        }
                    ],
                },
            ],
        }
    )
    physical = UInput(
        {ecodes.EV_KEY: [ecodes.KEY_X, ecodes.KEY_W]}, name=PHYSICAL_NAME, phys="pytest-physical"
    )
    stop = threading.Event()
    result: dict = {}
    grabbed: list[InputDevice] = []

    def run():
        try:
            result["reason"] = Runtime(config, LinuxInputBackend(), output_backend()).run(
                stop, timeout=20
            )
        except BaseException as exc:
            result["error"] = exc

    def read_abs(device, until_value, timeout=2.0):
        values = []
        deadline = time.monotonic() + timeout
        while (not values or values[-1] != until_value) and time.monotonic() < deadline:
            if select.select([device.fd], [], [], 0.1)[0]:
                values += [e.value for e in device.read() if e.type == ecodes.EV_ABS]
        return values

    thread = threading.Thread(target=run, daemon=True)
    try:
        thread.start()
        for name in ("InpMap Test E2E Keyboard", "InpMap Test E2E Gamepad"):
            device = find_device(name)
            device.grab()
            grabbed.append(device)
        vkbd, vpad = grabbed
        time.sleep(0.3)
        assert "error" not in result, result.get("error")

        emit(physical, ecodes.KEY_X, 1)
        emit(physical, ecodes.KEY_X, 0)
        assert read_key_events(vkbd, 2) == [(ecodes.KEY_A, 1), (ecodes.KEY_A, 0)]
        assert read_key_events(vpad, 2) == [(ecodes.BTN_EAST, 1), (ecodes.BTN_EAST, 0)]

        emit(physical, ecodes.KEY_W, 1)
        attack = read_abs(vpad, -32768)
        assert attack[-1] == -32768 and len(attack) >= 2  # ramped, not a jump
        assert all(a > b for a, b in pairwise(attack))  # monotonic
        emit(physical, ecodes.KEY_W, 0)
        back = read_abs(vpad, 0)
        assert back[-1] == 0 and len(back) >= 2
    finally:
        stop.set()
        thread.join(timeout=5)
        for device in grabbed:
            try:
                device.ungrab()
            except OSError:
                pass
            device.close()
        physical.close()
    assert result.get("reason") is StopReason.STOPPED, result.get("error")


@pytest.mark.hardware
def test_modifiers_hidden_on_forwarder_before_output_and_restored():
    from inpmap.dsl.compiler import compile_text

    config = compile_text(
        f"""version 1
input kbd {{ name = "{PHYSICAL_NAME}"; to = own }}
output keyboard {{ type = keyboard; name = "InpMap Test E2E Keyboard" }}
map KEY_LEFTBRACE modifiers(ctrl, shift) {{ tap KEY_ENTER }}
""",
        "t.inpmap",
    ).config
    ctrl, shift, brace = ecodes.KEY_LEFTCTRL, ecodes.KEY_LEFTSHIFT, ecodes.KEY_LEFTBRACE
    physical = UInput(
        {ecodes.EV_KEY: [ctrl, shift, brace]}, name=PHYSICAL_NAME, phys="pytest-physical"
    )
    stop = threading.Event()
    result: dict = {}
    grabbed: list[InputDevice] = []

    def run():
        try:
            result["reason"] = Runtime(config, LinuxInputBackend(), output_backend()).run(
                stop, timeout=20
            )
        except BaseException as exc:
            result["error"] = exc

    def read_timed(device, count, timeout=2.0):
        events = []
        deadline = time.monotonic() + timeout
        while len(events) < count and time.monotonic() < deadline:
            if select.select([device.fd], [], [], 0.1)[0]:
                events += [
                    (e.code, e.value, e.timestamp())
                    for e in device.read()
                    if e.type == ecodes.EV_KEY
                ]
        return events

    thread = threading.Thread(target=run, daemon=True)
    try:
        thread.start()
        for name in ("InpMap Test E2E Keyboard", forward_name(PHYSICAL_NAME)):
            device = find_device(name)
            device.grab()
            grabbed.append(device)
        vkbd, forwarder = grabbed
        time.sleep(0.3)
        assert "error" not in result, result.get("error")

        emit(physical, ctrl, 1)
        emit(physical, shift, 1)
        assert [(c_, v) for c_, v, _t in read_timed(forwarder, 2)] == [(ctrl, 1), (shift, 1)]
        emit(physical, brace, 1)
        hidden = read_timed(forwarder, 2)
        assert [(c_, v) for c_, v, _t in hidden] == [(ctrl, 0), (shift, 0)]
        enter = read_timed(vkbd, 2)
        assert [(c_, v) for c_, v, _t in enter] == [(ecodes.KEY_ENTER, 1), (ecodes.KEY_ENTER, 0)]
        assert hidden[-1][2] <= enter[0][2]  # modifiers released before the Enter

        emit(physical, brace, 0)
        emit(physical, shift, 0)  # let go of Shift, keep Ctrl
        restored = read_timed(forwarder, 1)
        assert [(c_, v) for c_, v, _t in restored] == [(ctrl, 1)]
        emit(physical, ctrl, 0)
        assert [(c_, v) for c_, v, _t in read_timed(forwarder, 1)] == [(ctrl, 0)]
        assert read_timed(forwarder, 1, timeout=0.3) == []  # no stray events
    finally:
        stop.set()
        thread.join(timeout=5)
        for device in grabbed:
            try:
                device.ungrab()
            except OSError:
                pass
            device.close()
        physical.close()
    assert result.get("reason") is StopReason.STOPPED, result.get("error")


# -- LinuxInputSource with stand-ins for evdev objects ---------------------
# (Events on a destroyed uinput device cannot be read back, so cleanup
# ordering is checked here instead of against real devices.)


class StubEvent:
    def __init__(self, etype, code, value):
        self.type, self.code, self.value = etype, code, value


class StubDevice:
    name, path = "Stub", "/dev/input/event99"

    def __init__(self, events=(), read_error=None, ungrab_error=None):
        self.calls = []
        self._events = list(events)
        self._read_error = read_error
        self._ungrab_error = ungrab_error
        self.active = []  # what EVIOCGKEY would report

    def active_keys(self):
        return list(self.active)

    def capabilities(self, absinfo=False):
        return {ecodes.EV_KEY: [ecodes.KEY_A, ecodes.KEY_X]}

    def feed(self, *events):
        self._events += events

    def read(self):
        if self._read_error:
            raise self._read_error
        if not self._events:
            raise BlockingIOError
        events, self._events = self._events, []
        return iter(events)

    led_error = None

    def set_led(self, code, value):
        if self.led_error:
            raise self.led_error
        self.calls.append(("led", code, value))

    def grab(self):
        self.calls.append("grab")

    def ungrab(self):
        self.calls.append("ungrab")
        if self._ungrab_error:
            raise self._ungrab_error

    def close(self):
        self.calls.append("close")


class StubForwarder:
    def __init__(self):
        self.calls = []
        self.feedback = []  # events the desktop wrote to the forwarder

    def read(self):
        if not self.feedback:
            raise BlockingIOError
        events, self.feedback = self.feedback, []
        return iter(events)

    def write(self, etype, code, value):
        self.calls.append(("write", etype, code, value))

    def syn(self):
        self.calls.append(("syn",))

    def close(self):
        self.calls.append(("close",))


def make_source(**device_kwargs):
    from inpmap.backends.linux_input import LinuxInputSource

    device, forwarder = StubDevice(**device_kwargs), StubForwarder()
    return LinuxInputSource(CONFIG.inputs["kbd"], device, forwarder), device, forwarder


def test_read_translates_key_events_and_keeps_others_raw():
    from inpmap.models import InputEvent, KeyAction

    events = [
        StubEvent(ecodes.EV_MSC, ecodes.MSC_SCAN, 0x7001B),
        StubEvent(ecodes.EV_KEY, ecodes.KEY_X, 1),
        StubEvent(ecodes.EV_KEY, ecodes.KEY_X, 2),
        StubEvent(ecodes.EV_SYN, ecodes.SYN_REPORT, 0),
    ]
    source, _, _ = make_source(events=events)
    result = source.read()
    assert [event for event, _ in result] == [
        None,
        InputEvent("kbd", ecodes.KEY_X, KeyAction.PRESS),
        InputEvent("kbd", ecodes.KEY_X, KeyAction.REPEAT),
        None,
    ]
    assert result[0][1] is events[0]  # raw events are passed on unchanged
    assert source.read() == []  # nothing pending


def key_events(result):
    return [(e.code, e.action.value) for e, _ in result if e is not None]


def raw_triples(result):
    return [(r.type, r.code, r.value) for _, r in result]


def test_syn_dropped_synthesizes_missed_release():
    source, device, _ = make_source()
    device.feed(StubEvent(ecodes.EV_KEY, ecodes.KEY_X, 1), StubEvent(ecodes.EV_SYN, 0, 0))
    source.read()
    # The release of X was lost in the overflow; X is no longer down.
    device.active = []
    device.feed(
        StubEvent(ecodes.EV_SYN, ecodes.SYN_DROPPED, 0),
        StubEvent(ecodes.EV_KEY, ecodes.KEY_B, 1),  # incomplete frame: ignored
        StubEvent(ecodes.EV_SYN, ecodes.SYN_REPORT, 0),
        StubEvent(ecodes.EV_KEY, ecodes.KEY_C, 1),  # normal again
    )
    result = source.read()
    assert key_events(result) == [(ecodes.KEY_X, 0), (ecodes.KEY_C, 1)]
    # the synthesized release is forwardable and followed by a SYN_REPORT
    assert raw_triples(result)[:2] == [
        (ecodes.EV_KEY, ecodes.KEY_X, 0),
        (ecodes.EV_SYN, ecodes.SYN_REPORT, 0),
    ]


def test_syn_dropped_synthesizes_missed_press():
    source, device, _ = make_source()
    device.active = [ecodes.KEY_A]
    device.feed(
        StubEvent(ecodes.EV_SYN, ecodes.SYN_DROPPED, 0),
        StubEvent(ecodes.EV_SYN, ecodes.SYN_REPORT, 0),
    )
    assert key_events(source.read()) == [(ecodes.KEY_A, 1)]
    # later release is handled normally
    device.active = []
    device.feed(StubEvent(ecodes.EV_KEY, ecodes.KEY_A, 0))
    assert key_events(source.read()) == [(ecodes.KEY_A, 0)]


def test_syn_dropped_across_reads_and_no_changes():
    source, device, _ = make_source()
    device.feed(StubEvent(ecodes.EV_SYN, ecodes.SYN_DROPPED, 0))
    assert source.read() == []
    device.feed(
        StubEvent(ecodes.EV_KEY, ecodes.KEY_Q, 1),  # still dropping
        StubEvent(ecodes.EV_SYN, ecodes.SYN_REPORT, 0),
    )
    assert source.read() == []  # state unchanged: nothing synthesized


def test_pump_feedback_applies_leds_only():
    source, device, forwarder = make_source()
    forwarder.feedback = [
        StubEvent(ecodes.EV_LED, ecodes.LED_CAPSL, 1),
        StubEvent(ecodes.EV_SYN, ecodes.SYN_REPORT, 0),
        StubEvent(ecodes.EV_LED, ecodes.LED_NUML, 0),
    ]
    source.pump_feedback()
    assert device.calls == [("led", ecodes.LED_CAPSL, 1), ("led", ecodes.LED_NUML, 0)]
    source.pump_feedback()  # nothing pending: no error


def test_pump_feedback_led_failure_is_logged_once(caplog):
    source, device, forwarder = make_source()
    device.led_error = OSError(9, "Bad file descriptor")
    forwarder.feedback = [StubEvent(ecodes.EV_LED, ecodes.LED_CAPSL, 1)] * 3
    source.pump_feedback()
    assert sum("cannot set LEDs" in r.message for r in caplog.records) == 1


def test_mask_hides_forwarded_key_and_unmask_restores_it():
    source, device, forwarder = make_source()
    device.feed(StubEvent(ecodes.EV_KEY, ecodes.KEY_LEFTCTRL, 1))
    for _event, raw in source.read():
        source.forward(raw)
    source.mask(ecodes.KEY_LEFTCTRL)
    assert forwarder.calls[-2:] == [("write", ecodes.EV_KEY, ecodes.KEY_LEFTCTRL, 0), ("syn",)]
    source.forward(StubEvent(ecodes.EV_KEY, ecodes.KEY_LEFTCTRL, 2))  # repeat: hidden
    calls = len(forwarder.calls)
    source.unmask(ecodes.KEY_LEFTCTRL)  # still physically held: pressed again
    assert forwarder.calls[calls:] == [("write", ecodes.EV_KEY, ecodes.KEY_LEFTCTRL, 1), ("syn",)]


def test_key_released_while_masked_is_not_pressed_again():
    source, device, forwarder = make_source()
    device.feed(StubEvent(ecodes.EV_KEY, ecodes.KEY_LEFTCTRL, 1))
    for _event, raw in source.read():
        source.forward(raw)
    source.mask(ecodes.KEY_LEFTCTRL)
    device.feed(StubEvent(ecodes.EV_KEY, ecodes.KEY_LEFTCTRL, 0))
    for _event, raw in source.read():
        source.forward(raw)  # hidden: the forwarder already has it released
    calls = len(forwarder.calls)
    source.unmask(ecodes.KEY_LEFTCTRL)
    assert forwarder.calls[calls:] == []


def test_keys_held_at_open_are_known():
    from inpmap.backends.linux_input import LinuxInputSource

    device = StubDevice()
    device.active = [ecodes.KEY_LEFTSHIFT]
    source = LinuxInputSource(CONFIG.inputs["kbd"], device, StubForwarder())
    device.active = []  # shift released during an overflow
    device.feed(
        StubEvent(ecodes.EV_SYN, ecodes.SYN_DROPPED, 0),
        StubEvent(ecodes.EV_SYN, ecodes.SYN_REPORT, 0),
    )
    assert key_events(source.read()) == [(ecodes.KEY_LEFTSHIFT, 0)]


def test_read_on_vanished_device_raises_device_lost():
    import errno

    from inpmap.input import InputDeviceLost

    source, _, _ = make_source(read_error=OSError(errno.ENODEV, "No such device"))
    with pytest.raises(InputDeviceLost):
        source.read()


def test_close_releases_forwarded_held_keys_then_destroys():
    source, device, forwarder = make_source()
    source.grab()
    source.forward(StubEvent(ecodes.EV_KEY, ecodes.KEY_A, 1))
    source.forward(StubEvent(ecodes.EV_KEY, ecodes.KEY_B, 1))
    source.forward(StubEvent(ecodes.EV_KEY, ecodes.KEY_B, 0))
    source.close()
    assert forwarder.calls[-3:] == [
        ("write", ecodes.EV_KEY, ecodes.KEY_A, 0),
        ("syn",),
        ("close",),
    ]
    assert device.calls == ["grab", "ungrab", "close"]


def test_close_continues_after_ungrab_failure():
    source, device, forwarder = make_source(ungrab_error=OSError(5, "I/O error"))
    source.grab()
    source.forward(StubEvent(ecodes.EV_KEY, ecodes.KEY_A, 1))
    with pytest.raises(InputError, match="ungrab"):
        source.close()
    assert ("write", ecodes.EV_KEY, ecodes.KEY_A, 0) in forwarder.calls
    assert ("close",) in forwarder.calls
    assert device.calls[-1] == "close"


def test_close_after_device_loss_is_clean():
    import errno

    source, device, forwarder = make_source(ungrab_error=OSError(errno.ENODEV, "gone"))
    source.grab()
    source.close()  # ENODEV on ungrab is expected for a vanished device
    assert device.calls[-1] == "close"


@pytest.mark.hardware
def test_wait_for_key_press_identifies_the_device():
    """`inpmap input-config` identification, with a synthetic gamepad.

    The device cannot be grabbed (identification reads it ungrabbed), so it
    is a gamepad: desktops ignore gamepad buttons, nothing is typed.
    """
    from inpmap.backends.linux_input import wait_for_key_press

    capabilities = {
        ecodes.EV_KEY: [ecodes.BTN_SOUTH, ecodes.BTN_EAST],
        ecodes.EV_ABS: [
            (ecodes.ABS_X, evdev.AbsInfo(0, -32768, 32767, 16, 128, 0)),
            (ecodes.ABS_Y, evdev.AbsInfo(0, -32768, 32767, 16, 128, 0)),
        ],
    }
    pad = UInput(capabilities, name="InpMap Test Identify Pad", phys="pytest-identify")
    other = UInput(capabilities, name="InpMap Test Identify Other", phys="pytest-identify-2")
    try:
        paths = [pad.device.path, other.device.path, "/dev/input/does-not-exist"]
        time.sleep(0.3)  # let udev apply permissions to the new nodes

        def press_later():
            time.sleep(0.3)
            other.write(ecodes.EV_KEY, ecodes.BTN_EAST, 0)  # a release does not count
            other.syn()
            time.sleep(0.1)
            pad.write(ecodes.EV_KEY, ecodes.BTN_SOUTH, 1)
            pad.write(ecodes.EV_KEY, ecodes.BTN_SOUTH, 0)
            pad.syn()

        threading.Thread(target=press_later, daemon=True).start()
        found, failed = wait_for_key_press(paths, timeout=5)
        assert found == pad.device.path
        assert failed == ["/dev/input/does-not-exist"]
        assert wait_for_key_press(paths[:2], timeout=0.2) == (None, [])
    finally:
        pad.close()
        other.close()


PAD_NAME = "InpMap Test Synthetic Axis Pad"


def synthetic_pad() -> UInput:
    stick = evdev.AbsInfo(0, -32768, 32767, 16, 128, 0)
    return UInput(
        {
            ecodes.EV_KEY: [ecodes.BTN_SOUTH, ecodes.BTN_EAST],
            ecodes.EV_ABS: [
                (ecodes.ABS_X, stick),
                (ecodes.ABS_Y, stick),
                (ecodes.ABS_RZ, evdev.AbsInfo(0, 0, 255, 0, 0, 0)),
                (ecodes.ABS_HAT0Y, evdev.AbsInfo(0, -1, 1, 0, 0, 0)),
            ],
        },
        name=PAD_NAME,
        phys="pytest-axis-pad",
    )


def emit_abs(uinput: UInput, code: int, value: int) -> None:
    uinput.write(ecodes.EV_ABS, code, value)
    uinput.syn()


def read_abs_events(device: InputDevice, timeout: float = 0.5):
    events = []
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        ready, _, _ = select.select([device.fd], [], [], deadline - time.monotonic())
        if ready:
            events += [(e.code, e.value) for e in device.read() if e.type == ecodes.EV_ABS]
    return events


@pytest.mark.hardware
def test_axis_thresholds_through_runtime():
    """R2 and D-pad up of a synthetic gamepad drive keys; mapped axes are suppressed."""
    from inpmap.dsl.compiler import compile_text

    config = compile_text(
        f'version 1\ninput pad {{ name = "{PAD_NAME}"; to = own }}\n'
        'output keyboard { type = keyboard; name = "InpMap Test Axis Keyboard" }\n'
        "map pad.ABS_RZ above 0.5 { hold KEY_SPACE }\n"
        "map pad.ABS_HAT0Y below -0.5 { hold KEY_UP }\n",
        "axis-test.inpmap",
    ).config
    pad = synthetic_pad()
    stop = threading.Event()
    result: dict = {}
    grabbed: list[InputDevice] = []

    def run():
        try:
            result["reason"] = Runtime(config, LinuxInputBackend(), output_backend()).run(
                stop, timeout=20
            )
        except BaseException as exc:  # reported by the main thread
            result["error"] = exc

    thread = threading.Thread(target=run, daemon=True)
    try:
        thread.start()
        for name in ("InpMap Test Axis Keyboard", forward_name(PAD_NAME)):
            device = find_device(name)
            device.grab()
            grabbed.append(device)
        vkbd, forwarder = grabbed
        time.sleep(0.3)
        assert "error" not in result, result.get("error")

        emit_abs(pad, ecodes.ABS_RZ, 200)  # 0.78: pressed
        emit_abs(pad, ecodes.ABS_RZ, 120)  # 0.47: within the hysteresis, still held
        emit_abs(pad, ecodes.ABS_RZ, 0)  # released
        emit_abs(pad, ecodes.ABS_HAT0Y, -1)  # D-pad up
        emit_abs(pad, ecodes.ABS_HAT0Y, 0)
        emit_abs(pad, ecodes.ABS_X, 12000)  # not mapped: passes through

        assert read_key_events(vkbd, 4) == [
            (ecodes.KEY_SPACE, 1),
            (ecodes.KEY_SPACE, 0),
            (ecodes.KEY_UP, 1),
            (ecodes.KEY_UP, 0),
        ]
        forwarded = read_abs_events(forwarder)
        assert (ecodes.ABS_X, 12000) in forwarded
        assert all(code not in (ecodes.ABS_RZ, ecodes.ABS_HAT0Y) for code, _ in forwarded)
    finally:
        stop.set()
        thread.join(timeout=5)
        for device in grabbed:
            try:
                device.ungrab()
            except OSError:
                pass
            device.close()
        pad.close()
    assert result.get("reason") is StopReason.STOPPED, result.get("error")


@pytest.mark.hardware
def test_monitor_axes_shows_live_values():
    from inpmap.backends.linux_input import monitor_axes
    from inpmap.models import AxisThreshold

    pad = synthetic_pad()
    shown: list[str] = []
    try:
        time.sleep(0.3)  # udev permissions for the new node

        def move():
            time.sleep(0.3)
            emit_abs(pad, ecodes.ABS_RZ, 200)

        threading.Thread(target=move, daemon=True).start()
        spec = InputDeviceSpec(id="pad", name=PAD_NAME)
        threshold = AxisThreshold(ecodes.ABS_RZ, True, 0.5)
        notes = monitor_axes(
            {"pad": spec},
            {("pad", ecodes.ABS_RZ): [("r2", threshold)]},
            lambda rows, changed: shown.extend(rows[i].text() for i in sorted(changed)),
            timeout=1.0,
        )
    finally:
        pad.close()
    assert notes == []
    assert any(line.startswith("pad        ABS_RZ       +0.00") for line in shown)
    assert any("+0.78" in line and "r2: above 0.5 ON" in line for line in shown)
    assert any(line.startswith("pad        ABS_HAT0Y") for line in shown)


@pytest.mark.hardware
def test_listen_reports_buttons_and_axes():
    """`inpmap detect`'s listener, with a synthetic gamepad read without grabbing."""
    from inpmap.backends.linux_input import listen

    pad = synthetic_pad()
    keys, axes = [], []
    try:
        time.sleep(0.3)  # udev permissions for the new node

        def press_later():
            time.sleep(0.3)
            emit(pad, ecodes.BTN_EAST, 1)
            emit(pad, ecodes.BTN_EAST, 0)
            emit_abs(pad, ecodes.ABS_RZ, 255)

        threading.Thread(target=press_later, daemon=True).start()
        notes = listen(
            [pad.device.path, "/dev/input/does-not-exist"],
            lambda path, name, code, pressed: keys.append((name, code, pressed)),
            lambda path, name, code, value: axes.append((code, value)),
            timeout=1.0,
        )
    finally:
        pad.close()
    assert notes == [
        "/dev/input/does-not-exist: cannot be read (see docs/installation.md, permissions)"
    ]
    assert keys == [(PAD_NAME, ecodes.BTN_EAST, True), (PAD_NAME, ecodes.BTN_EAST, False)]
    assert axes == [(ecodes.ABS_RZ, 1.0)]


# -- routing: unmapped input goes to the outputs (configuration.md §3.4) ----

ROUTED_KEYBOARD = "InpMap Test Routed Keyboard"
ROUTED_GAMEPAD = "InpMap Test Routed Gamepad"


@contextlib.contextmanager
def running(config, grab_names):
    """Run the runtime in a thread; grab the named devices before anything is emitted."""
    stop = threading.Event()
    result: dict = {}
    grabbed: list[InputDevice] = []

    def run():
        try:
            runtime = Runtime(config, LinuxInputBackend(), output_backend())
            result["reason"] = runtime.run(stop, timeout=20)
        except BaseException as exc:  # reported by the main thread
            result["error"] = exc

    thread = threading.Thread(target=run, daemon=True)
    try:
        thread.start()
        for name in grab_names:
            device = find_device(name)
            device.grab()
            grabbed.append(device)
        time.sleep(0.3)  # the runtime grabs the physical devices meanwhile
        assert "error" not in result, result.get("error")
        yield grabbed
    finally:
        stop.set()
        thread.join(timeout=5)
        for device in grabbed:
            with contextlib.suppress(OSError):
                device.ungrab()
            device.close()
    assert result.get("reason") is StopReason.STOPPED, result.get("error")


def routed_config(extra=""):
    from inpmap.dsl.compiler import compile_text

    return compile_text(
        f'version 1\ninput kbd {{ name = "{PHYSICAL_NAME}" }}\n'
        f'input pad {{ name = "{PAD_NAME}" }}\n'
        f'output keyboard {{ type = keyboard; name = "{ROUTED_KEYBOARD}" }}\n'
        f'output gamepad {{ type = gamepad; name = "{ROUTED_GAMEPAD}" }}\n'
        "map kbd.KEY_X { hold KEY_Y }\nmap pad.BTN_EAST { hold KEY_ESC }\n" + extra,
        "routing-test.inpmap",
    ).config


def read_all_events(device: InputDevice, timeout: float = 0.5):
    events = []
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if select.select([device.fd], [], [], deadline - time.monotonic())[0]:
            events += list(device.read())
    return events


def device_exists(name: str) -> bool:
    for path in list_devices():
        device = InputDevice(path)
        found = device.name == name
        device.close()
        if found:
            return True
    return False


@pytest.mark.hardware
def test_routed_keyboard_and_pad_come_out_of_the_outputs_only():
    keyboard = UInput(
        {ecodes.EV_KEY: [ecodes.KEY_X, ecodes.KEY_A, ecodes.KEY_ESC]},
        name=PHYSICAL_NAME,
        phys="pytest-physical",
    )
    pad = synthetic_pad()
    try:
        with running(routed_config(), (ROUTED_KEYBOARD, ROUTED_GAMEPAD)) as (vkbd, vpad):
            # No pass-through devices: everything goes to the two outputs.
            assert not device_exists(forward_name(PHYSICAL_NAME))
            assert not device_exists(forward_name(PAD_NAME))
            emit(keyboard, ecodes.KEY_A, 1)
            emit(keyboard, ecodes.KEY_A, 0)
            emit(keyboard, ecodes.KEY_X, 1)
            emit(keyboard, ecodes.KEY_X, 0)
            emit(pad, ecodes.BTN_SOUTH, 1)
            emit(pad, ecodes.BTN_SOUTH, 0)
            emit_abs(pad, ecodes.ABS_X, 16384)
            emit_abs(pad, ecodes.ABS_RZ, 255)
            emit_abs(pad, ecodes.ABS_HAT0Y, -1)
            assert read_key_events(vkbd, 4) == [
                (ecodes.KEY_A, 1),
                (ecodes.KEY_A, 0),
                (ecodes.KEY_Y, 1),
                (ecodes.KEY_Y, 0),
            ]
            events = read_all_events(vpad)
            keys = [(e.code, e.value) for e in events if e.type == ecodes.EV_KEY]
            axes = [(e.code, e.value) for e in events if e.type == ecodes.EV_ABS]
            # The D-pad axis arrives as the D-pad button (SDL uses only those).
            assert keys == [(ecodes.BTN_SOUTH, 1), (ecodes.BTN_SOUTH, 0), (ecodes.BTN_DPAD_UP, 1)]
            assert axes == [(ecodes.ABS_X, 16384), (ecodes.ABS_RZ, 255)]
    finally:
        keyboard.close()
        pad.close()


@pytest.mark.hardware
def test_mouse_part_goes_to_a_pass_through_device_with_only_the_mouse():
    combo = UInput(
        {
            ecodes.EV_KEY: [ecodes.KEY_X, ecodes.KEY_A, ecodes.BTN_LEFT],
            ecodes.EV_REL: [ecodes.REL_X, ecodes.REL_Y],
        },
        name=PHYSICAL_NAME,
        phys="pytest-physical",
    )
    pad = synthetic_pad()
    names = (ROUTED_KEYBOARD, ROUTED_GAMEPAD, forward_name(PHYSICAL_NAME))
    try:
        with running(routed_config(), names) as (vkbd, _vpad, passthrough):
            caps = passthrough.capabilities()
            assert caps[ecodes.EV_KEY] == [ecodes.BTN_LEFT]
            assert sorted(caps[ecodes.EV_REL]) == [ecodes.REL_X, ecodes.REL_Y]
            combo.write(ecodes.EV_REL, ecodes.REL_X, 7)
            combo.syn()
            emit(combo, ecodes.BTN_LEFT, 1)
            emit(combo, ecodes.BTN_LEFT, 0)
            emit(combo, ecodes.KEY_A, 1)
            emit(combo, ecodes.KEY_A, 0)
            assert read_key_events(passthrough, 2) == [(ecodes.BTN_LEFT, 1), (ecodes.BTN_LEFT, 0)]
            assert read_key_events(vkbd, 2) == [(ecodes.KEY_A, 1), (ecodes.KEY_A, 0)]
    finally:
        combo.close()
        pad.close()


@pytest.mark.hardware
def test_leds_of_the_keyboard_output_reach_the_routed_physical_keyboard():
    keyboard = UInput(
        {ecodes.EV_KEY: [ecodes.KEY_X, ecodes.KEY_ESC], ecodes.EV_LED: [ecodes.LED_CAPSL]},
        name=PHYSICAL_NAME,
        phys="pytest-physical",
        max_effects=0,
    )
    pad = synthetic_pad()
    try:
        with running(routed_config(), (ROUTED_KEYBOARD, ROUTED_GAMEPAD)) as (vkbd, _vpad):
            while select.select([keyboard.fd], [], [], 0.2)[0]:
                list(keyboard.read())  # LED writes made before the test
            vkbd.set_led(ecodes.LED_CAPSL, 1)  # what the desktop does on Caps Lock
            leds = []
            deadline = time.monotonic() + 2.0
            while (ecodes.LED_CAPSL, 1) not in leds and time.monotonic() < deadline:
                if select.select([keyboard.fd], [], [], 0.2)[0]:
                    leds += [(e.code, e.value) for e in keyboard.read() if e.type == ecodes.EV_LED]
            assert (ecodes.LED_CAPSL, 1) in leds
    finally:
        keyboard.close()
        pad.close()


@pytest.mark.hardware
def test_refused_device_is_never_grabbed():
    from inpmap.dsl.compiler import compile_text
    from inpmap.routing import InputRefused

    config = compile_text(
        f'version 1\ninput kbd {{ name = "{PHYSICAL_NAME}" }}\n'
        f'output gamepad {{ type = gamepad; name = "{ROUTED_GAMEPAD}" }}\n'
        "map KEY_X { hold BTN_SOUTH }\n",
        "refused.inpmap",
    ).config
    keyboard = UInput({ecodes.EV_KEY: [ecodes.KEY_X, ecodes.KEY_A]}, name=PHYSICAL_NAME)
    try:
        with pytest.raises(InputRefused, match="no keyboard output"):
            Runtime(config, LinuxInputBackend(), output_backend()).run(threading.Event(), timeout=5)
        device = find_device(PHYSICAL_NAME)
        device.grab()  # would fail with EBUSY if InpMap still held it
        device.ungrab()
        device.close()
    finally:
        keyboard.close()

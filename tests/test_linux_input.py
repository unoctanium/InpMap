"""Linux input backend tests.

The ``hardware`` test runs the real runtime against a *synthetic* physical
keyboard created via uinput. It grabs every output and forwarding device
itself before any event is emitted, so nothing reaches the desktop, and it
never touches real hardware.
"""

import select
import threading
import time

import pytest

evdev = pytest.importorskip("evdev")
from evdev import InputDevice, UInput, ecodes, list_devices  # noqa: E402

from inpmap.backends.linux import LinuxOutputBackend  # noqa: E402
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
CONFIG = parse_config(
    {
        "version": 1,
        "inputs": {"kbd": {"name": PHYSICAL_NAME}},
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
            runtime = Runtime(CONFIG, LinuxInputBackend(), LinuxOutputBackend())
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
            runtime = Runtime(
                CONFIG, LinuxInputBackend(), LinuxOutputBackend(), reconnect_interval=0.2
            )
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

    def read(self):
        if self._read_error:
            raise self._read_error
        if not self._events:
            raise BlockingIOError
        events, self._events = self._events, []
        return iter(events)

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
        StubEvent(ecodes.EV_SYN, ecodes.SYN_DROPPED, 0),
        StubEvent(ecodes.EV_SYN, ecodes.SYN_REPORT, 0),
    ]
    source, _, _ = make_source(events=events)
    result = source.read()
    assert [event for event, _ in result] == [
        None,
        InputEvent("kbd", ecodes.KEY_X, KeyAction.PRESS),
        InputEvent("kbd", ecodes.KEY_X, KeyAction.REPEAT),
        None,  # SYN_REPORT; SYN_DROPPED is not passed on
    ]
    assert source.read() == []  # nothing pending


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

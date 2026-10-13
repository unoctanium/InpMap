"""Linux backend tests.

Unmarked tests only inspect capability sets (no devices). Tests marked
``hardware`` create real uinput devices; they grab each virtual device's own
event node before emitting, so no event reaches the desktop.
Run them with: pytest -m hardware
"""

import select
import time

import pytest

evdev = pytest.importorskip("evdev")
from evdev import InputDevice, ecodes  # noqa: E402

from inpmap.backends.linux import (  # noqa: E402
    GAMEPAD_BUTTONS,
    KEYBOARD_KEYS,
    LinuxOutputBackend,
    capabilities,
)
from inpmap.config import parse_config  # noqa: E402
from inpmap.models import OutputDeviceSpec, OutputKind  # noqa: E402
from inpmap.output import OutputManager  # noqa: E402

# -- capability sets (no devices) -----------------------------------------


def test_keyboard_has_all_basic_keys_and_no_buttons():
    caps = capabilities(OutputKind.KEYBOARD, frozenset())
    keys = set(caps[ecodes.EV_KEY])
    # udev sets ID_INPUT_KEYBOARD only if codes 1..31 are all present.
    assert set(range(1, 32)) <= keys
    assert not any(ecodes.BTN_MISC <= code < ecodes.KEY_OK for code in keys)
    assert set(caps) == {ecodes.EV_KEY}


def test_gamepad_has_standard_buttons_axes_and_no_keys():
    caps = capabilities(OutputKind.GAMEPAD, frozenset())
    keys = set(caps[ecodes.EV_KEY])
    assert ecodes.BTN_SOUTH in keys
    assert keys.isdisjoint(KEYBOARD_KEYS)
    axes = {code for code, _ in caps[ecodes.EV_ABS]}
    assert {ecodes.ABS_X, ecodes.ABS_Y, ecodes.ABS_RX, ecodes.ABS_RY} <= axes


def test_mapped_codes_are_always_declared():
    happy = ecodes.BTN_TRIGGER_HAPPY1
    caps = capabilities(OutputKind.GAMEPAD, frozenset({happy}))
    assert happy in caps[ecodes.EV_KEY]
    assert happy not in GAMEPAD_BUTTONS


# -- real uinput devices --------------------------------------------------

CONFIG = parse_config(
    {
        "version": 1,
        "inputs": {"kbd": {"name": "unused"}},
        "outputs": {
            "keyboard": {"type": "keyboard", "name": "InpMap Test Keyboard"},
            "gamepad": {"type": "gamepad", "name": "InpMap Test Gamepad"},
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


def read_key_events(device: InputDevice, count: int, timeout: float = 2.0):
    """Read ``count`` EV_KEY events as (code, value) pairs."""
    events = []
    deadline = time.monotonic() + timeout
    while len(events) < count:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        ready, _, _ = select.select([device.fd], [], [], remaining)
        if ready:
            events += [(e.code, e.value) for e in device.read() if e.type == ecodes.EV_KEY]
    return events


@pytest.fixture
def grabbed():
    """Open a device node and grab it so its events reach only the test."""
    opened = []

    def open_grabbed(path):
        device = InputDevice(path)
        device.grab()
        opened.append(device)
        return device

    yield open_grabbed
    for device in opened:
        try:
            device.ungrab()
        except OSError:
            pass  # the virtual device is already gone
        device.close()


@pytest.mark.hardware
def test_devices_are_created_with_expected_identity_and_capabilities():
    with OutputManager(LinuxOutputBackend(), CONFIG) as outputs:
        for device_id, device in outputs.devices.items():
            node = InputDevice(device.node)
            try:
                assert node.name == CONFIG.outputs[device_id].name
                caps = node.capabilities()
                # Unanswered rumble uploads would block games (see linux.py).
                assert ecodes.EV_FF not in caps
                if device_id == "keyboard":
                    assert ecodes.KEY_Y in caps[ecodes.EV_KEY]
                    assert ecodes.EV_ABS not in caps
                else:
                    assert ecodes.BTN_SOUTH in caps[ecodes.EV_KEY]
                    assert ecodes.KEY_Y not in caps[ecodes.EV_KEY]
                    assert ecodes.EV_ABS in caps
            finally:
                node.close()


@pytest.mark.hardware
def test_press_release_reach_virtual_devices(grabbed):
    with OutputManager(LinuxOutputBackend(), CONFIG) as outputs:
        keyboard = grabbed(outputs.devices["keyboard"].node)
        gamepad = grabbed(outputs.devices["gamepad"].node)
        outputs.press("keyboard", ecodes.KEY_Y)
        outputs.press("gamepad", ecodes.BTN_SOUTH)
        outputs.release("keyboard", ecodes.KEY_Y)
        outputs.release("gamepad", ecodes.BTN_SOUTH)
        assert read_key_events(keyboard, 2) == [(ecodes.KEY_Y, 1), (ecodes.KEY_Y, 0)]
        assert read_key_events(gamepad, 2) == [(ecodes.BTN_SOUTH, 1), (ecodes.BTN_SOUTH, 0)]


@pytest.mark.hardware
def test_release_all_reaches_devices_and_close_removes_them(grabbed):
    # Events still queued when a device is destroyed cannot be read (evdev
    # returns ENODEV), so the releases are checked before closing. That
    # close() calls release_all() first is covered by the fake-backend tests.
    outputs = OutputManager(LinuxOutputBackend(), CONFIG)
    outputs.open()
    try:
        keyboard_node = outputs.devices["keyboard"].node
        keyboard = grabbed(keyboard_node)
        gamepad = grabbed(outputs.devices["gamepad"].node)
        outputs.press("keyboard", ecodes.KEY_Y)
        outputs.press("gamepad", ecodes.BTN_SOUTH)
        outputs.release_all()
        assert read_key_events(keyboard, 2) == [(ecodes.KEY_Y, 1), (ecodes.KEY_Y, 0)]
        assert read_key_events(gamepad, 2) == [(ecodes.BTN_SOUTH, 1), (ecodes.BTN_SOUTH, 0)]
    finally:
        outputs.close()
    # Device nodes disappear asynchronously after destruction.
    deadline = time.monotonic() + 2.0
    while time.monotonic() < deadline:
        try:
            InputDevice(keyboard_node).close()
        except OSError:
            break
        time.sleep(0.05)
    else:
        pytest.fail(f"{keyboard_node} still exists after close")


def test_missing_uinput_node_gives_actionable_error():
    # evdev checks the node before creating anything, so no device is made.
    from inpmap.output import OutputError

    backend = LinuxOutputBackend(devnode="/dev/does-not-exist")
    spec = OutputDeviceSpec(id="k", kind=OutputKind.KEYBOARD, name="InpMap Test")
    with pytest.raises(OutputError, match="Check that /dev/does-not-exist exists"):
        backend.create(spec, frozenset())

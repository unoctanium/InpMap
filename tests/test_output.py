import pytest
from fakes import FakeOutputBackend

from inpmap import codes
from inpmap.codes import code_from_name
from inpmap.config import parse_config
from inpmap.models import TouchPoint
from inpmap.output import OutputError, OutputManager

KEY_Y = code_from_name("KEY_Y")
KEY_Z = code_from_name("KEY_Z")
BTN_FACE_DOWN = code_from_name("BTN_FACE_DOWN")

CONFIG = parse_config(
    {
        "version": 1,
        "inputs": {"kbd": {"name": "Kbd"}},
        "outputs": {
            "vkbd": {"type": "keyboard"},
            "pad": {"type": "gamepad"},
        },
        "mappings": [
            {
                "id": "x",
                "input": {"device": "kbd", "type": "key", "code": "KEY_X"},
                "outputs": [
                    {"device": "vkbd", "type": "key", "code": "KEY_Y"},
                    {"device": "pad", "type": "button", "code": "BTN_FACE_DOWN"},
                ],
            },
            {
                "id": "c",
                "input": {"device": "kbd", "type": "key", "code": "KEY_C"},
                "outputs": [{"device": "vkbd", "type": "key", "code": "KEY_Z"}],
            },
        ],
    }
)


@pytest.fixture
def backend():
    return FakeOutputBackend()


def test_open_creates_devices_with_needed_codes(backend):
    with OutputManager(backend, CONFIG):
        # The fixed set of each output plus what mappings send (configuration.md §3.3).
        assert {KEY_Y, KEY_Z} <= backend.created["vkbd"].key_codes
        assert backend.created["vkbd"].key_codes == codes.KEYBOARD_OUTPUT_KEYS
        assert backend.created["pad"].key_codes == codes.GAMEPAD_OUTPUT_BUTTONS
    assert all(device.closed for device in backend.created.values())


def test_press_and_release_route_to_device(backend):
    with OutputManager(backend, CONFIG) as outputs:
        outputs.press("vkbd", KEY_Y)
        outputs.press("pad", BTN_FACE_DOWN)
        assert outputs.held("vkbd") == {KEY_Y}
        outputs.release("vkbd", KEY_Y)
        outputs.release("pad", BTN_FACE_DOWN)
        assert outputs.held("vkbd") == set()
    assert backend.created["vkbd"].events == [(KEY_Y, True), (KEY_Y, False)]
    assert backend.created["pad"].events == [(BTN_FACE_DOWN, True), (BTN_FACE_DOWN, False)]


def test_redundant_transitions_are_ignored(backend):
    with OutputManager(backend, CONFIG) as outputs:
        outputs.release("vkbd", KEY_Y)
        outputs.press("vkbd", KEY_Y)
        outputs.press("vkbd", KEY_Y)
        outputs.release("vkbd", KEY_Y)
        outputs.release("vkbd", KEY_Y)
    assert backend.created["vkbd"].events == [(KEY_Y, True), (KEY_Y, False)]


def test_close_releases_held_codes_before_destroying(backend):
    outputs = OutputManager(backend, CONFIG)
    outputs.open()
    outputs.press("vkbd", KEY_Y)
    outputs.press("vkbd", KEY_Z)
    outputs.press("pad", BTN_FACE_DOWN)
    outputs.close()
    assert backend.created["vkbd"].events[-2:] == [(KEY_Y, False), (KEY_Z, False)]
    assert backend.created["pad"].events[-1] == (BTN_FACE_DOWN, False)
    assert all(device.closed for device in backend.created.values())


def test_exception_inside_context_still_releases(backend):
    with pytest.raises(RuntimeError, match="boom"), OutputManager(backend, CONFIG) as outputs:
        outputs.press("pad", BTN_FACE_DOWN)
        raise RuntimeError("boom")
    assert backend.created["pad"].events[-1] == (BTN_FACE_DOWN, False)
    assert backend.created["pad"].closed


def test_create_failure_closes_already_created_devices(backend):
    backend.fail_on = "pad"
    outputs = OutputManager(backend, CONFIG)
    with pytest.raises(OutputError, match="simulated create failure"):
        outputs.open()
    assert backend.created["vkbd"].closed
    assert outputs.devices == {}


def test_unexpected_create_error_also_cleans_up(backend):
    def explode(spec, key_codes):
        if spec.id == "pad":
            raise KeyboardInterrupt
        return FakeOutputBackend.create(backend, spec, key_codes)

    backend.create = explode
    with pytest.raises(KeyboardInterrupt):
        OutputManager(backend, CONFIG).open()
    assert backend.created["vkbd"].closed


def test_failed_press_is_not_recorded_as_held(backend):
    with OutputManager(backend, CONFIG) as outputs:
        backend.created["vkbd"].fail_writes = True
        with pytest.raises(OutputError):
            outputs.press("vkbd", KEY_Y)
        assert outputs.held("vkbd") == set()
        backend.created["vkbd"].fail_writes = False


def test_release_failure_on_one_device_does_not_block_others(backend):
    outputs = OutputManager(backend, CONFIG)
    outputs.open()
    outputs.press("vkbd", KEY_Y)
    outputs.press("pad", BTN_FACE_DOWN)
    backend.created["vkbd"].fail_writes = True
    with pytest.raises(OutputError, match="vkbd KEY_Y"):
        outputs.close()
    assert backend.created["pad"].events[-1] == (BTN_FACE_DOWN, False)
    assert all(device.closed for device in backend.created.values())


def test_close_failure_reported_after_closing_all(backend):
    outputs = OutputManager(backend, CONFIG)
    outputs.open()
    backend.created["vkbd"].fail_close = True
    with pytest.raises(OutputError, match="closing 'vkbd'"):
        outputs.close()
    assert backend.created["pad"].closed


def test_write_to_unknown_device_raises(backend):
    with OutputManager(backend, CONFIG) as outputs, pytest.raises(OutputError):
        outputs.press("nope", KEY_Y)


def test_open_twice_rejected(backend):
    with OutputManager(backend, CONFIG) as outputs, pytest.raises(RuntimeError):
        outputs.open()


# -- axes -------------------------------------------------------------------------

ABS_X, ABS_RZ = 0x00, 0x05


def test_set_axis_tracks_value_and_skips_unchanged(backend):
    with OutputManager(backend, CONFIG) as outputs:
        outputs.set_axis("pad", ABS_X, 0.5)
        outputs.set_axis("pad", ABS_X, 0.5)  # unchanged: not written
        assert outputs.axis("pad", ABS_X) == 0.5
        outputs.set_axis("pad", ABS_X, 0.0)
        assert outputs.axis("pad", ABS_X) == 0.0
    assert backend.created["pad"].axis_events == [(ABS_X, 0.5), (ABS_X, 0.0)]


def test_close_returns_moved_axes_to_rest(backend):
    outputs = OutputManager(backend, CONFIG)
    outputs.open()
    outputs.set_axis("pad", ABS_X, -1.0)
    outputs.set_axis("pad", ABS_RZ, 1.0)
    outputs.close()
    assert backend.created["pad"].axis_events[-2:] == [(ABS_X, 0.0), (ABS_RZ, 0.0)]


def test_axis_reset_failure_does_not_stop_key_release(backend):
    outputs = OutputManager(backend, CONFIG)
    outputs.open()
    outputs.set_axis("pad", ABS_X, 1.0)
    outputs.press("vkbd", KEY_Y)
    backend.created["pad"].fail_writes = True
    with pytest.raises(OutputError, match="pad axis 0x0"):
        outputs.close()
    assert backend.created["vkbd"].events[-1] == (KEY_Y, False)
    assert all(d.closed for d in backend.created.values())


EMULATED = parse_config(
    {
        "version": 1,
        "inputs": {"kbd": {"name": "Kbd"}},
        "outputs": {"pad": {"type": "gamepad", "emulate": "dualsense-edge"}},
        "mappings": [
            {
                "id": "a",
                "input": {"device": "kbd", "type": "key", "code": "KEY_A"},
                "outputs": [{"device": "pad", "type": "button", "code": "BTN_FACE_RIGHT"}],
            }
        ],
    }
)


def test_emulated_controller_gets_the_touchpad_click(backend):
    with OutputManager(backend, EMULATED):
        keys = backend.created["pad"].key_codes
    assert keys == codes.DUALSENSE_EDGE_BUTTONS | {codes.TOUCHPAD_CLICK}


def test_close_lifts_fingers_left_on_a_touchpad(backend):
    manager = OutputManager(backend, EMULATED)
    manager.open()
    point = TouchPoint(0, 0.5, 0.5)
    manager.set_touch("pad", (point, None))
    manager.close()
    assert backend.created["pad"].touch_events == [(point, None), ()]


def test_lifted_fingers_are_not_lifted_again(backend):
    manager = OutputManager(backend, EMULATED)
    manager.open()
    manager.set_touch("pad", (TouchPoint(0, 0.5, 0.5), None))
    manager.set_touch("pad", (None, None))
    manager.close()
    assert len(backend.created["pad"].touch_events) == 2


def test_touch_on_unknown_device_raises(backend):
    with OutputManager(backend, EMULATED) as manager, pytest.raises(OutputError):
        manager.set_touch("nope", ())

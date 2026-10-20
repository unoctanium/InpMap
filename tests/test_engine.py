import pytest
from fakes import FakeOutputBackend

from inpmap.codes import code_from_name as c
from inpmap.config import parse_config
from inpmap.engine import MappingEngine
from inpmap.models import InputEvent, KeyAction
from inpmap.output import OutputError, OutputManager

PRESS, RELEASE, REPEAT = KeyAction.PRESS, KeyAction.RELEASE, KeyAction.REPEAT


def key(name, device="vkbd"):
    return {"device": device, "type": "key", "code": name}


def button(name, device="vpad"):
    return {"device": device, "type": "button", "code": name}


CONFIG = parse_config(
    {
        "version": 1,
        "inputs": {"kbd": {"name": "Kbd"}, "pad": {"name": "Pad"}},
        "outputs": {"vkbd": {"type": "keyboard"}, "vpad": {"type": "gamepad"}},
        "mappings": [
            {
                "id": "x",
                "input": key("KEY_X", "kbd"),
                "outputs": [key("KEY_Y"), button("BTN_FACE_DOWN")],
            },
            {"id": "c", "input": key("KEY_C", "kbd"), "outputs": [key("KEY_Y")]},
            {"id": "z", "input": key("KEY_Z", "kbd"), "outputs": [button("BTN_START")]},
            {"id": "pad-east", "input": button("BTN_FACE_RIGHT", "pad"), "outputs": [key("KEY_Y")]},
        ],
    }
)


class RecordingSink:
    def __init__(self):
        self.events = []
        self.axes = []

    def set_axis(self, device_id, code, value):
        self.axes.append((device_id, code, value))

    def press(self, device_id, code):
        self.events.append((device_id, code, True))

    def release(self, device_id, code):
        self.events.append((device_id, code, False))


@pytest.fixture
def sink():
    return RecordingSink()


@pytest.fixture
def engine(sink):
    return MappingEngine(CONFIG, sink)


def ev(device, name, action):
    return InputEvent(device, c(name), action)


# -- matching ------------------------------------------------------------


def test_unmapped_event_is_not_handled(engine, sink):
    assert engine.handle(ev("kbd", "KEY_A", PRESS)) is False
    assert sink.events == []


def test_same_code_on_other_device_is_not_mapped(engine, sink):
    assert engine.handle(ev("pad", "KEY_X", PRESS)) is False
    assert engine.is_mapped("kbd", c("KEY_X"))
    assert not engine.is_mapped("pad", c("KEY_X"))
    assert sink.events == []


def test_press_activates_all_outputs_and_is_consumed(engine, sink):
    assert engine.handle(ev("kbd", "KEY_X", PRESS)) is True
    assert sink.events == [("vkbd", c("KEY_Y"), True), ("vpad", c("BTN_FACE_DOWN"), True)]
    assert engine.active_rules() == ["x"]


def test_release_releases_all_outputs(engine, sink):
    engine.handle(ev("kbd", "KEY_X", PRESS))
    assert engine.handle(ev("kbd", "KEY_X", RELEASE)) is True
    assert sink.events[2:] == [("vkbd", c("KEY_Y"), False), ("vpad", c("BTN_FACE_DOWN"), False)]
    assert engine.active_rules() == []
    assert engine.held_outputs() == set()


def test_repeat_is_consumed_without_output(engine, sink):
    engine.handle(ev("kbd", "KEY_X", PRESS))
    for _ in range(5):
        assert engine.handle(ev("kbd", "KEY_X", REPEAT)) is True
    assert len(sink.events) == 2


def test_repeat_without_press_is_passed_through(engine, sink):
    # A press can pass through deliberately (no mapping fits the held
    # modifiers); its repeats and release must then pass through as well.
    assert engine.handle(ev("kbd", "KEY_X", REPEAT)) is False
    assert sink.events == []


def test_duplicate_press_is_ignored(engine, sink):
    engine.handle(ev("kbd", "KEY_X", PRESS))
    engine.handle(ev("kbd", "KEY_X", PRESS))
    engine.handle(ev("kbd", "KEY_X", RELEASE))
    assert [pressed for _, _, pressed in sink.events] == [True, True, False, False]


def test_release_without_press_is_passed_through(engine, sink):
    # Same reason as above: otherwise the desktop would keep a passed-through
    # press forever (stuck key).
    assert engine.handle(ev("kbd", "KEY_X", RELEASE)) is False
    assert sink.events == []


def test_independent_rules_interleave(engine, sink):
    engine.handle(ev("kbd", "KEY_X", PRESS))
    engine.handle(ev("kbd", "KEY_Z", PRESS))
    engine.handle(ev("kbd", "KEY_X", RELEASE))
    assert engine.held_outputs() == {("vpad", c("BTN_START"))}
    engine.handle(ev("kbd", "KEY_Z", RELEASE))
    assert engine.held_outputs() == set()


# -- shared outputs (reference counting) ---------------------------------


def test_shared_output_stays_held_until_last_input_released(engine, sink):
    engine.handle(ev("kbd", "KEY_X", PRESS))  # KEY_Y + BTN_FACE_DOWN
    engine.handle(ev("kbd", "KEY_C", PRESS))  # KEY_Y again
    engine.handle(ev("kbd", "KEY_X", RELEASE))
    # BTN_FACE_DOWN released, KEY_Y still held by "c"
    assert sink.events == [
        ("vkbd", c("KEY_Y"), True),
        ("vpad", c("BTN_FACE_DOWN"), True),
        ("vpad", c("BTN_FACE_DOWN"), False),
    ]
    engine.handle(ev("kbd", "KEY_C", RELEASE))
    assert sink.events[-1] == ("vkbd", c("KEY_Y"), False)


def test_shared_output_across_input_devices(engine, sink):
    engine.handle(ev("pad", "BTN_FACE_RIGHT", PRESS))
    engine.handle(ev("kbd", "KEY_C", PRESS))
    engine.handle(ev("pad", "BTN_FACE_RIGHT", RELEASE))
    assert sink.events == [("vkbd", c("KEY_Y"), True)]
    engine.handle(ev("kbd", "KEY_C", RELEASE))
    assert sink.events[-1] == ("vkbd", c("KEY_Y"), False)


def test_alias_codes_refer_to_the_same_input(sink):
    # BTN_FACE_DOWN and BTN_FACE_DOWN are one code; an event for either matches.
    config = parse_config(
        {
            "version": 1,
            "inputs": {"pad": {"name": "Pad"}},
            "outputs": {"vkbd": {"type": "keyboard"}},
            "mappings": [
                {"id": "a", "input": button("BTN_FACE_DOWN", "pad"), "outputs": [key("KEY_ENTER")]}
            ],
        }
    )
    engine = MappingEngine(config, sink)
    assert engine.handle(ev("pad", "BTN_FACE_DOWN", PRESS)) is True
    assert sink.events == [("vkbd", c("KEY_ENTER"), True)]


# -- device loss and shutdown ----------------------------------------------


def test_release_device_releases_only_its_inputs(engine, sink):
    engine.handle(ev("kbd", "KEY_X", PRESS))
    engine.handle(ev("pad", "BTN_FACE_RIGHT", PRESS))
    engine.release_device("kbd")
    # BTN_FACE_DOWN released; KEY_Y still held by the pad's rule
    assert engine.held_outputs() == {("vkbd", c("KEY_Y"))}
    assert engine.active_rules() == ["pad-east"]
    engine.release_device("pad")
    assert engine.held_outputs() == set()
    assert sink.events[-1] == ("vkbd", c("KEY_Y"), False)


def test_release_all(engine, sink):
    for name in ("KEY_X", "KEY_C", "KEY_Z"):
        engine.handle(ev("kbd", name, PRESS))
    engine.release_all()
    assert engine.held_outputs() == set()
    assert engine.active_rules() == []
    pressed = {(d, code) for d, code, p in sink.events if p}
    released = {(d, code) for d, code, p in sink.events if not p}
    assert pressed == released


def test_input_pressed_again_after_device_loss_works(engine, sink):
    engine.handle(ev("kbd", "KEY_X", PRESS))
    engine.release_device("kbd")
    engine.handle(ev("kbd", "KEY_X", RELEASE))  # stale release: ignored
    engine.handle(ev("kbd", "KEY_X", PRESS))
    assert engine.active_rules() == ["x"]
    assert sink.events.count(("vkbd", c("KEY_Y"), True)) == 2


# -- with the real OutputManager and errors --------------------------------


@pytest.fixture
def backend():
    return FakeOutputBackend()


def test_end_to_end_with_output_manager(backend):
    with OutputManager(backend, CONFIG) as outputs:
        engine = MappingEngine(CONFIG, outputs)
        engine.handle(ev("kbd", "KEY_X", PRESS))
        engine.handle(ev("kbd", "KEY_C", PRESS))
        engine.handle(ev("kbd", "KEY_X", RELEASE))
        assert outputs.held("vkbd") == {c("KEY_Y")}
        assert outputs.held("vpad") == set()
    # closed while KEY_Y was still held by "c": released on close
    assert backend.created["vkbd"].events == [(c("KEY_Y"), True), (c("KEY_Y"), False)]


def test_output_error_on_press_keeps_state_consistent(backend):
    with OutputManager(backend, CONFIG) as outputs:
        engine = MappingEngine(CONFIG, outputs)
        backend.created["vpad"].fail_writes = True
        with pytest.raises(OutputError, match="mapping 'x'.*BTN_FACE_DOWN"):
            engine.handle(ev("kbd", "KEY_X", PRESS))
        # KEY_Y was still pressed; the rule counts as active
        assert outputs.held("vkbd") == {c("KEY_Y")}
        backend.created["vpad"].fail_writes = False
        engine.handle(ev("kbd", "KEY_X", RELEASE))
        assert outputs.held("vkbd") == set()
        assert outputs.held("vpad") == set()
        assert engine.held_outputs() == set()


def test_output_error_on_release_does_not_block_other_outputs(backend):
    with OutputManager(backend, CONFIG) as outputs:
        engine = MappingEngine(CONFIG, outputs)
        engine.handle(ev("kbd", "KEY_X", PRESS))
        backend.created["vkbd"].fail_writes = True
        with pytest.raises(OutputError, match="release vkbd KEY_Y"):
            engine.handle(ev("kbd", "KEY_X", RELEASE))
        assert outputs.held("vpad") == set()  # BTN_FACE_DOWN still released
        assert engine.active_rules() == []
        backend.created["vkbd"].fail_writes = False
    # OutputManager.close() released the KEY_Y it still considered held
    assert backend.created["vkbd"].events[-1] == (c("KEY_Y"), False)


def test_release_all_continues_after_errors(backend):
    with OutputManager(backend, CONFIG) as outputs:
        engine = MappingEngine(CONFIG, outputs)
        engine.handle(ev("kbd", "KEY_X", PRESS))
        engine.handle(ev("kbd", "KEY_Z", PRESS))
        backend.created["vkbd"].fail_writes = True
        with pytest.raises(OutputError):
            engine.release_all()
        assert engine.active_rules() == []
        assert outputs.held("vpad") == set()
        backend.created["vkbd"].fail_writes = False


# -- tap outputs -----------------------------------------------------------

TAP_CONFIG = parse_config(
    {
        "version": 1,
        "inputs": {"kbd": {"name": "Kbd"}},
        "outputs": {"vkbd": {"type": "keyboard"}, "vpad": {"type": "gamepad"}},
        "mappings": [
            {
                "id": "x",
                "input": key("KEY_X", "kbd"),
                "outputs": [{**key("KEY_Y"), "mode": "tap"}, button("BTN_FACE_DOWN")],
            },
            {"id": "c", "input": key("KEY_C", "kbd"), "outputs": [key("KEY_Y")]},
        ],
    }
)


class FakeClock:
    def __init__(self):
        self.now = 100.0

    def __call__(self):
        return self.now


@pytest.fixture
def clock():
    return FakeClock()


@pytest.fixture
def tap_engine(sink, clock):
    return MappingEngine(TAP_CONFIG, sink, clock=clock)


def test_tap_releases_after_duration_independent_of_input(tap_engine, sink, clock):
    from inpmap.engine import TAP_DURATION

    tap_engine.handle(ev("kbd", "KEY_X", PRESS))
    assert sink.events == [("vkbd", c("KEY_Y"), True), ("vpad", c("BTN_FACE_DOWN"), True)]
    assert tap_engine.next_deadline() == pytest.approx(100.0 + TAP_DURATION)
    tap_engine.tick()  # not due yet
    assert len(sink.events) == 2
    clock.now += TAP_DURATION
    tap_engine.tick()
    assert sink.events[-1] == ("vkbd", c("KEY_Y"), False)
    assert tap_engine.next_deadline() is None
    # the hold output still follows the input
    assert tap_engine.held_outputs() == {("vpad", c("BTN_FACE_DOWN"))}
    tap_engine.handle(ev("kbd", "KEY_X", RELEASE))
    assert sink.events[-1] == ("vpad", c("BTN_FACE_DOWN"), False)


def test_tap_with_quick_release_still_lasts_full_duration(tap_engine, sink, clock):
    tap_engine.handle(ev("kbd", "KEY_X", PRESS))
    tap_engine.handle(ev("kbd", "KEY_X", RELEASE))
    assert ("vkbd", c("KEY_Y"), False) not in sink.events
    clock.now += 1
    tap_engine.tick()
    assert sink.events[-1] == ("vkbd", c("KEY_Y"), False)


def test_tap_ignores_repeat_and_taps_again_on_next_press(tap_engine, sink, clock):
    tap_engine.handle(ev("kbd", "KEY_X", PRESS))
    tap_engine.handle(ev("kbd", "KEY_X", REPEAT))
    clock.now += 1
    tap_engine.tick()
    tap_engine.handle(ev("kbd", "KEY_X", RELEASE))
    tap_engine.handle(ev("kbd", "KEY_X", PRESS))
    y_presses = [e for e in sink.events if e == ("vkbd", c("KEY_Y"), True)]
    assert len(y_presses) == 2


def test_tap_does_not_release_key_held_by_another_mapping(tap_engine, sink, clock):
    tap_engine.handle(ev("kbd", "KEY_C", PRESS))  # holds KEY_Y
    tap_engine.handle(ev("kbd", "KEY_X", PRESS))  # taps KEY_Y: already down
    clock.now += 1
    tap_engine.tick()
    assert ("vkbd", c("KEY_Y"), False) not in sink.events
    tap_engine.handle(ev("kbd", "KEY_C", RELEASE))
    assert sink.events[-1] == ("vkbd", c("KEY_Y"), False)


def test_release_all_finishes_pending_taps(tap_engine, sink):
    tap_engine.handle(ev("kbd", "KEY_X", PRESS))
    tap_engine.release_all()
    assert tap_engine.held_outputs() == set()
    assert tap_engine.next_deadline() is None
    assert ("vkbd", c("KEY_Y"), False) in sink.events


def test_device_loss_lets_pending_tap_finish(tap_engine, sink, clock):
    tap_engine.handle(ev("kbd", "KEY_X", PRESS))
    tap_engine.release_device("kbd")
    assert sink.events[-1] == ("vpad", c("BTN_FACE_DOWN"), False)  # hold output released
    assert tap_engine.held_outputs() == {("vkbd", c("KEY_Y"))}
    clock.now += 1
    tap_engine.tick()
    assert tap_engine.held_outputs() == set()

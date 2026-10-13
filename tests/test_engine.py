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
                "outputs": [key("KEY_Y"), button("BTN_SOUTH")],
            },
            {"id": "c", "input": key("KEY_C", "kbd"), "outputs": [key("KEY_Y")]},
            {"id": "z", "input": key("KEY_Z", "kbd"), "outputs": [button("BTN_START")]},
            {"id": "pad-east", "input": button("BTN_EAST", "pad"), "outputs": [key("KEY_Y")]},
        ],
    }
)


class RecordingSink:
    def __init__(self):
        self.events = []

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
    assert sink.events == [("vkbd", c("KEY_Y"), True), ("vpad", c("BTN_SOUTH"), True)]
    assert engine.active_rules() == ["x"]


def test_release_releases_all_outputs(engine, sink):
    engine.handle(ev("kbd", "KEY_X", PRESS))
    assert engine.handle(ev("kbd", "KEY_X", RELEASE)) is True
    assert sink.events[2:] == [("vkbd", c("KEY_Y"), False), ("vpad", c("BTN_SOUTH"), False)]
    assert engine.active_rules() == []
    assert engine.held_outputs() == set()


def test_repeat_is_consumed_without_output(engine, sink):
    engine.handle(ev("kbd", "KEY_X", PRESS))
    for _ in range(5):
        assert engine.handle(ev("kbd", "KEY_X", REPEAT)) is True
    assert len(sink.events) == 2


def test_repeat_without_press_does_nothing(engine, sink):
    assert engine.handle(ev("kbd", "KEY_X", REPEAT)) is True
    assert sink.events == []


def test_duplicate_press_is_ignored(engine, sink):
    engine.handle(ev("kbd", "KEY_X", PRESS))
    engine.handle(ev("kbd", "KEY_X", PRESS))
    engine.handle(ev("kbd", "KEY_X", RELEASE))
    assert [pressed for _, _, pressed in sink.events] == [True, True, False, False]


def test_release_without_press_is_ignored_but_consumed(engine, sink):
    # e.g. the key was already held when the remapper started
    assert engine.handle(ev("kbd", "KEY_X", RELEASE)) is True
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
    engine.handle(ev("kbd", "KEY_X", PRESS))  # KEY_Y + BTN_SOUTH
    engine.handle(ev("kbd", "KEY_C", PRESS))  # KEY_Y again
    engine.handle(ev("kbd", "KEY_X", RELEASE))
    # BTN_SOUTH released, KEY_Y still held by "c"
    assert sink.events == [
        ("vkbd", c("KEY_Y"), True),
        ("vpad", c("BTN_SOUTH"), True),
        ("vpad", c("BTN_SOUTH"), False),
    ]
    engine.handle(ev("kbd", "KEY_C", RELEASE))
    assert sink.events[-1] == ("vkbd", c("KEY_Y"), False)


def test_shared_output_across_input_devices(engine, sink):
    engine.handle(ev("pad", "BTN_EAST", PRESS))
    engine.handle(ev("kbd", "KEY_C", PRESS))
    engine.handle(ev("pad", "BTN_EAST", RELEASE))
    assert sink.events == [("vkbd", c("KEY_Y"), True)]
    engine.handle(ev("kbd", "KEY_C", RELEASE))
    assert sink.events[-1] == ("vkbd", c("KEY_Y"), False)


def test_alias_codes_refer_to_the_same_input(sink):
    # BTN_A and BTN_SOUTH are one code; an event for either matches.
    config = parse_config(
        {
            "version": 1,
            "inputs": {"pad": {"name": "Pad"}},
            "outputs": {"vkbd": {"type": "keyboard"}},
            "mappings": [
                {"id": "a", "input": button("BTN_A", "pad"), "outputs": [key("KEY_ENTER")]}
            ],
        }
    )
    engine = MappingEngine(config, sink)
    assert engine.handle(ev("pad", "BTN_SOUTH", PRESS)) is True
    assert sink.events == [("vkbd", c("KEY_ENTER"), True)]


# -- device loss and shutdown ----------------------------------------------


def test_release_device_releases_only_its_inputs(engine, sink):
    engine.handle(ev("kbd", "KEY_X", PRESS))
    engine.handle(ev("pad", "BTN_EAST", PRESS))
    engine.release_device("kbd")
    # BTN_SOUTH released; KEY_Y still held by the pad's rule
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
        with pytest.raises(OutputError, match="mapping 'x'.*BTN_SOUTH"):
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
        assert outputs.held("vpad") == set()  # BTN_SOUTH still released
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

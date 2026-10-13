"""`inpmap input-config`: device grouping, selectors, file editing, the session."""

import os

import pytest

from inpmap.backends.linux_setup import SysfsInput, devices_for_input_config, parse_bitmap
from inpmap.codes import code_from_name as c
from inpmap.config import ConfigError
from inpmap.dsl.compiler import compile_text
from inpmap.dsl.parser import DslSyntaxError
from inpmap.input_config import (
    ConfigFile,
    Device,
    Session,
    classify,
    group_devices,
    group_title,
    name_problem,
    run_session,
    selector_for,
    suggest_name,
    write_atomically,
)

KEYBOARD_KEYS = frozenset({c("KEY_A"), c("KEY_B"), c("KEY_ENTER")})
PAD_KEYS = frozenset({c("BTN_SOUTH"), c("BTN_EAST")})
ABS_X, ABS_Y, ABS_MT_POSITION_X, REL_X = 0, 1, 0x35, 0


def sysfs(node, name, phys, keys, abs_axes=(), rel=(), vendor="1532", uniq=""):
    return SysfsInput(
        node,
        name,
        vendor,
        "1027",
        phys,
        "0003",
        uniq,
        frozenset(keys),
        frozenset(abs_axes),
        frozenset(rel),
    )


# A gamepad with four interfaces (like a Razer Raiju) and a two-node keyboard dongle.
NODES = [
    sysfs("event3", "Pad Keyboard", "usb-1/input1", KEYBOARD_KEYS),
    sysfs("event4", "Pad Mouse", "usb-1/input1", {c("BTN_LEFT")}, rel={REL_X}),
    sysfs("event5", "Pad", "usb-1/input1", ()),  # motion sensor: no keys
    sysfs("event6", "Pad Touchpad", "usb-1/input5", {c("BTN_LEFT")}, {ABS_MT_POSITION_X}),
    sysfs("event11", "Generic X-Box pad", "usb-1/input0", PAD_KEYS, {ABS_X, ABS_Y}),
    sysfs("event7", "Dongle", "usb-2/input0", KEYBOARD_KEYS, vendor="4348"),
    sysfs("event8", "Dongle Keyboard", "usb-2/input1", KEYBOARD_KEYS, vendor="4348"),
    sysfs("event20", "InpMap forward: Dongle", "inpmap-forward", KEYBOARD_KEYS),
]
LINKS = {
    "/dev/input/event11": ["/dev/input/by-id/usb-Pad-event-joystick"],
    "/dev/input/event7": [
        "/dev/input/by-path/pci-usb-0:2:1.0-event-kbd",
        "/dev/input/by-id/usb-Dongle-event-kbd",
    ],
    "/dev/input/event8": ["/dev/input/by-path/pci-usb-0:2:1.1-event-kbd"],
}


@pytest.fixture
def devices():
    return devices_for_input_config(NODES, LINKS)


def by_node(devices, node):
    return next(d for d in devices if d.node == node)


# -- devices ---------------------------------------------------------------------------------


def test_parse_bitmap():
    assert parse_bitmap("") == frozenset()
    assert parse_bitmap("5") == {0, 2}
    assert parse_bitmap("1 0") == {64}  # 64-bit words, most significant first


def test_classify():
    assert classify(KEYBOARD_KEYS, frozenset(), frozenset()) == "keyboard"
    assert classify(PAD_KEYS, frozenset({ABS_X}), frozenset()) == "gamepad"
    assert classify(frozenset({c("BTN_LEFT")}), frozenset(), frozenset({REL_X})) == "mouse"
    assert classify(frozenset({c("BTN_LEFT")}), frozenset({ABS_MT_POSITION_X}), frozenset()) == (
        "touchpad"
    )
    assert classify(frozenset({c("KEY_POWER")}), frozenset(), frozenset()) == "other"


def test_devices_without_keys_and_own_devices_are_left_out(devices):
    assert [d.node for d in devices] == [
        "event3",
        "event4",
        "event6",
        "event11",
        "event7",
        "event8",
    ]


def test_grouped_per_physical_device_with_the_product_name(devices):
    groups = group_devices(devices)
    assert [(g.title, [d.node for d in g.devices]) for g in groups] == [
        ("Pad", ["event3", "event4", "event6", "event11"]),  # titled by the keyless node
        ("Dongle", ["event7", "event8"]),
    ]


def test_group_title():
    assert group_title(["A Keyboard", "A", "A Mouse"]) == "A"
    assert group_title(["Mouse X", "Keyboard Y"]) == "Mouse X"  # shortest


def test_selector_prefers_by_id_then_unique_name_then_by_path(devices):
    assert selector_for(by_node(devices, "event7"), devices) == (
        "path",
        "/dev/input/by-id/usb-Dongle-event-kbd",
    )
    assert selector_for(by_node(devices, "event3"), devices) == ("name", "Pad Keyboard")
    twin = Device("event9", "Dongle Keyboard", ("x",), "keyboard", 3)
    assert selector_for(by_node(devices, "event8"), [*devices, twin]) == (
        "path",
        "/dev/input/by-path/pci-usb-0:2:1.1-event-kbd",
    )


def test_names():
    assert suggest_name("keyboard", []) == "kbd"
    assert suggest_name("keyboard", ["kbd", "kbd2"]) == "kbd3"
    assert suggest_name("other", []) == "dev"
    assert name_problem("pad", []) is None
    assert "reserved" in name_problem("map", [])
    assert "already used" in name_problem("kbd", ["kbd"])
    assert "not a valid name" in name_problem("2pad", [])


# -- the file --------------------------------------------------------------------------------

EXISTING = """# my config
version 1

input kbd {
    path = "/dev/input/by-id/usb-Dongle-event-kbd"   # the dongle
}
# outputs
output keyboard { type = keyboard }
map KEY_A { tap KEY_B }
"""


def test_existing_inputs_are_found_and_marked(tmp_path, devices, monkeypatch):
    path = tmp_path / "c.inpmap"
    path.write_text(EXISTING)
    monkeypatch.setattr(os.path, "realpath", lambda p: LINK_TARGETS.get(p, p))
    file = ConfigFile.load(str(path))
    assert [(e.name, e.selector) for e in file.inputs] == [("kbd", "path")]
    assert file.mark(devices) == {"event7": "kbd"}


LINK_TARGETS = {"/dev/input/by-id/usb-Dongle-event-kbd": "/dev/input/event7"}


def test_blocks_are_inserted_after_the_last_input_keeping_everything_else(tmp_path):
    path = tmp_path / "c.inpmap"
    path.write_text(EXISTING)
    text = ConfigFile.load(str(path)).with_inputs(['input pad {\n    name = "Pad"\n}'])
    assert text == EXISTING.replace(
        "# the dongle\n}\n", '# the dongle\n}\n\ninput pad {\n    name = "Pad"\n}\n'
    )


def test_without_inputs_blocks_go_after_version(tmp_path):
    path = tmp_path / "c.inpmap"
    path.write_text("version 1\noutput keyboard { type = keyboard }\n")
    text = ConfigFile.load(str(path)).with_inputs(['input kbd {\n    name = "K"\n}'])
    assert text.startswith('version 1\n\ninput kbd {\n    name = "K"\n}\noutput keyboard')


def test_new_file_gets_a_starter_configuration(tmp_path):
    file = ConfigFile.load(str(tmp_path / "new.inpmap"))
    assert file.text is None
    text = file.with_inputs(['input kbd {\n    name = "K"\n}'])
    assert text.startswith("# InpMap configuration")
    compile_text(text + "map KEY_A { tap KEY_B; tap BTN_SOUTH }\n", "new.inpmap")


def test_unparsable_or_versionless_files_are_refused(tmp_path):
    bad = tmp_path / "bad.inpmap"
    bad.write_text("version 1\nmap {\n")
    with pytest.raises(DslSyntaxError):
        ConfigFile.load(str(bad))
    bad.write_text("# nothing\n")
    with pytest.raises(ValueError, match="version"):
        ConfigFile.load(str(bad))


def test_write_atomically_keeps_a_backup_and_the_mode(tmp_path):
    path = tmp_path / "c.inpmap"
    assert write_atomically(str(path), "one") is None
    path.chmod(0o600)
    assert write_atomically(str(path), "two") == str(path) + ".bak"
    assert path.read_text() == "two"
    assert (tmp_path / "c.inpmap.bak").read_text() == "one"
    assert path.stat().st_mode & 0o777 == 0o600
    assert sorted(p.name for p in tmp_path.iterdir()) == ["c.inpmap", "c.inpmap.bak"]


# -- the session -----------------------------------------------------------------------------


class Script:
    def __init__(self, *lines):
        self.lines = list(lines)
        self.output = []

    def ask(self, prompt):
        if not self.lines:
            raise EOFError
        return self.lines.pop(0)

    def say(self, text):
        self.output.append(text)

    def text(self):
        return "\n".join(self.output)


def session_for(path, devices, script, identified=None):
    def check(text):
        try:
            compile_text(text, str(path))
        except ConfigError as exc:
            return list(exc.problems)
        return []

    file = ConfigFile.load(str(path))
    return Session(file, devices, script.say, lambda candidates: identified, check)


def test_select_rename_and_write(tmp_path, devices):
    path = tmp_path / "c.inpmap"
    path.write_text("version 1\noutput keyboard { type = keyboard }\nmap KEY_A { tap KEY_B }\n")
    script = Script("4", "5", "5", "5 left", "w")
    run_session(session_for(path, devices, script), script.ask)
    out = script.text()
    assert "4 selected as 'pad'" in out
    assert "5 selected as 'kbd'" in out and "5 deselected." in out
    assert "5 selected as 'left'" in out
    assert "Check: OK." in out
    config = compile_text(path.read_text(), "c").config
    assert {name: spec.path or spec.name for name, spec in config.inputs.items()} == {
        "pad": "/dev/input/by-id/usb-Pad-event-joystick",
        "left": "/dev/input/by-id/usb-Dongle-event-kbd",
    }
    assert (tmp_path / "c.inpmap.bak").exists()


def test_quit_and_end_of_input_change_nothing(tmp_path, devices):
    path = tmp_path / "c.inpmap"
    for script in (Script("4", "q"), Script("4")):
        run_session(session_for(path, devices, script), script.ask)
        assert "No changes written." in script.text()
    assert not path.exists()


def test_errors_are_explained(tmp_path, devices):
    path = tmp_path / "c.inpmap"
    path.write_text(EXISTING.replace("/dev/input/by-id/usb-Dongle-event-kbd", "/nope"))
    script = Script("99", "x", "1 map", "w", "q")
    run_session(session_for(path, devices, script), script.ask)
    out = script.text()
    assert "There is no device 99." in out
    assert "Unknown command 'x'" in out
    assert "'map' is a reserved word" in out
    assert "Nothing selected" in out


def test_identify_selects_the_pressed_device(tmp_path, devices):
    path = tmp_path / "new.inpmap"
    pad = by_node(devices, "event11")
    script = Script("i", "w")
    run_session(session_for(path, devices, script, identified=pad), script.ask)
    assert "That was 4: Generic X-Box pad (gamepad)." in script.text()
    assert 'input pad {\n    path = "/dev/input/by-id/usb-Pad-event-joystick"\n}' in (
        path.read_text()
    )


def test_identify_without_result(tmp_path, devices):
    script = Script("i", "q")
    run_session(session_for(tmp_path / "n.inpmap", devices, script), script.ask)
    assert "No key press recognised." in script.text()


def test_listing_marks_existing_and_selected(tmp_path, devices, monkeypatch):
    path = tmp_path / "c.inpmap"
    path.write_text(EXISTING)
    monkeypatch.setattr(os.path, "realpath", lambda p: LINK_TARGETS.get(p, p))
    script = Script("6", "l", "q")
    run_session(session_for(path, devices, script), script.ask)
    listing = script.output[-2]
    assert "  Pad (1532:1027)" in listing
    assert "      5  [kbd]        keyboard     3 keys     Dongle" in listing
    assert "      6  + kbd2       keyboard     3 keys     Dongle Keyboard" in listing

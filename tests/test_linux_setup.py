import pytest

from inpmap.backends.linux_setup import (
    UINPUT_RULE,
    SysfsInput,
    device_rule,
    read_sysfs_inputs,
    render_rules,
    resolve,
)
from inpmap.config import parse_config
from inpmap.input import InputError
from inpmap.models import InputDeviceSpec

KBD = SysfsInput("event7", "2.4G Dongle", "4348", "4744", "usb-0000:00:14.0-11/input0")
KBD_IF1 = SysfsInput("event8", "2.4G Dongle Keyboard", "4348", "4744", "usb-.../input1")
OWN = SysfsInput("event25", "2.4G Dongle", "4348", "4744", "inpmap-forward")


def make_sysfs(root, devices):
    for d in devices:
        base = root / d.node / "device"
        (base / "id").mkdir(parents=True)
        (base / "name").write_text(d.name + "\n")
        (base / "id" / "vendor").write_text(d.vendor + "\n")
        (base / "id" / "product").write_text(d.product + "\n")
        if d.phys:
            (base / "phys").write_text(d.phys + "\n")


def config_with(selector):
    return parse_config(
        {
            "version": 1,
            "inputs": {"kbd": selector},
            "outputs": {"vkbd": {"type": "keyboard"}},
            "mappings": [
                {
                    "id": "x",
                    "input": {"device": "kbd", "type": "key", "code": "KEY_X"},
                    "outputs": [{"device": "vkbd", "type": "key", "code": "KEY_Y"}],
                }
            ],
        }
    )


def test_read_sysfs_inputs(tmp_path):
    make_sysfs(tmp_path, [KBD, KBD_IF1])
    (tmp_path / "mouse0").mkdir()  # non-event entries are ignored
    assert read_sysfs_inputs(str(tmp_path)) == [KBD, KBD_IF1]


def test_read_sysfs_missing_root(tmp_path):
    assert read_sysfs_inputs(str(tmp_path / "nope")) == []


def test_resolve_by_name_skips_own_devices():
    spec = InputDeviceSpec(id="kbd", name="2.4G Dongle")
    assert resolve(spec, [OWN, KBD_IF1, KBD]) == KBD


def test_resolve_by_path(tmp_path):
    (tmp_path / "event8").touch()
    link = tmp_path / "usb-4348_2.4G_Dongle-if01-event-kbd"
    link.symlink_to(tmp_path / "event8")
    spec = InputDeviceSpec(id="kbd", path=str(link))
    assert resolve(spec, [KBD, KBD_IF1]) == KBD_IF1


def test_resolve_missing_device():
    with pytest.raises(InputError, match="plug it in"):
        resolve(InputDeviceSpec(id="kbd", name="Other"), [KBD])


def test_device_rule_matches_name_vendor_product():
    assert device_rule(KBD) == (
        'SUBSYSTEM=="input", KERNEL=="event*", ATTRS{name}=="2.4G Dongle", '
        'ATTRS{id/vendor}=="4348", ATTRS{id/product}=="4744", TAG+="uaccess"'
    )


@pytest.mark.parametrize("name", ['Evil "Kbd', "Glob*Kbd", "Back\\slash"])
def test_device_rule_rejects_unsafe_names(name):
    with pytest.raises(InputError, match="write the rule by hand"):
        device_rule(SysfsInput("event1", name, "0001", "0002", ""))


def test_render_rules_contains_uinput_and_inputs_and_instructions():
    text = render_rules(config_with({"name": "2.4G Dongle"}), [KBD], "config/local.json")
    assert UINPUT_RULE in text
    assert device_rule(KBD) in text
    assert "# Input 'kbd': 2.4G Dongle (currently event7)" in text
    assert "sudo install -m 644 70-inpmap.rules /etc/udev/rules.d/70-inpmap.rules" in text
    assert "sudo rm /etc/udev/rules.d/70-inpmap.rules" in text
    # every non-comment line is a rule
    rules = [line for line in text.splitlines() if line and not line.startswith("#")]
    assert len(rules) == 2

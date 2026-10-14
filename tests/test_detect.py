"""`inpmap detect`: events written as triggers."""

from inpmap.codes import TRIGGER_AXES
from inpmap.codes import code_from_name as c
from inpmap.detect import Detector
from inpmap.models import Modifier

KBD, PAD, OTHER = "/dev/input/event7", "/dev/input/event11", "/dev/input/event3"


def detector(**kw):
    return Detector({KBD: "kbd", PAD: "pad"}, "default", **kw)


def test_keys_with_input_names_and_modifiers():
    d = detector()
    assert d.key(KBD, "Dongle", c("KEY_F7"), True) == "kbd.KEY_F7" + " " * 22 + " Dongle"
    assert d.key(KBD, "Dongle", c("KEY_F7"), False) is None  # releases print nothing
    assert d.key(KBD, "Dongle", c("KEY_RIGHTCTRL"), True) is None  # modifiers alone: nothing
    d.key(PAD, "Pad", c("KEY_LEFTSHIFT"), True)  # modifiers count from every device
    line = d.key(KBD, "Dongle", c("KEY_F7"), True)
    assert line.startswith("kbd.KEY_F7 modifiers(ctrl, shift) ")
    d.key(KBD, "Dongle", c("KEY_RIGHTCTRL"), False)
    assert d.key(PAD, "Pad", c("BTN_SOUTH"), True).startswith("pad.BTN_SOUTH modifiers(shift) ")


def test_devices_outside_the_profile_get_a_hint():
    line = detector().key(OTHER, "Pad Keyboard", c("KEY_VOLUMEUP"), True)
    assert line.startswith("KEY_VOLUMEUP ")
    assert line.endswith("(not in default; add it with: inpmap input-config default)")
    assert "not in" not in Detector({}, None).key(OTHER, "X", c("KEY_A"), True)


def test_keys_that_are_not_modifiers_in_the_profile_are_shown():
    d = detector(modifiers=frozenset({Modifier.CTRL}))
    assert d.key(KBD, "Dongle", c("KEY_RIGHTALT"), True).startswith("kbd.KEY_RIGHTALT ")


def test_axes_print_once_per_crossing():
    d = detector()
    rz, hat = TRIGGER_AXES["ABS_RZ"], TRIGGER_AXES["ABS_HAT0Y"]
    assert d.axis(PAD, "Pad", rz, 0.3) is None
    assert d.axis(PAD, "Pad", rz, 0.6).startswith("pad.ABS_RZ above 0.5 ")
    assert d.axis(PAD, "Pad", rz, 0.9) is None  # still past half
    assert d.axis(PAD, "Pad", rz, 0.47) is None  # within the hysteresis
    assert d.axis(PAD, "Pad", rz, 0.1) is None  # back to the middle: nothing
    assert d.axis(PAD, "Pad", rz, 0.7) is not None  # crossing again
    up = d.axis(PAD, "Pad", hat, -1.0)
    assert up.startswith("pad.ABS_HAT0Y below -0.5 ") and up.endswith("(D-pad up)")
    assert d.axis(PAD, "Pad", 0x28, 1.0) is None  # ABS_MISC: cannot be a trigger

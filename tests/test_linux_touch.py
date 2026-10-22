"""Multi-touch protocol B decoding (backends/linux_touch.py)."""

from inpmap.backends.linux_touch import (
    ABS_MT_POSITION_X,
    ABS_MT_POSITION_Y,
    ABS_MT_SLOT,
    ABS_MT_TRACKING_ID,
    TouchDecoder,
)
from inpmap.models import TouchContact, TouchEvent

ABS_MT_PRESSURE = 0x3A
# The Razer Raiju V3 Pro's touchpad.
RANGES = {ABS_MT_POSITION_X: (0, 2628), ABS_MT_POSITION_Y: (0, 1332)}


def decoder():
    return TouchDecoder("touch", RANGES)


def feed(dec, *values):
    for code, value in values:
        dec.axis(code, value)
    return dec.frame()


def test_one_finger_down_moves_and_lifts():
    dec = decoder()
    down = feed(dec, (ABS_MT_TRACKING_ID, 7), (ABS_MT_POSITION_X, 2628), (ABS_MT_POSITION_Y, 0))
    assert down == TouchEvent("touch", (TouchContact(0, 1.0, 0.0),))
    moved = feed(dec, (ABS_MT_POSITION_Y, 666))
    assert moved == TouchEvent("touch", (TouchContact(0, 1.0, 666 / 1332),))
    assert feed(dec, (ABS_MT_TRACKING_ID, -1)) == TouchEvent("touch", ())


def test_frame_without_changes_reports_nothing():
    dec = decoder()
    assert dec.frame() is None
    assert feed(dec, (ABS_MT_PRESSURE, 30)) is None  # not used
    assert feed(dec, (ABS_MT_POSITION_X, 100)) is None  # no finger in the slot


def test_fingers_are_listed_in_the_order_they_touched():
    dec = decoder()
    feed(dec, (ABS_MT_SLOT, 2), (ABS_MT_TRACKING_ID, 1), (ABS_MT_POSITION_X, 0))
    both = feed(dec, (ABS_MT_SLOT, 0), (ABS_MT_TRACKING_ID, 2), (ABS_MT_POSITION_X, 2628))
    assert [c.slot for c in both.contacts] == [2, 0]
    # The values that follow belong to the slot selected last (0).
    moved = feed(dec, (ABS_MT_POSITION_Y, 1332))
    assert moved.contacts[1] == TouchContact(0, 1.0, 1.0)


def test_positions_outside_the_range_are_clamped():
    dec = TouchDecoder("touch", {ABS_MT_POSITION_X: (100, 200), ABS_MT_POSITION_Y: (0, 0)})
    event = feed(dec, (ABS_MT_TRACKING_ID, 1), (ABS_MT_POSITION_X, 250), (ABS_MT_POSITION_Y, 5))
    assert event.contacts == (TouchContact(0, 1.0, 0.0),)


def test_initial_slot_is_used():
    dec = TouchDecoder("touch", RANGES, slot=1)
    event = feed(dec, (ABS_MT_TRACKING_ID, 1))
    assert event.contacts[0].slot == 1


def test_reset_lifts_every_finger_and_ignores_stale_ones():
    dec = decoder()
    assert dec.reset() is None  # nothing was down
    feed(dec, (ABS_MT_TRACKING_ID, 1), (ABS_MT_POSITION_X, 10))
    assert dec.reset() == TouchEvent("touch", ())
    # The finger still on the surface moves, but has no new tracking ID.
    assert feed(dec, (ABS_MT_POSITION_X, 20)) is None
    assert feed(dec, (ABS_MT_TRACKING_ID, 2)).contacts == (TouchContact(0, 20 / 2628, 0.0),)


def test_handles_only_multitouch_axes():
    assert TouchDecoder.handles(ABS_MT_SLOT) and TouchDecoder.handles(ABS_MT_PRESSURE)
    assert not TouchDecoder.handles(0x00)  # ABS_X

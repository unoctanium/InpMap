"""Axis holder stacks and routed base values (docs/configuration.md §7.3)."""

from inpmap.axes import AxisStacks

KEY = ("gamepad", 0x00)


def stacks():
    written = []
    return AxisStacks(lambda device, code, value: written.append(value)), written


def test_base_shows_while_no_holder_and_returns_after_the_holder():
    axes, written = stacks()
    axes.set_base(KEY, "pad", 0.3)
    holder = axes.acquire(KEY, 1.0)  # a mapping overrides the stick
    axes.set_base(KEY, "pad", 0.4)  # the stick moves meanwhile: not visible
    assert axes.below(holder) == 0.4
    axes.release(holder)
    assert written == [0.3, 1.0, 0.4]


def test_most_recently_updated_base_wins_and_clearing_falls_back():
    axes, written = stacks()
    axes.set_base(KEY, "pad1", 0.5)
    axes.set_base(KEY, "pad2", -0.5)
    axes.set_base(KEY, "pad1", 0.6)
    axes.clear_base(KEY, "pad1")
    axes.clear_base(KEY, "pad2")
    assert written == [0.5, -0.5, 0.6, -0.5, 0.0]


def test_unchanged_values_are_not_written_again():
    axes, written = stacks()
    axes.set_base(KEY, "pad", 0.0)
    axes.set_base(KEY, "pad", 0.2)
    axes.set_base(KEY, "pad", 0.2)
    axes.clear_base(KEY, "unknown")
    assert written == [0.2]

import pytest

from inpmap.state import OutputRefCounts

KEY = ("vkbd", 21)


def test_first_acquire_and_last_release_report_transitions():
    refs = OutputRefCounts()
    assert refs.acquire(KEY) is True
    assert refs.acquire(KEY) is False
    assert refs.count(KEY) == 2
    assert refs.release(KEY) is False
    assert refs.release(KEY) is True
    assert refs.count(KEY) == 0
    assert refs.held() == set()


def test_keys_are_independent():
    refs = OutputRefCounts()
    refs.acquire(KEY)
    refs.acquire(("vpad", 304))
    assert refs.held() == {KEY, ("vpad", 304)}
    assert refs.release(KEY) is True
    assert refs.held() == {("vpad", 304)}


def test_release_without_acquire_is_a_bug():
    refs = OutputRefCounts()
    with pytest.raises(ValueError):
        refs.release(KEY)
    assert refs.held() == set()

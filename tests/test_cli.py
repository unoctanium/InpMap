import json
from pathlib import Path

import pytest

from inpmap.cli import EXIT_CONFIG_ERROR, EXIT_DEVICE_ERROR, EXIT_OK, EXIT_USAGE, main

EXAMPLE = Path(__file__).resolve().parent.parent / "config" / "example.json"


def test_check_valid_config(capsys):
    assert main(["check", str(EXAMPLE)]) == EXIT_OK
    out = capsys.readouterr().out
    assert "OK (version 1)" in out
    assert "physical-keyboard KEY_X -> keyboard KEY_Y, gamepad BTN_SOUTH" in out


def test_check_invalid_config(tmp_path, capsys):
    path = tmp_path / "bad.json"
    path.write_text(json.dumps({"version": 99}))
    assert main(["check", str(path)]) == EXIT_CONFIG_ERROR
    err = capsys.readouterr().err
    assert "unsupported version 99" in err


@pytest.fixture
def fake_linux_backend(monkeypatch):
    """Replace the uinput backend so test-outputs runs without devices."""
    from fakes import FakeOutputBackend

    backend = FakeOutputBackend()
    linux = pytest.importorskip("inpmap.backends.linux")
    monkeypatch.setattr(linux, "LinuxOutputBackend", lambda: backend)
    return backend


def test_test_outputs_pulses_every_mapped_output(fake_linux_backend, capsys):
    args = ["test-outputs", str(EXAMPLE), "--delay", "0", "--hold", "0"]
    assert main(args) == EXIT_OK
    keyboard = fake_linux_backend.created["keyboard"]
    gamepad = fake_linux_backend.created["gamepad"]
    assert [pressed for _, pressed in keyboard.events] == [True, False]
    assert [pressed for _, pressed in gamepad.events] == [True, False]
    assert keyboard.closed and gamepad.closed
    assert "gamepad: BTN_SOUTH released" in capsys.readouterr().out


def test_test_outputs_only_selected_device(fake_linux_backend):
    args = ["test-outputs", str(EXAMPLE), "--delay", "0", "--hold", "0", "--only", "gamepad"]
    assert main(args) == EXIT_OK
    assert fake_linux_backend.created["keyboard"].events == []
    assert len(fake_linux_backend.created["gamepad"].events) == 2


def test_test_outputs_no_emit(fake_linux_backend):
    assert main(["test-outputs", str(EXAMPLE), "--delay", "0", "--no-emit"]) == EXIT_OK
    assert all(not d.events and d.closed for d in fake_linux_backend.created.values())


def test_test_outputs_unknown_device(fake_linux_backend, capsys):
    args = ["test-outputs", str(EXAMPLE), "--delay", "0", "--only", "nope"]
    assert main(args) == EXIT_USAGE
    assert "unknown output device(s): nope" in capsys.readouterr().err


def test_test_outputs_device_error(fake_linux_backend, capsys):
    fake_linux_backend.fail_on = "gamepad"
    assert main(["test-outputs", str(EXAMPLE), "--delay", "0"]) == EXIT_DEVICE_ERROR
    assert "simulated create failure" in capsys.readouterr().err
    assert fake_linux_backend.created["keyboard"].closed


def test_missing_command_is_usage_error():
    with pytest.raises(SystemExit) as info:
        main([])
    assert info.value.code == 2

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


@pytest.fixture
def fake_run_backends(monkeypatch):
    """Run `inpmap run` against fakes; the scripted input stops immediately."""
    from fakes import FakeInputBackend, FakeInputSource, FakeOutputBackend

    from inpmap.config import load_config

    config = load_config(EXAMPLE)
    sources = {i: FakeInputSource(spec) for i, spec in config.inputs.items()}
    inputs = FakeInputBackend(sources)
    outputs = FakeOutputBackend()
    linux = pytest.importorskip("inpmap.backends.linux")
    linux_input = pytest.importorskip("inpmap.backends.linux_input")
    monkeypatch.setattr(linux, "LinuxOutputBackend", lambda: outputs)
    monkeypatch.setattr(linux_input, "LinuxInputBackend", lambda: inputs)
    return inputs, outputs


def test_run_with_timeout_stops_and_cleans_up(fake_run_backends, capsys):
    inputs, outputs = fake_run_backends
    assert main(["run", str(EXAMPLE), "--timeout", "0.05"]) == EXIT_OK
    assert "stopped (timeout)" in capsys.readouterr().out
    assert all(source.closed for source in inputs.sources.values())
    assert all(device.closed for device in outputs.created.values())


def test_run_restores_signal_handlers(fake_run_backends):
    import signal

    before = {s: signal.getsignal(s) for s in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP)}
    main(["run", str(EXAMPLE), "--timeout", "0.05"])
    assert {s: signal.getsignal(s) for s in before} == before


def test_run_input_error_exit_code(fake_run_backends, capsys):
    from inpmap.input import InputError

    inputs, outputs = fake_run_backends
    inputs.open_error["physical-keyboard"] = InputError("no readable device named X")
    assert main(["run", str(EXAMPLE), "--timeout", "1"]) == EXIT_DEVICE_ERROR
    assert "no readable device named X" in capsys.readouterr().err
    assert all(device.closed for device in outputs.created.values())


def test_run_rejects_non_positive_timeout(capsys):
    assert main(["run", str(EXAMPLE), "--timeout", "0"]) == EXIT_USAGE


def test_missing_command_is_usage_error():
    with pytest.raises(SystemExit) as info:
        main([])
    assert info.value.code == 2


# -- configuration language files --------------------------------------------------------

DSL_EXAMPLE = Path(__file__).resolve().parent.parent / "config" / "example.inpmap"


def test_check_dsl_example(capsys):
    assert main(["check", str(DSL_EXAMPLE)]) == EXIT_OK
    out = capsys.readouterr().out
    assert "combo: kbd KEY_F9 -> macro (4 steps)" in out


def test_check_dsl_reports_positions_and_warnings(tmp_path, capsys):
    path = tmp_path / "bad.inpmap"
    path.write_text(
        'version 1\ninput kbd { name = "K" }\noutput keyboard { type = keyboard }\n'
        "map KEY_X { tap KEY_QQ }\n"
    )
    assert main(["check", str(path)]) == EXIT_CONFIG_ERROR
    assert f"{path}:4:17: unknown key code 'KEY_QQ'" in capsys.readouterr().err
    ok = tmp_path / "warn.inpmap"
    ok.write_text(
        'version 1\ninput kbd { name = "K" }\noutput pad { type = gamepad }\n'
        "map KEY_X { tap BTN_X }\n"
    )
    assert main(["check", str(ok)]) == EXIT_OK
    assert f"{ok}:4:17: warning: BTN_X is the top button" in capsys.readouterr().err


def test_macro_trace_on_dsl_file(capsys):
    assert main(["macro-trace", str(DSL_EXAMPLE), "combo", "--seed", "1"]) == EXIT_OK
    assert "keyboard   KEY_Q            down" in capsys.readouterr().out


def test_dsl_example_file_matches_spec():
    import re

    spec = (DSL_EXAMPLE.parent.parent / "docs" / "dsl.md").read_text()
    block = re.search(r"## 11\. Complete example.*?```\n(.*?)```", spec, re.S).group(1)
    assert DSL_EXAMPLE.read_text() == block

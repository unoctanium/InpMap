from pathlib import Path

import pytest

from inpmap.cli import EXIT_CONFIG_ERROR, EXIT_DEVICE_ERROR, EXIT_OK, EXIT_USAGE, main

EXAMPLE = Path(__file__).resolve().parent / "data" / "json_era_example.inpmap"

# A minimal configuration whose outputs the device tests can count exactly.
SIMPLE = """version 1
input kbd { name = "Kbd" }
output keyboard { type = keyboard }
output gamepad { type = gamepad }
map KEY_X {
    hold KEY_Y
    hold BTN_SOUTH
}
"""


@pytest.fixture
def simple(tmp_path) -> str:
    path = tmp_path / "simple.inpmap"
    path.write_text(SIMPLE)
    return str(path)


# -- check -----------------------------------------------------------------------------


def test_check_example(capsys):
    assert main(["check", str(EXAMPLE)]) == EXIT_OK
    out = capsys.readouterr().out
    assert "OK (version 1)" in out
    assert "KEY_X: every input KEY_X -> keyboard KEY_Y, gamepad BTN_SOUTH" in out
    assert "combo: every input KEY_F9 -> macro (4 steps)" in out


def test_check_reports_positions_and_warnings(tmp_path, capsys):
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


def test_check_unsupported_version(tmp_path, capsys):
    path = tmp_path / "v99.inpmap"
    path.write_text("version 99\n")
    assert main(["check", str(path)]) == EXIT_CONFIG_ERROR
    assert "unsupported version 99" in capsys.readouterr().err


def test_other_file_types_are_rejected(tmp_path, capsys):
    path = tmp_path / "old.json"
    path.write_text("{}")
    assert main(["check", str(path)]) == EXIT_CONFIG_ERROR
    assert "configuration files must end in .inpmap" in capsys.readouterr().err


def test_missing_file(tmp_path, capsys):
    missing = tmp_path / "missing.inpmap"
    assert main(["check", str(missing)]) == EXIT_CONFIG_ERROR
    assert f"no such configuration; create it with: inpmap input-config {missing}" in (
        capsys.readouterr().err
    )


# -- profiles and service-unit ---------------------------------------------------------------


@pytest.fixture
def config_home(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    directory = tmp_path / "inpmap"
    directory.mkdir()
    return directory


def test_profile_names_and_the_default_profile(config_home, capsys):
    (config_home / "default.inpmap").write_text(SIMPLE)
    (config_home / "dcs.inpmap").write_text(SIMPLE)
    assert main(["check"]) == EXIT_OK
    assert f"{config_home}/default.inpmap: OK" in capsys.readouterr().out
    assert main(["check", "dcs"]) == EXIT_OK
    assert f"{config_home}/dcs.inpmap: OK" in capsys.readouterr().out


def test_missing_profile_says_how_to_create_it(config_home, capsys):
    assert main(["check", "nope"]) == EXIT_CONFIG_ERROR
    assert "no such configuration; create it with: inpmap input-config nope" in (
        capsys.readouterr().err
    )


def test_service_unit_lists_the_profiles(config_home, capsys):
    import sys

    (config_home / "dcs.inpmap").write_text(SIMPLE)
    (config_home / "broken.inpmap").write_text("version 1\nmap\n")
    (config_home / "my game.inpmap").write_text(SIMPLE)
    assert main(["service-unit"]) == EXIT_OK
    captured = capsys.readouterr()
    assert f'"{sys.executable}" -m inpmap run --wait-for-devices %i' in captured.out
    assert "#   broken               invalid (1 problem(s); see inpmap check)" in captured.out
    assert "#   dcs                  OK" in captured.out
    assert "my game.inpmap: the name cannot be a profile name" in captured.err


# -- macro-trace -----------------------------------------------------------------------------


def test_macro_trace(capsys):
    assert main(["macro-trace", str(EXAMPLE), "combo", "--seed", "1"]) == EXIT_OK
    assert "keyboard   KEY_Q            down" in capsys.readouterr().out


# -- test-outputs ------------------------------------------------------------------------------


@pytest.fixture
def fake_linux_backend(monkeypatch):
    """Replace the uinput backend so test-outputs runs without devices."""
    from fakes import FakeOutputBackend

    backend = FakeOutputBackend()
    linux = pytest.importorskip("inpmap.backends.linux")
    monkeypatch.setattr(linux, "LinuxOutputBackend", lambda: backend)
    return backend


def test_test_outputs_pulses_every_mapped_output(fake_linux_backend, simple, capsys):
    assert main(["test-outputs", simple, "--delay", "0", "--hold", "0"]) == EXIT_OK
    keyboard = fake_linux_backend.created["keyboard"]
    gamepad = fake_linux_backend.created["gamepad"]
    assert [pressed for _, pressed in keyboard.events] == [True, False]
    assert [pressed for _, pressed in gamepad.events] == [True, False]
    assert keyboard.closed and gamepad.closed
    assert "gamepad: BTN_SOUTH released" in capsys.readouterr().out


def test_test_outputs_only_selected_device(fake_linux_backend, simple):
    args = ["test-outputs", simple, "--delay", "0", "--hold", "0", "--only", "gamepad"]
    assert main(args) == EXIT_OK
    assert fake_linux_backend.created["keyboard"].events == []
    assert len(fake_linux_backend.created["gamepad"].events) == 2


def test_test_outputs_no_emit(fake_linux_backend, simple):
    assert main(["test-outputs", simple, "--delay", "0", "--no-emit"]) == EXIT_OK
    assert all(not d.events and d.closed for d in fake_linux_backend.created.values())


def test_test_outputs_unknown_device(fake_linux_backend, simple, capsys):
    assert main(["test-outputs", simple, "--delay", "0", "--only", "nope"]) == EXIT_USAGE
    assert "unknown output device(s): nope" in capsys.readouterr().err


def test_test_outputs_device_error(fake_linux_backend, simple, capsys):
    fake_linux_backend.fail_on = "gamepad"
    assert main(["test-outputs", simple, "--delay", "0"]) == EXIT_DEVICE_ERROR
    assert "simulated create failure" in capsys.readouterr().err
    assert fake_linux_backend.created["keyboard"].closed


# -- run --------------------------------------------------------------------------------------


@pytest.fixture
def fake_run_backends(monkeypatch, simple):
    """Run `inpmap run` against fakes; the scripted input stops immediately."""
    from fakes import FakeInputBackend, FakeInputSource, FakeOutputBackend

    from inpmap.loading import load

    config = load(simple).config
    sources = {i: FakeInputSource(spec) for i, spec in config.inputs.items()}
    inputs = FakeInputBackend(sources)
    outputs = FakeOutputBackend()
    linux = pytest.importorskip("inpmap.backends.linux")
    linux_input = pytest.importorskip("inpmap.backends.linux_input")
    monkeypatch.setattr(linux, "LinuxOutputBackend", lambda: outputs)
    monkeypatch.setattr(linux_input, "LinuxInputBackend", lambda: inputs)
    return inputs, outputs


def test_run_with_timeout_stops_and_cleans_up(fake_run_backends, simple, capsys):
    inputs, outputs = fake_run_backends
    assert main(["run", simple, "--timeout", "0.05"]) == EXIT_OK
    assert "stopped (timeout)" in capsys.readouterr().out
    assert all(source.closed for source in inputs.sources.values())
    assert all(device.closed for device in outputs.created.values())


def test_run_restores_signal_handlers(fake_run_backends, simple):
    import signal

    before = {s: signal.getsignal(s) for s in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP)}
    main(["run", simple, "--timeout", "0.05"])
    assert {s: signal.getsignal(s) for s in before} == before


def test_run_input_error_exit_code(fake_run_backends, simple, capsys):
    from inpmap.input import InputError

    inputs, outputs = fake_run_backends
    inputs.open_error["kbd"] = InputError("no readable device named X")
    assert main(["run", simple, "--timeout", "1"]) == EXIT_DEVICE_ERROR
    assert "no readable device named X" in capsys.readouterr().err
    assert all(device.closed for device in outputs.created.values())


def test_run_wait_for_devices_starts_without_the_device(fake_run_backends, simple, capsys):
    from inpmap.input import InputError

    inputs, outputs = fake_run_backends
    inputs.open_error["kbd"] = InputError("no readable device named X")
    assert main(["run", simple, "--timeout", "0.05", "--wait-for-devices"]) == EXIT_OK
    assert "stopped (timeout)" in capsys.readouterr().out
    assert all(device.closed for device in outputs.created.values())


def test_run_rejects_non_positive_timeout(simple):
    assert main(["run", simple, "--timeout", "0"]) == EXIT_USAGE


def test_missing_command_is_usage_error():
    with pytest.raises(SystemExit) as info:
        main([])
    assert info.value.code == 2


# -- codes ---------------------------------------------------------------------------------


def test_codes_filter(capsys):
    assert main(["codes", "kp1"]) == EXIT_OK
    lines = capsys.readouterr().out.splitlines()
    assert lines[0].split() == ["NAME", "CODE", "SENT", "BY"]
    assert lines[1].split() == ["KEY_KP1", "79", "keyboard"]
    assert len(lines) == 2


def test_codes_aliases_axes_and_no_match(capsys):
    main(["codes", "btn_a"])
    assert "BTN_SOUTH                     304  gamepad  (also BTN_A)" in capsys.readouterr().out
    main(["codes", "ABS_RZ"])
    assert "gamepad axis (trigger)" in capsys.readouterr().out
    assert main(["codes", "nothing_like_this"]) == EXIT_OK
    assert "no name contains 'nothing_like_this'" in capsys.readouterr().out


# -- fmt -------------------------------------------------------------------------------------

UNFORMATTED = (
    'version 1\ninput kbd { name = "K" }\noutput keyboard { type = keyboard }\n'
    "map KEY_X { tap KEY_A; tap KEY_B }\n"
)
FORMATTED = (
    'version 1\ninput kbd { name = "K" }\noutput keyboard { type = keyboard }\n'
    "map KEY_X {\n    tap KEY_A\n    tap KEY_B\n}\n"
)


def test_fmt_rewrites_in_place_without_backup(tmp_path, capsys):
    path = tmp_path / "a.inpmap"
    path.write_text(UNFORMATTED)
    assert main(["fmt", str(path)]) == EXIT_OK
    assert path.read_text() == FORMATTED
    assert f"{path}: formatted" in capsys.readouterr().out
    assert not (tmp_path / "a.inpmap.bak").exists()
    assert main(["fmt", str(path)]) == EXIT_OK  # already formatted: silent
    assert capsys.readouterr().out == ""


def test_fmt_check_and_diff_change_nothing(tmp_path, capsys):
    path = tmp_path / "a.inpmap"
    path.write_text(UNFORMATTED)
    assert main(["fmt", "--check", str(path)]) == EXIT_CONFIG_ERROR
    assert f"{path}: not formatted" in capsys.readouterr().out
    assert main(["fmt", "--diff", str(path)]) == EXIT_OK
    out = capsys.readouterr().out
    assert "-map KEY_X { tap KEY_A; tap KEY_B }" in out and "+    tap KEY_A" in out
    assert path.read_text() == UNFORMATTED


def test_fmt_leaves_files_with_syntax_errors_alone(tmp_path, capsys):
    path = tmp_path / "bad.inpmap"
    path.write_text("version 1\nmap {\n")
    assert main(["fmt", str(path)]) == EXIT_CONFIG_ERROR
    assert "unexpected" in capsys.readouterr().err
    assert path.read_text() == "version 1\nmap {\n"


def test_fmt_stdin_to_stdout(monkeypatch, capsys):
    import io

    monkeypatch.setattr("sys.stdin", io.StringIO(UNFORMATTED))
    assert main(["fmt", "-"]) == EXIT_OK
    assert capsys.readouterr().out == FORMATTED


def test_check_notes_a_configuration_without_mappings(tmp_path, capsys):
    path = tmp_path / "empty.inpmap"
    path.write_text('version 1\ninput kbd { name = "K" }\noutput keyboard { type = keyboard }\n')
    assert main(["check", str(path)]) == EXIT_OK
    assert "note: no mappings yet" in capsys.readouterr().out


def test_input_config_example_starts_from_the_example(config_home, monkeypatch, capsys):
    from inpmap.input_config import Device

    devices = [Device("event7", "Kbd", ("g",), "keyboard", 100, ("/dev/input/by-id/kbd",))]
    linux_setup = pytest.importorskip("inpmap.backends.linux_setup")
    monkeypatch.setattr(linux_setup, "devices_for_input_config", lambda: devices)
    answers = iter(["1", "w"])
    monkeypatch.setattr("builtins.input", lambda prompt: next(answers))
    assert main(["input-config", "example"]) == EXIT_OK
    text = (config_home / "example.inpmap").read_text()
    assert text.startswith("# InpMap example")
    assert 'version 1\n\ninput kbd {\n    path = "/dev/input/by-id/kbd"\n}\n' in text
    assert "Check: OK." in capsys.readouterr().out


def test_syntax_file_command(capsys):
    assert main(["syntax-file", "nano"]) == EXIT_OK
    assert "syntax inpmap" in capsys.readouterr().out

import json
from pathlib import Path

import pytest

from inpmap.cli import EXIT_CONFIG_ERROR, EXIT_OK, main

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


def test_missing_command_is_usage_error():
    with pytest.raises(SystemExit) as info:
        main([])
    assert info.value.code == 2

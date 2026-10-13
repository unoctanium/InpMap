from pathlib import Path

import pytest

from inpmap.cli import EXIT_OK, EXIT_USAGE, main
from inpmap.config import parse_config
from inpmap.macros import Led
from inpmap.trace import format_trace, trace

CONFIG = parse_config(
    {
        "version": 1,
        "inputs": {"kbd": {"name": "Demo"}},
        "outputs": {"keyboard": {"type": "keyboard"}, "gamepad": {"type": "gamepad"}},
        "mappings": [
            {
                "id": "combo",
                "input": {"device": "kbd", "type": "key", "code": "KEY_F1"},
                "outputs": [
                    {
                        "macro": {
                            "steps": [
                                {"tap": {"code": "KEY_Q", "device": "keyboard"}},
                                {"wait_ms": {"min": 40, "max": 60}},
                                {"tap": {"code": "BTN_EAST", "device": "gamepad"}},
                            ]
                        }
                    }
                ],
            },
            {
                "id": "caps",
                "input": {"device": "kbd", "type": "key", "code": "KEY_CAPSLOCK"},
                "outputs": [
                    {
                        "macro": {
                            "device": "keyboard",
                            "steps": [
                                {
                                    "if_single": {
                                        "then": [{"tap": "KEY_ESC"}],
                                        "else": [{"hold_keys": "KEY_LEFTCTRL"}],
                                    }
                                }
                            ],
                        }
                    }
                ],
            },
            {
                "id": "led",
                "input": {"device": "kbd", "type": "key", "code": "KEY_F2"},
                "outputs": [
                    {
                        "macro": {
                            "device": "keyboard",
                            "steps": [
                                {
                                    "if_led": {
                                        "led": "numlock",
                                        "then": [{"tap": "KEY_1"}],
                                        "else": [{"tap": "KEY_2"}],
                                    }
                                }
                            ],
                        }
                    }
                ],
            },
        ],
    }
)


def texts(lines):
    return [(round(line.ms, 1), " ".join(line.text.split())) for line in lines]


def test_combo_timeline_is_deterministic_per_seed():
    first = texts(trace(CONFIG, "combo", seed=3))
    assert first == texts(trace(CONFIG, "combo", seed=3))
    assert first[:3] == [
        (0.0, ">> input pressed"),
        (0.0, "keyboard KEY_Q down"),
        (10.0, "keyboard KEY_Q up"),
    ]
    east_down = next(ms for ms, text in first if text == "gamepad BTN_EAST down")
    assert 60.0 <= east_down <= 80.0


def test_if_single_with_other_key():
    lines = texts(trace(CONFIG, "caps", hold_ms=300, other_key_at=[100]))
    assert (100.0, "keyboard KEY_LEFTCTRL down") in lines
    assert lines[-1] == (300.0, "keyboard KEY_LEFTCTRL up")


def test_if_single_alone_and_until():
    lines = texts(trace(CONFIG, "caps", hold_ms=50, until_ms=1000))
    assert (50.0, "keyboard KEY_ESC down") in lines


def test_leds_and_repeated_presses():
    lit = texts(trace(CONFIG, "led", leds=frozenset({Led.NUMLOCK}), press_at=[0, 500]))
    assert [t for _ms, t in lit if t.endswith("down")] == ["keyboard KEY_1 down"] * 2


def test_unknown_mapping():
    with pytest.raises(ValueError, match="unknown mapping 'nope'"):
        trace(CONFIG, "nope")


def test_format():
    assert format_trace(trace(CONFIG, "combo")).splitlines()[0] == "      0.0 ms  >> input pressed"


def test_cli(tmp_path: Path, capsys):
    import json

    path = tmp_path / "c.json"
    path.write_text(
        json.dumps(
            {
                "version": 1,
                "inputs": {"kbd": {"name": "Demo"}},
                "outputs": {"keyboard": {"type": "keyboard"}},
                "mappings": [
                    {
                        "id": "m",
                        "input": {"device": "kbd", "type": "key", "code": "KEY_X"},
                        "outputs": [{"macro": {"device": "keyboard", "steps": [{"tap": "KEY_A"}]}}],
                    }
                ],
            }
        )
    )
    assert main(["macro-trace", str(path), "m", "--hold-ms", "50"]) == EXIT_OK
    assert "keyboard   KEY_A            down" in capsys.readouterr().out
    assert main(["macro-trace", str(path), "x"]) == EXIT_USAGE

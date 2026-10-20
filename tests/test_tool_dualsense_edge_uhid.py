"""The test tool tools/dualsense_edge_uhid.py presses buttons the emulated pad has."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

from inpmap.backends.linux_uhid import BUTTON_BITS
from inpmap.codes import CODES

_PATH = Path(__file__).resolve().parent.parent / "tools" / "dualsense_edge_uhid.py"
if not _PATH.exists():  # e.g. tests run from the source distribution
    pytest.skip("tools/ is not part of the source distribution", allow_module_level=True)
_spec = importlib.util.spec_from_file_location("dualsense_edge_uhid", _PATH)
tool = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(tool)


def test_every_button_of_the_tool_has_a_bit_on_the_emulated_pad():
    assert set(tool.DEFAULT_SEQUENCE) == set(tool.BUTTONS)
    for code_name, _ in tool.BUTTONS.values():
        assert CODES[code_name] in BUTTON_BITS


def test_defaults():
    args = tool.parse_args([])
    assert (args.hold, args.gap, args.rounds, args.idle) == (1.0, 1.0, 0, False)

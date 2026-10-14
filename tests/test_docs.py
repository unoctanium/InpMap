"""The examples in the user documentation are valid and behave as described."""

import re
from pathlib import Path

import pytest
from golden_example_traces import SCENARIOS, TIMELINES

from inpmap.dsl.compiler import compile_text
from inpmap.dsl.parser import parse
from inpmap.trace import trace

ROOT = Path(__file__).resolve().parent.parent
REFERENCE = ROOT / "docs" / "configuration.md"
EXAMPLE = ROOT / "src" / "inpmap" / "data" / "example.inpmap"
# The example of the JSON era; its behaviour was verified on real hardware
# and recorded in golden_example_traces.py. Kept to check the engine.
JSON_ERA_EXAMPLE = ROOT / "tests" / "data" / "json_era_example.inpmap"

# Context for fragments that contain only mappings and variables. The anchor
# keeps both outputs in use.
HEADER = """version 1
input kbd { name = "Kbd" }
output keyboard { type = keyboard }
output gamepad { type = gamepad }
"""
ANCHOR = "\nmap KEY_F24 { hold KEY_F23; hold BTN_MODE }\n"


def inpmap_blocks(path: Path = REFERENCE) -> list[str]:
    """Code blocks marked ```inpmap; each must be valid as written."""
    return re.findall(r"```inpmap\n(.*?)```", path.read_text(), re.S)


def section(title: str) -> str:
    """The first ```inpmap block after a heading or sentence starting with `title`."""
    match = re.search(re.escape(title) + r".*?```inpmap\n(.*?)```", REFERENCE.read_text(), re.S)
    assert match, title
    return match.group(1)


def test_reference_has_examples():
    assert len(inpmap_blocks()) >= 15


@pytest.mark.parametrize("block", inpmap_blocks())
def test_reference_examples_parse_and_compile(block):
    parse(block, "reference")
    if block.lstrip("# \n").startswith("version") or "\nversion 1" in block:
        compile_text(block, "reference.inpmap")
    elif not re.search(r"^(input|output|settings) ", block, re.M):
        compile_text(HEADER + block + ANCHOR, "reference.inpmap")


def test_readme_example_compiles():
    (block,) = inpmap_blocks(ROOT / "README.md")
    compile_text(block, "readme.inpmap")


def test_example_file_is_the_complete_example():
    assert EXAMPLE.read_text() == section("## 10. Complete example")


@pytest.mark.parametrize("mapping, scenario_index", sorted(TIMELINES))
def test_json_era_example_matches_reference_timelines(mapping, scenario_index):
    """Behaviour of the former example equals the verified JSON version."""
    config = compile_text(JSON_ERA_EXAMPLE.read_text(), "example.inpmap").config
    scenario = SCENARIOS[scenario_index]
    actual = [(t.ms, t.text) for t in trace(config, mapping, seed=7, **scenario)]
    assert actual == TIMELINES[(mapping, scenario_index)]


def test_more_examples_names():
    config = compile_text(section("A keyboard and a gamepad as inputs"), "more.inpmap").config
    assert "pad.BTN_SOUTH+ctrl" in [m.id for m in config.mappings]
    config = compile_text(section("A key combination replaced"), "more.inpmap").config
    assert [m.id for m in config.mappings] == ["bracket_combo", "alternate"]


def test_documented_one_line_alternation():
    """§6.8: the two `if`s alternate between A and B."""
    config = compile_text(HEADER + section("### 6.8") + ANCHOR, "t.inpmap").config
    lines = [t.text for t in trace(config, "KEY_F12", press_at=[0, 200], hold_ms=50)]
    taps = [line.split()[1] for line in lines if line.endswith("down")]
    assert taps == ["KEY_B", "KEY_A"]


def test_examples_are_formatted():
    """`inpmap fmt` would leave every documented example as it is."""
    from inpmap.dsl.formatter import format_text

    for block in inpmap_blocks() + inpmap_blocks(ROOT / "README.md"):
        assert format_text(block) == block, block
    for path in (EXAMPLE, JSON_ERA_EXAMPLE):
        assert format_text(path.read_text()) == path.read_text(), path

"""Reusable blocks: block and call (docs/configuration.md §6.11)."""

import pytest

from inpmap.config import ConfigError
from inpmap.dsl.compiler import compile_text
from inpmap.trace import trace

HEADER = """version 1
input kbd { name = "K" }
output keyboard { type = keyboard }
"""


def config(text):
    return compile_text(HEADER + text, "t.inpmap")


def timeline(text, mapping, **scenario):
    return [(t.ms, t.text) for t in trace(config(text).config, mapping, seed=1, **scenario)]


def problems(text):
    with pytest.raises(ConfigError) as info:
        config(text)
    return info.value.problems


INLINE = """
map KEY_F1 {
    tap KEY_A
    hold KEY_B
    while held { tap KEY_C (pause 20ms) }
    on release { wait 30ms; tap KEY_D }
}
"""
WITH_BLOCKS = """
block start { tap KEY_A; hold KEY_B }
block loop { while held { tap KEY_C (pause 20ms) } }
block finish { wait 30ms; tap KEY_D }
block everything { call start; call loop }
map KEY_F1 {
    call everything
    on release { call finish }
}
"""


def test_a_call_behaves_as_if_the_statements_were_written_there():
    """Same timeline, including the non-blocking hold across the block boundary."""
    expected = timeline(INLINE, "KEY_F1", hold_ms=100)
    assert timeline(WITH_BLOCKS, "KEY_F1", hold_ms=100) == expected
    assert any("KEY_C" in text for _, text in expected)


def test_calls_inside_conditions_loops_and_parallel():
    text = """
block one { tap KEY_1 }
let flag = true
map KEY_F2 {
    if flag { call one } else { tap KEY_2 }
    repeat 2 { call one }
    parallel { branch { call one }; branch { tap KEY_3 } }
}
"""
    downs = [t for _, t in timeline(text, "KEY_F2") if t.endswith("down")]
    assert [d.split()[1] for d in downs] == ["KEY_1", "KEY_1", "KEY_1", "KEY_1", "KEY_3"]


def test_unused_block_is_a_warning():
    result = config("block spare { tap KEY_A }\nmap KEY_X { tap KEY_B }\n")
    assert result.warnings == ["t.inpmap:4:7: warning: block 'spare' is never called"]


@pytest.mark.parametrize(
    "text, message",
    [
        ("map KEY_X { call nope }\n", "t.inpmap:4:18: unknown block 'nope'"),
        (
            "block a { tap KEY_A }\nblock a { tap KEY_B }\nmap KEY_X { call a }\n",
            "t.inpmap:5:7: block 'a' is already defined at line 4",
        ),
        ("block a { call a }\nmap KEY_X { call a }\n", "block 'a' calls itself"),
        (
            "block a { if x { call b } }\nblock b { call a }\nlet x = true\nmap KEY_X { call a }\n",
            "block 'a' calls itself",
        ),
        (
            "block a { cancel on release }\nmap KEY_X { call a }\n",
            "a mapping option is not allowed",
        ),
        ("block a { on release { tap KEY_A } }\nmap KEY_X { call a }\n", "'on release' is not"),
        ("block a { toggle { tap KEY_A } }\nmap KEY_X { call a }\n", "'toggle' is not allowed"),
        ("block a { disable }\nmap KEY_X { call a }\n", "'disable' is not allowed"),
        ("block call { tap KEY_A }\nmap KEY_X { tap KEY_A }\n", "unexpected"),
    ],
)
def test_block_errors(text, message):
    found = problems(text)
    assert any(message in p for p in found), found


def test_errors_inside_a_block_are_reported_once_at_the_block():
    found = problems(
        "block bad { tap KEY_QQ }\nmap KEY_X { call bad }\nmap KEY_Y { call bad; call bad }\n"
    )
    assert [p for p in found if "KEY_QQ" in p] == [
        "t.inpmap:4:17: unknown key code 'KEY_QQ' (did you mean 'KEY_Q'?)"
    ]

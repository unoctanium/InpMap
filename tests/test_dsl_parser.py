import pytest

from inpmap.dsl.parser import DslSyntaxError, parse


def kinds(tree):
    return [child.data for child in tree.children]


def test_top_level_structure():
    tree = parse(
        """
version 1
settings { key_pause = 10ms; modifiers = ctrl, alt }
let n = 0
input kbd { name = "Kbd" }
output keyboard { type = keyboard }
map KEY_X modifiers(ctrl, right_shift) as x_map { tap KEY_A }
"""
    )
    assert kinds(tree) == ["version", "settings", "let_stmt", "input_def", "output_def", "map_def"]


def test_statements():
    tree = parse(
        """
map KEY_X {
    cancel on release
    restart on press
    keep modifiers
    key_pause 5ms
    max_run none
    hold KEY_A + gamepad.BTN_SOUTH
    tap ctrl + KEY_C (pause 30ms)
    press KEY_B
    release KEY_B (pause 0ms)
    with KEY_LEFTSHIFT { tap KEY_A }
    axis ABS_Y { target = -1.0; attack = 150ms; release = 50ms }
    axis ABS_X 1.0 (attack 10ms, release 20ms)
    move ABS_X to 0.5 over 1s
    wait random(40ms, 60ms)
    wait delay
    repeat 3 { tap KEY_A }
    repeat n { tap KEY_A }
    while held { tap KEY_A }
    parallel { branch { wait 1ms }; branch { wait 2ms } }
    n += 1
    n -= 1
    flag = true
    on release { tap KEY_ENTER }
}
map KEY_Y { toggle { tap KEY_A } }
map KEY_Z {
    on tap within 200ms { tap KEY_1 }
    on double_tap { tap KEY_2 }
    on long_press after 200ms { tap KEY_3 }
}
"""
    )
    body = tree.children[0].children[-1]
    assert [s.data for s in body.children] == [
        "opt_cancel",
        "opt_restart",
        "opt_keep",
        "opt_kv",
        "opt_kv",
        "hold",
        "tap",
        "press",
        "release",
        "with",
        "axis",
        "axis",
        "move",
        "wait",
        "wait",
        "repeat",
        "repeat",
        "while_held",
        "parallel",
        "augassign",
        "augassign",
        "assign",
        "on_release",
    ]


def test_conditions_and_else_on_new_line():
    tree = parse(
        """
map KEY_X {
    if tap within 200ms { tap KEY_1 }
    else if single { tap KEY_2 }
    # a comment between
    else if not capslock { tap KEY_3 }
    else if mode == 2 { tap KEY_4 }
    else if mode != "a" { tap KEY_5 }
    else if flag { tap KEY_6 }
    else { tap KEY_7 }
}
"""
    )
    if_stmt = tree.children[0].children[-1].children[0]
    assert if_stmt.data == "if_stmt"
    assert [c.data for c in if_stmt.children if hasattr(c, "data")] == [
        "cond_tap",
        "block",
        "else_if",
        "else_if",
        "else_if",
        "else_if",
        "else_if",
        "else_block",
    ]


def test_positions_are_kept():
    tree = parse("version 1\n\nmap KEY_X {\n    tap KEY_A\n}\n")
    tap = tree.children[1].children[-1].children[0]
    assert (tap.meta.line, tap.meta.column) == (4, 5)


@pytest.mark.parametrize(
    "text, line, column, message",
    [
        ("version 1\nmap KEY_X { tap KEY_A $ }", 2, 23, "unexpected character '$'"),
        ("version 1\nmap KEY_X {\n  tap KEY_A\n", 4, 1, "missing '}'"),
        ("map KEY_X {\n wait 10\n}", 2, 7, "unexpected '10'"),
        ("map KEY_X { tap }", 1, 17, "unexpected '}'"),
        ("map KEY_X { if x { tap KEY_A } else }", 1, 37, "unexpected '}'"),
        ("map KEY_X {\n  tap KEY_A KEY_B\n}", 2, 13, "unexpected 'KEY_B'"),
    ],
)
def test_syntax_errors(text, line, column, message):
    with pytest.raises(DslSyntaxError) as info:
        parse(text, "t.inpmap")
    error = info.value
    assert (error.line, error.column) == (line, column)
    assert message in error.message
    assert str(error).startswith(f"t.inpmap:{line}:{column}: ")


def test_durations_need_a_unit_and_no_space():
    with pytest.raises(DslSyntaxError):
        parse("map KEY_X { wait 10 ms }")
    parse("map KEY_X { wait 1.5s }")

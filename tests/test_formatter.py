"""`inpmap fmt` layout rules (docs/usage.md, `inpmap fmt`)."""

import pytest

from inpmap.dsl.formatter import format_text
from inpmap.dsl.parser import DslSyntaxError, parse


def fmt(text: str) -> str:
    result = format_text(text, "t.inpmap")
    assert format_text(result, "t.inpmap") == result  # idempotent
    assert parse(result) == parse(text)  # same meaning
    return result


def test_indentation_one_statement_per_line_and_spacing():
    source = (
        "version   1\n"
        "map KEY_X modifiers( ctrl ,shift ) as  x {\n"
        "\ttap ctrl+KEY_C ( pause 30ms ,release 5ms ) ; wait random( 40ms ,60ms )\n"
        "   n+=1\n"
        "}\n"
    )
    assert fmt(source) == (
        "version 1\n"
        "map KEY_X modifiers(ctrl, shift) as x {\n"
        "    tap ctrl + KEY_C (pause 30ms, release 5ms)\n"
        "    wait random(40ms, 60ms)\n"
        "    n += 1\n"
        "}\n"
    )


def test_one_line_blocks_stay_only_if_written_so_with_one_simple_statement():
    source = (
        "version 1\n"
        "map KEY_A { tap KEY_B }\n"
        "map KEY_C {\n    tap KEY_D\n}\n"
        "map KEY_E { tap KEY_F; tap KEY_G }\n"
        "map KEY_H { while held { tap KEY_I } }\n"
        "output gamepad {   type = gamepad   }\n"
    )
    assert fmt(source) == (
        "version 1\n"
        "map KEY_A { tap KEY_B }\n"
        "map KEY_C {\n    tap KEY_D\n}\n"
        "map KEY_E {\n    tap KEY_F\n    tap KEY_G\n}\n"
        "map KEY_H {\n    while held { tap KEY_I }\n}\n"
        "output gamepad { type = gamepad }\n"
    )


def test_one_line_block_longer_than_100_characters_is_split():
    long_name = "x" * 90
    source = f'version 1\ninput kbd {{ name = "{long_name}" }}\n'
    assert fmt(source) == f'version 1\ninput kbd {{\n    name = "{long_name}"\n}}\n'


def test_else_and_if_chains():
    source = (
        "version 1\nmap KEY_A {\n    if capslock { tap KEY_1 }\n    else if numlock {\n"
        "        tap KEY_2\n    }\n    else { tap KEY_3 }\n}\n"
        "map KEY_B { if tap { tap KEY_1 } else { tap KEY_2 } }\n"
    )
    assert fmt(source) == (
        "version 1\nmap KEY_A {\n    if capslock {\n        tap KEY_1\n    } else if numlock {\n"
        "        tap KEY_2\n    } else {\n        tap KEY_3\n    }\n}\n"
        "map KEY_B {\n    if tap { tap KEY_1 } else { tap KEY_2 }\n}\n"
    )


def test_blank_lines_kept_but_collapsed_and_trimmed():
    source = (
        "\n\nversion 1\n\n\n\nlet a = 1\nlet b = 2\n\nmap KEY_A {\n\n    tap KEY_B\n\n"
        "    tap KEY_C\n\n}\n\n\n"
    )
    assert fmt(source) == (
        "version 1\n\nlet a = 1\nlet b = 2\n\nmap KEY_A {\n    tap KEY_B\n\n    tap KEY_C\n}\n"
    )


def test_comments_are_kept_indented_and_aligned():
    source = (
        "# header\n"
        "version 1  # the version\n"
        "map KEY_A {   # opening\n"
        "  # before B\n"
        "  tap KEY_B # b\n"
        "  tap KEY_CCCCC         # c\n"
        "  # last inside\n"
        "}  # closing\n"
        "map KEY_X { tap KEY_Y; tap KEY_Z }   # one-line, split\n"
    )
    assert fmt(source) == (
        "# header\n"
        "version 1    # the version\n"  # consecutive with the next line: aligned
        "map KEY_A {  # opening\n"
        "    # before B\n"
        "    tap KEY_B      # b\n"
        "    tap KEY_CCCCC  # c\n"
        "    # last inside\n"
        "}            # closing\n"
        "map KEY_X {  # one-line, split\n"
        "    tap KEY_Y\n"
        "    tap KEY_Z\n"
        "}\n"
    )


def test_equals_signs_aligned_in_property_blocks_only():
    source = (
        "version 1\nsettings {\n    key_pause = 10ms\n    modifiers = ctrl, alt\n}\n"
        'output keyboard {\n    type = keyboard\n    name = "K"\n}\n'
        "map KEY_A {\n    axis ABS_Y {\n        target = -1.0\n        attack = 150ms\n"
        "        release = 50ms\n    }\n}\n"
    )
    result = fmt(source)
    assert "        target  = -1.0\n        attack  = 150ms\n        release = 50ms\n" in result
    assert '    type = keyboard\n    name = "K"\n' in result
    assert "    key_pause = 10ms\n    modifiers = ctrl, alt\n" in result


def test_gestures_are_not_aligned():
    source = (
        "version 1\nmap KEY_A {\n    on tap        { tap KEY_1 }\n"
        "    on long_press after 400ms { tap KEY_3 }\n}\n"
    )
    assert fmt(source) == (
        "version 1\nmap KEY_A {\n    on tap { tap KEY_1 }\n"
        "    on long_press after 400ms { tap KEY_3 }\n}\n"
    )


def test_everything_else_is_kept_as_written():
    source = (
        'version 1\nlet d = 1.5s\nlet s = "a \\"b\\""\n'
        "map pad.ABS_RZ above 0.5 modifiers(ignore) { move gamepad.ABS_X to -1.0 over d }\n"
        "layer nav {\n  map KEY_W { hold layer nav }\n  map KEY_Q { disable }\n}\n"
        "block b { call c; layer nav toggle; if not layer nav { x = true } }\n"
        "block c { parallel { branch { wait 1ms }; branch { wait 2ms } } }\n"
    )
    result = fmt(source)
    assert "let d = 1.5s\n" in result and 'let s = "a \\"b\\""\n' in result
    assert "map pad.ABS_RZ above 0.5 modifiers(ignore) { move gamepad.ABS_X to -1.0 over d }" in (
        result
    )
    assert "layer nav {\n    map KEY_W { hold layer nav }\n    map KEY_Q { disable }\n}\n" in result


def test_syntax_errors_are_reported_not_formatted():
    with pytest.raises(DslSyntaxError):
        format_text("version 1\nmap {\n", "t.inpmap")

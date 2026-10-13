"""Parser for the InpMap configuration language (docs/dsl.md §2–§5).

Produces a lark parse tree with source positions. Only syntax is checked
here; names, codes, types and all other rules are checked by the compiler.
Keywords that only matter semantically (e.g. ``double_tap``, ``capslock``,
``ctrl``, ``true``, ``none``) are ordinary names to the parser; the compiler
gives them meaning and rejects them where a user-chosen name is expected.
"""

from __future__ import annotations

from collections.abc import Iterator

from lark import Lark, Token, Tree
from lark.exceptions import UnexpectedCharacters, UnexpectedEOF, UnexpectedInput, UnexpectedToken

GRAMMAR = r"""
start: _sep? (top_stmt (_sep top_stmt)*)? _sep?

?top_stmt: version | settings | let_stmt | input_def | output_def | map_def

version: "version" NUMBER
settings: "settings" props
let_stmt: "let" NAME "=" value
input_def: "input" NAME props
output_def: "output" NAME props

props: "{" _sep? (prop (_sep prop)*)? _sep? "}"
prop: prop_name "=" value ("," value)*
!prop_name: NAME | "release" | "modifiers"

map_def: "map" ref modifiers? as_name? block
modifiers: "modifiers" "(" _nl? NAME ("," _nl? NAME)* _nl? ")"
as_name: "as" NAME

block: "{" _sep? (stmt (_sep stmt)*)? _sep? "}"

?stmt: hold | tap | press | release | with | axis | move | wait | repeat
     | while_held | toggle | parallel | if_stmt | gesture | on_release
     | assign | augassign | opt_cancel | opt_restart | opt_keep | opt_kv

hold: "hold" keys
tap: "tap" keys options?
press: "press" keys options?
release: "release" keys options?
with: "with" keys block
axis: "axis" ref (props | NUMBER options?)
move: "move" ref "to" NUMBER ("over" duration)?
wait: "wait" duration
repeat: "repeat" (NUMBER | NAME) block
while_held: "while" "held" block
toggle: "toggle" block
parallel: "parallel" "{" _sep? (branch (_sep branch)*)? _sep? "}"
branch: "branch" block
if_stmt: "if" cond block else_if* else_block?
else_if: "else" "if" cond block
else_block: "else" block
gesture: "on" gesture_name window? block
!gesture_name: "tap" | NAME
window: (WITHIN | AFTER) duration
on_release: "on" "release" block
assign: NAME "=" value
augassign: NAME AUGOP value
opt_cancel: "cancel" "on" "release"
opt_restart: "restart" "on" "press"
opt_keep: "keep" "modifiers"
opt_kv: NAME value

options: "(" _nl? option ("," _nl? option)* _nl? ")"
option: (NAME | RELEASE_KW) duration

?cond: "not" cond -> cond_not
     | "tap" within? -> cond_tap
     | "single" within? -> cond_single
     | NAME "==" value -> cond_eq
     | NAME "!=" value -> cond_ne
     | NAME -> cond_name
within: WITHIN duration

keys: ref ("+" ref)*
ref: NAME ("." NAME)?

duration: DURATION -> dur_literal
        | "random" "(" _nl? duration "," _nl? duration _nl? ")" -> dur_random
        | NAME -> dur_var

?value: NUMBER -> v_number
      | DURATION -> v_duration
      | STRING -> v_string
      | NAME -> v_name

_sep: (_NL | ";")+
_nl: _NL+

WITHIN: "within"
AFTER: "after"
RELEASE_KW: "release"
AUGOP: "+=" | "-="
DURATION.3: /\d+(\.\d+)?(ms|s)(?![A-Za-z0-9_])/
NUMBER.2: /-?\d+(\.\d+)?(?![A-Za-z0-9_])/
STRING: /"(\\.|[^"\\\n])*"/
NAME: /[A-Za-z_][A-Za-z0-9_]*/
_NL: /(\r?\n)+/
COMMENT: /#[^\n]*/

%import common.WS_INLINE
%ignore WS_INLINE
%ignore COMMENT
"""

# Literal tokens shown in messages by their text instead of lark's names.
_TOKEN_TEXT = {
    "_NL": "line break",
    "$END": "end of file",
    "NAME": "a name",
    "NUMBER": "a number",
    "DURATION": "a duration like 10ms",
    "STRING": "a string",
    "LBRACE": "'{'",
    "RBRACE": "'}'",
    "LPAR": "'('",
    "RPAR": "')'",
    "EQUAL": "'='",
    "COMMA": "','",
    "DOT": "'.'",
    "PLUS": "'+'",
    "SEMICOLON": "';'",
    "AUGOP": "'+=' or '-='",
}


class ElseJoiner:
    """Post-lexer: drop line breaks directly before ``else``.

    Allows ``}`` and ``else`` on separate lines without making the LALR
    grammar ambiguous (a line break otherwise ends a statement).
    """

    always_accept = ("_NL",)

    def process(self, stream: Iterator[Token]) -> Iterator[Token]:
        pending: Token | None = None
        for token in stream:
            if token.type == "_NL":
                pending = token
                continue
            if pending is not None and token.type != "ELSE":
                yield pending
            pending = None
            yield token
        if pending is not None:
            yield pending


_PARSER = Lark(
    GRAMMAR,
    parser="lalr",
    # The basic (not contextual) lexer: the post-lexer holds back line
    # breaks, which a parser-state-dependent lexer cannot cope with.
    lexer="basic",
    propagate_positions=True,
    postlex=ElseJoiner(),
    maybe_placeholders=False,
)


class DslSyntaxError(Exception):
    """A syntax error with its position."""

    def __init__(self, source: str, line: int, column: int, message: str) -> None:
        self.source = source
        self.line = line
        self.column = column
        self.message = message
        super().__init__(f"{source}:{line}:{column}: {message}")


def parse(text: str, source: str = "<config>") -> Tree:
    """Parse configuration text; raise DslSyntaxError on the first syntax error."""
    try:
        return _PARSER.parse(text)
    except UnexpectedInput as exc:
        raise _syntax_error(exc, text, source) from None


def _syntax_error(exc: UnexpectedInput, text: str, source: str) -> DslSyntaxError:
    line = getattr(exc, "line", None) or 1
    column = getattr(exc, "column", None) or 1
    if isinstance(exc, UnexpectedCharacters):
        char = text[exc.pos_in_stream] if exc.pos_in_stream < len(text) else "?"
        return DslSyntaxError(source, line, column, f"unexpected character {char!r}")
    if isinstance(exc, UnexpectedEOF):
        return DslSyntaxError(source, line, column, "unexpected end of file (missing '}'?)")
    if isinstance(exc, UnexpectedToken):
        token = exc.token
        found = "end of file" if token.type == "$END" else f"{token.value!r}"
        if token.type == "_NL":
            found = "line break"
        if token.type == "$END":
            line, column = _end_position(text)
            if "RBRACE" in exc.expected:
                return DslSyntaxError(source, line, column, "unexpected end of file: missing '}'")
        expected = sorted({_describe(name) for name in exc.expected})
        hint = f"; expected {', '.join(expected[:8])}" if expected else ""
        return DslSyntaxError(source, line, column, f"unexpected {found}{hint}")
    return DslSyntaxError(source, line, column, str(exc).splitlines()[0])


def _describe(token_name: str) -> str:
    if token_name in _TOKEN_TEXT:
        return _TOKEN_TEXT[token_name]
    pattern = _PARSER.get_terminal(token_name).pattern
    if pattern.type == "str":
        return f"'{pattern.value}'"
    return token_name.lower()


def _end_position(text: str) -> tuple[int, int]:
    lines = text.split("\n")
    return len(lines), len(lines[-1]) + 1

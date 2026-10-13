"""Parser for the InpMap configuration language (docs/dsl.md §2–§5).

The grammar is in ``inpmap.lark`` next to this module.

Produces a lark parse tree with source positions. Only syntax is checked
here; names, codes, types and all other rules are checked by the compiler.
Keywords that only matter semantically (e.g. ``double_tap``, ``capslock``,
``ctrl``, ``true``, ``none``) are ordinary names to the parser; the compiler
gives them meaning and rejects them where a user-chosen name is expected.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

from lark import Lark, Token, Tree
from lark.exceptions import UnexpectedCharacters, UnexpectedEOF, UnexpectedInput, UnexpectedToken

GRAMMAR_FILE = Path(__file__).with_name("inpmap.lark")

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
    GRAMMAR_FILE.read_text(encoding="utf-8"),
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

"""`inpmap fmt`: lay out configuration text consistently (docs/usage.md, `inpmap fmt`).

The text is parsed, every statement is rendered from the parse tree with
fixed spacing rules, and the comments (which the parser ignores) are put
back by their line numbers. ``format_text`` refuses to return a result
that does not parse to the same tree, so formatting can never change what
a configuration means.
"""

from __future__ import annotations

import functools
from collections.abc import Callable
from dataclasses import dataclass

from lark import Lark, Token, Tree
from lark.exceptions import UnexpectedInput

from .parser import GRAMMAR_FILE, DslSyntaxError, ElseJoiner, parse

INDENT = "    "
MAX_LINE = 100
# Statements that contain a block of their own: never on one line inside another block.
NESTED = {
    "with",
    "repeat",
    "while_held",
    "toggle",
    "parallel",
    "if_stmt",
    "gesture",
    "on_release",
    "map_def",
}


class FormatError(Exception):
    """The text cannot be formatted safely."""


@dataclass
class Line:
    indent: int
    text: str
    src: int  # source line this output line stands for
    prop: tuple[int, str, str] | None = None  # (group, name, rest) for '=' alignment
    comment: str | None = None  # trailing comment


@dataclass
class Comment:
    line: int
    text: str
    own_line: bool  # nothing but whitespace before it on its line


def format_text(text: str, source: str = "<config>") -> str:
    """The formatted text; raises DslSyntaxError or FormatError."""
    comments: list[Token] = []
    tree = _parse_with_comments(text, source, comments)
    lines = text.splitlines()
    notes = [
        Comment(t.line, str(t), not lines[t.line - 1][: t.column - 1].strip()) for t in comments
    ]
    rendered = _Renderer().top(tree)
    result = _assemble(rendered, notes, lines)
    if parse(result, source) != tree:  # pragma: no cover - a renderer bug
        raise FormatError(f"{source}: formatting would change the configuration; file left as is")
    if _comment_texts(result, source) != [c.text for c in notes]:  # pragma: no cover
        raise FormatError(f"{source}: formatting would lose a comment; file left as is")
    return result


class _CommentParser:
    """The grammar's parser, collecting the comments it otherwise ignores."""

    def __init__(self) -> None:
        self.comments: list[Token] = []
        self.lark = Lark(
            GRAMMAR_FILE.read_text(encoding="utf-8"),
            parser="lalr",
            lexer="basic",
            propagate_positions=True,
            postlex=ElseJoiner(),
            maybe_placeholders=False,
            lexer_callbacks={"COMMENT": self.comments.append},
        )


@functools.cache
def _comment_parser() -> _CommentParser:
    return _CommentParser()


def _parse_with_comments(text: str, source: str, comments: list[Token]) -> Tree:
    parser = _comment_parser()
    parser.comments.clear()
    try:
        tree = parser.lark.parse(text)
    except UnexpectedInput:
        parse(text, source)  # raises DslSyntaxError with the usual message
        raise  # pragma: no cover
    comments += parser.comments
    return tree


def _comment_texts(text: str, source: str) -> list[str]:
    found: list[Token] = []
    _parse_with_comments(text, source, found)
    return [str(t) for t in found]


# -- rendering ------------------------------------------------------------------------------


def _line(node: Tree | Token) -> int:
    return node.line if isinstance(node, Token) else node.meta.line


def _end_line(node: Tree) -> int:
    return node.meta.end_line


class _Renderer:
    def __init__(self) -> None:
        self.groups = 0

    def top(self, tree: Tree) -> list[Line]:
        lines: list[Line] = []
        for stmt in tree.children:
            lines += self.statement(stmt, 0)
        return lines

    # Each statement renders to lines; `inline` renders it as one string.
    def statement(self, stmt: Tree, indent: int) -> list[Line]:
        method: Callable = getattr(self, f"s_{stmt.data}", None) or self.simple
        return method(stmt, indent)

    def simple(self, stmt: Tree, indent: int) -> list[Line]:
        return [Line(indent, self.inline(stmt), _line(stmt))]

    def inline(self, stmt: Tree) -> str:
        return getattr(self, f"i_{stmt.data}")(stmt)

    # -- blocks -------------------------------------------------------------------

    def one_line_block(self, block: Tree) -> str | None:
        """`{ stmt }` if the block may stay on one line (rule 3), else None."""
        items = block.children
        if len(items) != 1 or block.meta.line != block.meta.end_line:
            return None
        item = items[0]
        if item.data in NESTED or (item.data == "axis" and _has_props(item)):
            return None
        return "{ " + (self.prop(item) if item.data == "prop" else self.inline(item)) + " }"

    def block(self, header: str, block: Tree, indent: int, src: int) -> list[Line]:
        short = self.one_line_block(block)
        if short is not None:
            line = f"{header} {short}"
            if len(INDENT * indent + line) <= MAX_LINE:
                return [Line(indent, line, src)]
        lines = [Line(indent, f"{header} {{", src)]
        lines += self.body(block.children, indent + 1)
        lines.append(Line(indent, "}", _end_line(block)))
        return lines

    def body(self, items: list[Tree], indent: int) -> list[Line]:
        lines: list[Line] = []
        group = self.new_group()
        for item in items:
            if item.data == "prop":
                name, rest = self.prop_parts(item)
                lines.append(Line(indent, f"{name} = {rest}", _line(item), (group, name, rest)))
            else:
                lines += self.statement(item, indent)
        return lines

    def new_group(self) -> int:
        self.groups += 1
        return self.groups

    def prop_parts(self, prop: Tree) -> tuple[str, str]:
        name_tree, *values = prop.children
        return str(name_tree.children[0]), ", ".join(self.value(v) for v in values)

    def prop(self, prop: Tree) -> str:
        name, rest = self.prop_parts(prop)
        return f"{name} = {rest}"

    # -- top-level statements -----------------------------------------------------------

    def i_version(self, stmt: Tree) -> str:
        return f"version {stmt.children[0]}"

    def s_settings(self, stmt: Tree, indent: int) -> list[Line]:
        return self.block("settings", stmt.children[0], indent, _line(stmt))

    def i_let_stmt(self, stmt: Tree) -> str:
        name, value = stmt.children
        return f"let {name} = {self.value(value)}"

    def s_input_def(self, stmt: Tree, indent: int) -> list[Line]:
        name, props = stmt.children
        return self.block(f"input {name}", props, indent, _line(stmt))

    def s_output_def(self, stmt: Tree, indent: int) -> list[Line]:
        name, props = stmt.children
        return self.block(f"output {name}", props, indent, _line(stmt))

    def s_map_def(self, stmt: Tree, indent: int) -> list[Line]:
        ref, *rest = stmt.children
        header = "map " + self.ref(ref)
        for part in rest[:-1]:
            if part.data == "threshold":
                direction, value = part.children
                header += f" {direction} {value}"
            elif part.data == "modifiers":
                header += " modifiers(" + ", ".join(str(t) for t in part.children) + ")"
            elif part.data == "as_name":
                header += f" as {part.children[0]}"
        return self.block(header, rest[-1], indent, _line(stmt))

    def s_block_def(self, stmt: Tree, indent: int) -> list[Line]:
        name, block = stmt.children
        return self.block(f"block {name}", block, indent, _line(stmt))

    def s_layer_def(self, stmt: Tree, indent: int) -> list[Line]:
        name, *maps = stmt.children
        if not maps:
            return [Line(indent, f"layer {name} {{ }}", _line(stmt))]
        lines = [Line(indent, f"layer {name} {{", _line(stmt))]
        for map_def in maps:
            lines += self.s_map_def(map_def, indent + 1)
        lines.append(Line(indent, "}", _end_line(stmt)))
        return lines

    # -- statements with blocks ---------------------------------------------------------

    def s_with(self, stmt: Tree, indent: int) -> list[Line]:
        keys, block = stmt.children
        return self.block(f"with {self.keys(keys)}", block, indent, _line(stmt))

    def s_repeat(self, stmt: Tree, indent: int) -> list[Line]:
        count, block = stmt.children
        return self.block(f"repeat {count}", block, indent, _line(stmt))

    def s_while_held(self, stmt: Tree, indent: int) -> list[Line]:
        return self.block("while held", stmt.children[0], indent, _line(stmt))

    def s_toggle(self, stmt: Tree, indent: int) -> list[Line]:
        return self.block("toggle", stmt.children[0], indent, _line(stmt))

    def s_on_release(self, stmt: Tree, indent: int) -> list[Line]:
        return self.block("on release", stmt.children[0], indent, _line(stmt))

    def s_gesture(self, stmt: Tree, indent: int) -> list[Line]:
        name, *rest = stmt.children
        header = f"on {name.children[0]}"
        if len(rest) == 2:
            word, duration = rest[0].children
            header += f" {word} {self.duration(duration)}"
        return self.block(header, rest[-1], indent, _line(stmt))

    def s_parallel(self, stmt: Tree, indent: int) -> list[Line]:
        if not stmt.children:
            return [Line(indent, "parallel { }", _line(stmt))]
        lines = [Line(indent, "parallel {", _line(stmt))]
        for branch in stmt.children:
            lines += self.block("branch", branch.children[0], indent + 1, _line(branch))
        lines.append(Line(indent, "}", _end_line(stmt)))
        return lines

    def s_if_stmt(self, stmt: Tree, indent: int) -> list[Line]:
        cond, block, *others = stmt.children
        parts = [(f"if {self.cond(cond)}", block, _line(stmt))]
        for other in others:
            if other.data == "else_if":
                other_cond, other_block = other.children
                parts.append((f"else if {self.cond(other_cond)}", other_block, _line(other)))
            else:
                parts.append(("else", other.children[0], _line(other)))
        shorts = [self.one_line_block(part[1]) for part in parts]
        if all(s is not None for s in shorts):
            line = " ".join(
                f"{head} {short}" for (head, _, _), short in zip(parts, shorts, strict=True)
            )
            if len(INDENT * indent + line) <= MAX_LINE:
                return [Line(indent, line, _line(stmt))]
        lines: list[Line] = []
        opener = ""
        for head, part_block, src in parts:
            lines.append(Line(indent, f"{opener}{head} {{", src))
            lines += self.body(part_block.children, indent + 1)
            opener = "} "
        lines.append(Line(indent, "}", _end_line(parts[-1][1])))
        return lines

    def s_axis(self, stmt: Tree, indent: int) -> list[Line]:
        if _has_props(stmt):
            ref, props = stmt.children
            return self.block(f"axis {self.ref(ref)}", props, indent, _line(stmt))
        return self.simple(stmt, indent)

    # -- one-line statements --------------------------------------------------------------

    def i_hold(self, stmt: Tree) -> str:
        return f"hold {self.keys(stmt.children[0])}"

    def _key_statement(self, word: str, stmt: Tree) -> str:
        keys, *options = stmt.children
        return f"{word} {self.keys(keys)}" + (f" {self.options(options[0])}" if options else "")

    def i_tap(self, stmt: Tree) -> str:
        return self._key_statement("tap", stmt)

    def i_press(self, stmt: Tree) -> str:
        return self._key_statement("press", stmt)

    def i_release(self, stmt: Tree) -> str:
        return self._key_statement("release", stmt)

    def i_axis(self, stmt: Tree) -> str:
        ref, number, *options = stmt.children
        text = f"axis {self.ref(ref)} {number}"
        return text + (f" {self.options(options[0])}" if options else "")

    def i_move(self, stmt: Tree) -> str:
        ref, number, *over = stmt.children
        text = f"move {self.ref(ref)} to {number}"
        return text + (f" over {self.duration(over[0])}" if over else "")

    def i_wait(self, stmt: Tree) -> str:
        return f"wait {self.duration(stmt.children[0])}"

    def i_assign(self, stmt: Tree) -> str:
        name, value = stmt.children
        return f"{name} = {self.value(value)}"

    def i_augassign(self, stmt: Tree) -> str:
        name, op, value = stmt.children
        return f"{name} {op} {self.value(value)}"

    def i_opt_cancel(self, stmt: Tree) -> str:
        return "cancel on release"

    def i_opt_restart(self, stmt: Tree) -> str:
        return "restart on press"

    def i_opt_keep(self, stmt: Tree) -> str:
        return "keep modifiers"

    def i_opt_kv(self, stmt: Tree) -> str:
        name, value = stmt.children
        return f"{name} {self.value(value)}"

    def i_disable(self, stmt: Tree) -> str:
        return "disable"

    def i_call(self, stmt: Tree) -> str:
        return f"call {stmt.children[0]}"

    def i_hold_layer(self, stmt: Tree) -> str:
        return f"hold layer {stmt.children[0]}"

    def i_layer_switch(self, stmt: Tree) -> str:
        name, action = stmt.children
        return f"layer {name} {action.children[0]}"

    # -- parts ----------------------------------------------------------------------------

    def ref(self, ref: Tree) -> str:
        return ".".join(str(t) for t in ref.children)

    def keys(self, keys: Tree) -> str:
        return " + ".join(self.ref(ref) for ref in keys.children)

    def options(self, options: Tree) -> str:
        parts = [f"{o.children[0]} {self.duration(o.children[1])}" for o in options.children]
        return "(" + ", ".join(parts) + ")"

    def duration(self, node: Tree) -> str:
        if node.data == "dur_random":
            low, high = node.children
            return f"random({self.duration(low)}, {self.duration(high)})"
        return str(node.children[0])

    def value(self, node: Tree) -> str:
        return str(node.children[0])

    def cond(self, node: Tree) -> str:
        kind = node.data
        if kind == "cond_not":
            return "not " + self.cond(node.children[0])
        if kind in ("cond_tap", "cond_single"):
            word = "tap" if kind == "cond_tap" else "single"
            if node.children:
                within_word, duration = node.children[0].children
                return f"{word} {within_word} {self.duration(duration)}"
            return word
        if kind in ("cond_eq", "cond_ne"):
            name, value = node.children
            return f"{name} {'==' if kind == 'cond_eq' else '!='} {self.value(value)}"
        if kind == "cond_layer":
            return f"layer {node.children[0]}"
        return str(node.children[0])  # cond_name


def _has_props(axis: Tree) -> bool:
    return (
        len(axis.children) == 2
        and isinstance(axis.children[1], Tree)
        and (axis.children[1].data == "props")
    )


# -- assembling lines and comments ------------------------------------------------------------


def _assemble(rendered: list[Line], notes: list[Comment], source_lines: list[str]) -> str:
    lines = list(rendered)
    own_line = [c for c in notes if c.own_line]
    for comment in [c for c in notes if not c.own_line]:
        target = [line for line in lines if line.src == comment.line]
        if target:
            target[0].comment = comment.text  # the line where the statement starts
        else:  # its line was merged into another one: keep it on a line of its own
            own_line.append(Comment(comment.line, comment.text, True))
    for comment in sorted(own_line, key=lambda c: c.line):
        index = next((i for i, line in enumerate(lines) if line.src > comment.line), len(lines))
        if index < len(lines):
            after = lines[index]
            indent = after.indent + (1 if after.text.startswith("}") else 0)
        else:
            indent = 0
        lines.insert(index, Line(indent, comment.text, comment.line))
    _align_props(lines)
    return _join(lines, source_lines)


def _align_props(lines: list[Line]) -> None:
    run: list[Line] = []
    for line in [*lines, None]:
        if line is not None and line.prop and (not run or run[0].prop[0] == line.prop[0]):
            run.append(line)
            continue
        if len(run) > 1:
            width = max(len(r.prop[1]) for r in run)
            for r in run:
                r.text = f"{r.prop[1]:<{width}} = {r.prop[2]}"
        run = [line] if line is not None and line.prop else []


def _join(lines: list[Line], source_lines: list[str]) -> str:
    out: list[str] = []
    codes = [INDENT * line.indent + line.text for line in lines]
    # Trailing comments of consecutive lines share one column (rule 7).
    columns: dict[int, int] = {}
    start = 0
    while start < len(lines):
        if lines[start].comment is None:
            start += 1
            continue
        end = start
        while end + 1 < len(lines) and lines[end + 1].comment is not None:
            end += 1
        column = max(len(codes[i]) for i in range(start, end + 1)) + 2
        for i in range(start, end + 1):
            columns[i] = column
        start = end + 1
    previous: Line | None = None
    for i, line in enumerate(lines):
        if previous is not None and _blank_between(previous, line, source_lines):
            out.append("")
        text = codes[i]
        if line.comment is not None:
            text = text.ljust(columns[i]) + line.comment
        out.append(text)
        previous = line
    return "\n".join(out).strip("\n") + "\n"


def _blank_between(before: Line, after: Line, source_lines: list[str]) -> bool:
    """Keep one blank line where the source had one (rule 6)."""
    if before.text.endswith("{") or after.text.startswith("}"):
        return False
    between = source_lines[before.src : after.src - 1]
    return any(not text.strip() for text in between)


__all__ = ["DslSyntaxError", "FormatError", "format_text"]

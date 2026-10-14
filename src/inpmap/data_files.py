"""Files shipped inside the package: the example configuration and editor syntax files."""

from __future__ import annotations

from importlib.resources import files

EXAMPLE_PROFILE = "example"
SYNTAX_FILES = {"kate": "inpmap.xml", "nano": "inpmap.nanorc"}


def example_text() -> str:
    """The example configuration (docs/configuration.md §10)."""
    return files("inpmap").joinpath("data/example.inpmap").read_text(encoding="utf-8")


def syntax_file(editor: str) -> str:
    """The syntax highlighting file for ``editor`` (a key of SYNTAX_FILES)."""
    name = SYNTAX_FILES[editor]
    return files("inpmap").joinpath(f"data/syntax/{name}").read_text(encoding="utf-8")

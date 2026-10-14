"""Where configurations live, and profile names (docs/usage.md, "Profiles").

Configurations are kept in ``$XDG_CONFIG_HOME/inpmap/`` (usually
``~/.config/inpmap/``). Commands accept either a path or a profile name:
an argument that ends in ``.inpmap`` or contains ``/`` is a path, anything
else is the name of ``<config dir>/NAME.inpmap``; no argument means the
profile ``default``.
"""

from __future__ import annotations

import os
from pathlib import Path

DEFAULT_PROFILE = "default"
SUFFIX = ".inpmap"


def config_dir() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.join(os.path.expanduser("~"), ".config")
    return Path(base) / "inpmap"


def is_path(argument: str) -> bool:
    return argument.endswith(SUFFIX) or "/" in argument


def resolve(argument: str | None) -> str:
    """The configuration file a command argument refers to."""
    if argument is None:
        argument = DEFAULT_PROFILE
    if is_path(argument):
        return argument
    return str(config_dir() / f"{argument}{SUFFIX}")


def profile_name(argument: str | None) -> str | None:
    """The profile name of an argument, or None if it is a path."""
    if argument is None:
        return DEFAULT_PROFILE
    return None if is_path(argument) else argument


def profile_name_of(path: str) -> str:
    """How to name a configuration file in messages: its profile name if it
    lives in the configuration folder, else the path."""
    file = Path(path)
    return file.stem if file.parent == config_dir() else path

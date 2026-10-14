"""Load a configuration file.

Configurations are written in the InpMap configuration language
(`.inpmap` files, docs/configuration.md); this is the only format.
"""

from __future__ import annotations

from pathlib import Path

from .config import ConfigError
from .dsl.compiler import LoadResult
from .dsl.compiler import load as load_dsl

DSL_SUFFIX = ".inpmap"


def load(path: str | Path) -> LoadResult:
    """Load and validate a configuration; returns the model and warnings."""
    if Path(path).suffix != DSL_SUFFIX:
        raise ConfigError(
            str(path),
            [f"configuration files must end in {DSL_SUFFIX} (see docs/configuration.md)"],
        )
    return load_dsl(path)

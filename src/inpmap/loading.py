"""Load a configuration file in either supported format.

`.inpmap` files use the configuration language (docs/dsl.md); everything
else is read as JSON. Both produce the same validated model.
"""

from __future__ import annotations

from pathlib import Path

from .config import load_config
from .dsl.compiler import LoadResult
from .dsl.compiler import load as load_dsl

DSL_SUFFIX = ".inpmap"


def load(path: str | Path) -> LoadResult:
    """Load and validate a configuration; returns the model and warnings."""
    if Path(path).suffix == DSL_SUFFIX:
        return load_dsl(path)
    return LoadResult(load_config(path), [])

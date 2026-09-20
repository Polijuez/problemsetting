"""``problemsetting`` -- problem authoring toolkit for the Polijuez DMOJ judge.

The package is consumed by problem repositories as a pinned ``uv`` git
dependency (decision Q2), so the CLI surface and :mod:`problemsetting.meta` are
public API: subcommand names, flags, and ``meta.yml``'s schema are contract.

Importing :mod:`problemsetting` deliberately does **not** import the subcommand
modules; :func:`problemsetting.cli.main` does, because a subcommand is only
registered when its module is imported.
"""

from __future__ import annotations

__version__ = "0.1.0"

from .errors import MetaError, ProblemsettingError, ScaffoldError
from .meta import (
    AXES,
    MODELS,
    Limits,
    ResolvedMeta,
    allowed_extensions,
    load,
    resolve,
)

__all__ = [
    "AXES",
    "Limits",
    "MODELS",
    "MetaError",
    "ProblemsettingError",
    "ResolvedMeta",
    "ScaffoldError",
    "__version__",
    "allowed_extensions",
    "load",
    "resolve",
]

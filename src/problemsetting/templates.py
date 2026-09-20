"""Access to the model templates shipped as package data.

Templates live in ``src/problemsetting/models/<model>/`` and travel inside the
wheel (decision Q29): there is no override layer and no template directory to
keep in sync with the installed package.  Each template is a complete working
problem, which is why the toolkit has no separate fixture set.
"""

from __future__ import annotations

from pathlib import Path

from .errors import ProblemsettingError
from .meta import EXECUTOR_BY_EXT, MODELS

MODELS_ROOT = Path(__file__).resolve().parent / "models"

#: Never copied into a new problem.  The first group is build output (which
#: .gitignore already covers), the second editor/bytecode noise.
TEMPLATE_IGNORE = (
    "__pycache__",
    "*.pyc",
    "init.yml",
    "*.zip",
    "*.in",
    "*.out",
    "__meta__",
)


def shipped() -> tuple[str, ...]:
    """Model names whose template is present in this build."""
    if not MODELS_ROOT.is_dir():
        return ()
    return tuple(
        sorted(entry.name for entry in MODELS_ROOT.iterdir() if (entry / "meta.yml").is_file())
    )


def template_dir(model: str) -> Path:
    """Return the template directory for ``model``, or raise an actionable error."""
    if model not in MODELS:
        raise ProblemsettingError(
            f"unknown model {model!r}; valid models: {', '.join(sorted(MODELS))}"
        )
    directory = MODELS_ROOT / model
    if not (directory / "meta.yml").is_file():
        available = shipped()
        if not available:
            raise ProblemsettingError(
                f"model {model!r} has no template in this build (looked in {MODELS_ROOT})"
            )
        raise ProblemsettingError(
            f"model {model!r} is part of the toolkit but its template is not shipped yet; "
            f"templates available in this build: {', '.join(available)}"
        )
    return directory


def solution_extensions(model: str) -> tuple[str, ...]:
    """Extensions of the model solutions ``model``'s template actually ships."""
    directory = template_dir(model)
    extensions = sorted(
        path.suffix for path in directory.glob("solution.*") if path.suffix in EXECUTOR_BY_EXT
    )
    if not extensions:
        raise ProblemsettingError(
            f"template {directory} ships no model solution (expected a solution.<ext> file)"
        )
    return tuple(extensions)

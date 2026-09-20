"""Exception hierarchy for the problemsetting toolkit.

Every error raised on *authoring* input -- a malformed ``meta.yml``, an
unusable problem name, a model whose template is not shipped -- is a
:class:`ProblemsettingError`.  The CLI prints those as ``error: ...`` and exits
non-zero; unexpected exceptions keep their traceback, because they are bugs.

Messages are the real user interface here: name the offending value, the file
it came from, and the valid alternatives.
"""

from __future__ import annotations


class ProblemsettingError(Exception):
    """Base class: an expected, actionable authoring error."""


class MetaError(ProblemsettingError):
    """``meta.yml`` is missing, malformed, or names something unknown."""


class ScaffoldError(ProblemsettingError):
    """``problemsetting new`` cannot scaffold the requested problem."""


class CaseError(ProblemsettingError):
    """A problem's ``generator.py`` cannot be turned into cases and ``init.yml``."""


class JudgeError(ProblemsettingError):
    """The judge image, the container pool, or a grading run is unusable."""


class OutputError(ProblemsettingError):
    """The model solution cannot be built, run, or trusted as an expected output."""

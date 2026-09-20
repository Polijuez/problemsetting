"""Problem directories: naming rules and lookup.

A problem is a directory containing ``meta.yml``; its **name is the directory
name**, because DMOJ derives the problem id from the basename of the directory
holding ``init.yml`` (``dmoj/judgeenv.py:get_problem_root()``).
"""

from __future__ import annotations

import re

from .errors import ProblemsettingError

#: DMOJ addresses problems by id and the site uses the same string, so keep it to
#: what survives being a directory name, a URL path segment and a filename stem.
#: ``\Z`` rather than ``$``: ``$`` also matches just before a trailing newline,
#: which would let ``demo\n`` through as a name.
NAME_RE = re.compile(r"[a-z0-9][a-z0-9_-]*\Z")

#: The site rejects problem codes longer than this (the old toolkit's README warns
#: about it).  Scaffolding is not blocked so much as refused early.
SITE_NAME_LIMIT = 20


def validate_name(name: str) -> str:
    """Return ``name`` if it is usable as a problem id, else raise."""
    if not NAME_RE.match(name):
        raise ProblemsettingError(
            f"invalid problem name {name!r}: use lowercase letters, digits, '-' and '_', "
            f"starting with a letter or digit"
        )
    if len(name) > SITE_NAME_LIMIT:
        raise ProblemsettingError(
            f"problem name {name!r} is {len(name)} characters; the judge site accepts at "
            f"most {SITE_NAME_LIMIT}"
        )
    return name



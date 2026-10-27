"""Problem directories: naming rules and lookup.

A problem is a directory containing ``meta.yml``; its **name is the directory
name**, because DMOJ derives the problem id from the basename of the directory
holding ``init.yml`` (``dmoj/judgeenv.py:get_problem_root()``).

Publishing no longer uses that name as the site's problem id -- the site assigns
a UUID and the human title/aliases travel in the package manifest -- so there is
no length cap here.  The name still has to be usable as a directory name and as
the id the judge sees, and it still has to be unique among the problems the
pool discovers.
"""

from __future__ import annotations

import re

from .errors import ProblemsettingError

#: DMOJ addresses problems by id, so keep it to what survives being a directory
#: name, a URL path segment and a filename stem.  ``\Z`` rather than ``$``: ``$``
#: also matches just before a trailing newline, which would let ``demo\n``
#: through as a name.
NAME_RE = re.compile(r"[a-z0-9][a-z0-9_-]*\Z")


def validate_name(name: str) -> str:
    """Return ``name`` if it is usable as a problem id, else raise."""
    if not NAME_RE.match(name):
        raise ProblemsettingError(
            f"invalid problem name {name!r}: use lowercase letters, digits, '-' and '_', "
            f"starting with a letter or digit"
        )
    return name

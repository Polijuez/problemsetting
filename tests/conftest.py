"""Suite-wide isolation from the roots the developer's shell happens to export.

Two environment variables redirect a root the toolkit resolves: ``PROBLEMS_ROOT``
(whence a problem is read and what a pool mounts) and ``PROBLEMSETTING_ROOT``
(which checkout the judge image is built from).  A developer working in a
problemset repo usually has the former exported, and a developer pointing the
toolkit at a fixture tree exports the latter.  Either leaking into this suite
would change what an unrelated test resolves -- the toolkit's own tests use the
toolkit checkout as the problems root, which is exactly what those variables
override -- and the failure would look like a bug in whichever test happened to
run first.

The removal is done once per session and restored at teardown, because it has to
happen *before* the module-scoped fixtures that build a problem through the CLI
(``tests/test_ci_contract.py``'s ``pipeline``): a function-scoped autouse fixture
runs after those, which is too late to help them.  A test that needs either
variable set does so with ``monkeypatch``, which is the only way it becomes
visible -- so a test's outcome depends on the test, not on the shell.
"""

from __future__ import annotations

import os
from collections.abc import Iterator

import pytest

from problemsetting import judges

#: Every environment variable that redirects a root.  Named here rather than
#: scattered, so adding a third redirection is one line and cannot be forgotten.
ROOT_ENV_VARS = (judges.PROBLEMS_ROOT_ENV, "PROBLEMSETTING_ROOT")


@pytest.fixture(scope="session", autouse=True)
def hermetic_roots() -> Iterator[None]:
    """Run the whole suite as if neither root had been configured in the shell."""
    saved = {variable: os.environ.pop(variable, None) for variable in ROOT_ENV_VARS}
    try:
        yield
    finally:
        for variable, value in saved.items():
            if value is not None:
                os.environ[variable] = value

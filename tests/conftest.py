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
import shutil
import tempfile
from collections.abc import Iterator
from pathlib import Path

import pytest

from problemsetting import judges

#: Every environment variable that redirects a root.  Named here rather than
#: scattered, so adding a third redirection is one line and cannot be forgotten.
ROOT_ENV_VARS = (judges.PROBLEMS_ROOT_ENV, "PROBLEMSETTING_ROOT")


@pytest.fixture(scope="session", autouse=True)
def hermetic_roots() -> Iterator[None]:
    """Run the whole suite as if no root had been configured, nor a repo entered.

    Removing the two environment variables is not enough, because neither is the
    first thing the problems root consults: **detection is**, and detection walks
    up from the current directory looking for the vendoring signature (a
    ``problems/`` directory beside ``vendor/problemsetting/``).  Running this
    suite from a checkout of the package with the working directory inside a
    problemset repo therefore makes every test resolve *that* repo's problems
    root, no matter what ``PROBLEMSETTING_ROOT`` says.  Measured: with cwd in a
    problemset repo, ``problems_root()`` returned that repo's ``problems/`` while
    ``PROBLEMSETTING_ROOT`` pointed elsewhere, and
    ``test_container_path_maps_under_the_mount`` failed for exactly that reason
    -- a test whose outcome depended on where the suite was launched from.

    So the suite also runs from a directory with no problemset structure above
    it.  ``tmp_path_factory`` is not usable at session scope before the first
    test, so the directory is made here and removed at teardown.
    """
    saved_env = {variable: os.environ.pop(variable, None) for variable in ROOT_ENV_VARS}
    saved_cwd = os.getcwd()
    # Under the system temp dir, which is above neither the toolkit nor a
    # problemset repo, and holds no `problems/` marker of its own.
    neutral = Path(tempfile.mkdtemp(prefix="problemsetting-suite-"))
    os.chdir(neutral)
    try:
        yield
    finally:
        os.chdir(saved_cwd)
        shutil.rmtree(neutral, ignore_errors=True)
        for variable, value in saved_env.items():
            if value is not None:
                os.environ[variable] = value

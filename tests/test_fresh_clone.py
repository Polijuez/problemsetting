"""The fresh-clone proof: clone a problemset repo and grade a problem.  **Opt-in.**

Every other test in this suite starts from a working directory that is already
set up: the toolkit checkout has its ``.venv``, its submodules are initialised,
and the problems it grades live inside that checkout.  That is exactly the crutch
a problemset repository does not have.  The property this file proves is the one
the whole vendoring exercise exists for (plan decision Q9, ticket 08)::

    cloning a problemset repository is enough to use the vendored toolkit

So the test builds the state a clone actually starts in -- a brand-new temporary
directory, no virtualenv, no generated cases, no initialised submodules -- and
drives the *documented* workflow to a graded verdict:

1. ``git clone <problemset repo>`` -- a pristine directory.
2. ``git submodule update --init --recursive`` -- the vendored toolkit *and* its
   nested judge-server.
3. ``(cd vendor/problemsetting && uv sync)`` -- the vendored toolkit's own venv.
4. ``./problemsetting regenerate`` -- rebuild the cases from the committed
   sources and confirm the committed checksums still describe them.
5. ``./problemsetting judges start`` then ``./problemsetting verify suma`` --
   grade through a real pool and read the verdict.

Commands are run through the shim at the repository root (``./problemsetting``,
decision Q13) rather than against the toolkit's modules, because the shim is the
author-facing surface the documentation promises; bypassing it would leave the
one thing every reader is told to type untested.

Two environment facts, stated rather than hidden
------------------------------------------------

**The submodule URL is rewritten to the local toolkit checkout.**  The problemset
repo's gitlink names a toolkit commit, and a gitlink names a *public revision*
rather than a machine-local path (that is deliberate -- the repository is shared).
The pin is currently unpublished -- the toolkit is ahead of ``origin/master`` --
so ``git submodule update --init --recursive`` against the public URL fails with
``upload-pack: not our ref``.  Publishing is the repository owner's decision, not
something a test may do, so the test points the submodule at the checkout the
suite is running from (``checkout_root()``) and uses
``-c protocol.file.allow=always`` to allow the file transport.  That is the
recommended remedy in ``docs/maintaining-a-problemset.md`` and in the repo's own
README, and it is a *substitution for an unpublished pin*, not the documented
procedure: with the pin published, the same commands work unchanged against the
public URL.

**The clone is made with ``umask 022``.**  ``git`` creates checked-out files with
``0666 & ~umask``, and the pool container runs the judge as a user that maps to a
different host identity, so a checkout made under a restrictive umask produces
files the container cannot read: ``podman logs`` then shows
``can't open file '/run/judge_runtime/launcher.py': [Errno 13] Permission
denied`` and the container dies before it is ready.  The default umask (022) is
what any real checkout has; the test sets it explicitly so the proof does not
depend on the invoking shell's ``umask``.  Reported to the orchestrator as a
finding: the toolkit could be made robust to a restrictive umask, but that is a
production change and outside this ticket.

These tests are skipped unless explicitly asked for, like the rest of the
judge-dependent suite::

    PROBLEMSETTING_JUDGE_TESTS=1 uv run pytest tests/test_fresh_clone.py

They need ``git`` and ``uv`` on the ``PATH`` as well, and the problemset
repository to clone.  The latter is named by ``PROBLEMSETTING_PROBLEMSET_REPO``,
defaulting to a ``problemset`` checkout beside this toolkit (how the two are
developed together); the tests skip when neither is present.
"""

from __future__ import annotations

import dataclasses
import hashlib
import os
import re
import shutil
import subprocess
from collections.abc import Iterator
from pathlib import Path

import pytest
import yaml

from problemsetting import judges

OPT_IN = os.environ.get("PROBLEMSETTING_JUDGE_TESTS") == "1"

#: The problemset repository to clone.  It is a repository *of problems*, not
#: part of the toolkit, so nothing in the toolkit can derive its location; the
#: variable names it, and the default is the side-by-side checkout the two
#: repositories are developed in.
REPO_ENV = "PROBLEMSETTING_PROBLEMSET_REPO"

#: Generous, because every one of these commands does real work: ``judges start``
#: boots a container that discovers the problems and self-tests every executor
#: (measured ~42 s warm), ``regenerate`` runs both generators and the model
#: solution, and ``verify`` compiles and runs each declared submission.  They
#: bound a hang; they do not pace the run.
COMMAND_TIMEOUT = 1800.0

#: Decision Q7 names the two committed checksums the problem directories carry.
CHECKSUM_SUFFIXES = ("zip.sha256sum", "zip.cases.sha256sum")


def checkout_root() -> Path:
    """The toolkit checkout this test file lives in.

    Located from the file rather than through :func:`judges.toolkit_root`, whose
    answer ``PROBLEMSETTING_ROOT`` may override with a fixture tree: the
    problemset repository to clone has to sit beside the *real* checkout, and the
    module-level constant below is computed before pytest's session fixture has
    had a chance to clear that variable.
    """
    for parent in Path(__file__).resolve().parents:
        if (parent / "pyproject.toml").is_file() and (parent / "src").is_dir():
            return parent
    raise AssertionError("this test file is not inside a problemsetting checkout")


def source_repository() -> Path | None:
    """The problemset repo to clone, or None when this machine has none.

    A named path wins; the fallback is the sibling checkout, and it is accepted
    only when it looks like a problemset repo (the shim is there and
    ``vendor/problemsetting`` is a submodule), so an unrelated directory sitting
    beside the toolkit cannot be cloned by accident.
    """
    named = os.environ.get(REPO_ENV)
    if named:
        candidate = Path(named)
        return candidate.resolve() if (candidate / "problemsetting").is_file() else None
    sibling = checkout_root().parent / "problemset"
    if (sibling / "problemsetting").is_file() and (sibling / "vendor/problemsetting").exists():
        return sibling
    return None


#: The repository cloned by the whole module, resolved at import because a skip
#: has to be decided before any fixture runs.
SOURCE = source_repository()

pytestmark = [
    pytest.mark.skipif(
        not OPT_IN,
        reason="set PROBLEMSETTING_JUDGE_TESTS=1 (needs the judge image and podman)",
    ),
    pytest.mark.skipif(
        shutil.which("podman") is None, reason="podman is not installed"
    ),
    # The documented workflow needs both: git for the clone and the submodules,
    # uv to create the vendored toolkit's venv.
    pytest.mark.skipif(shutil.which("git") is None, reason="git is not installed"),
    pytest.mark.skipif(shutil.which("uv") is None, reason="uv is not installed"),
    pytest.mark.skipif(
        SOURCE is None,
        reason=f"no problemset repository to clone; set {REPO_ENV} to one",
    ),
]


@dataclasses.dataclass
class FreshClone:
    """A pristine clone, and the documented commands run inside it.

    Every command runs with the clone's root as ``cwd`` and with the roots this
    suite's shell might export removed from the environment, so what a command
    resolves is what the clone contains -- not what the developer's shell happens
    to point at.  Testing the roots' resolution is ``tests/test_two_roots.py``'s
    job; here they must not be able to interfere.
    """

    root: Path

    @property
    def toolkit(self) -> Path:
        """The vendored toolkit inside the clone."""
        return self.root / "vendor" / "problemsetting"

    @property
    def judge_server(self) -> Path:
        """The toolkit's *nested* submodule: the DMOJ judge-server source."""
        return self.toolkit / "vendor" / "judge-server"

    def run(
        self,
        *argv: str,
        cwd: Path | None = None,
        check: bool = True,
        timeout: float = COMMAND_TIMEOUT,
    ) -> subprocess.CompletedProcess[str]:
        """Run one command in the clone; raise with its output when it fails.

        ``umask 022`` is set in the child (see the module docstring): the clone
        has to be readable by the pool container, and ``git`` takes the modes of
        the files it writes from the caller's umask.
        """
        environment = dict(os.environ)
        for variable in (judges.PROBLEMS_ROOT_ENV, "PROBLEMSETTING_ROOT"):
            environment.pop(variable, None)
        process = subprocess.run(
            list(argv),
            cwd=cwd or self.root,
            env=environment,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=timeout,
            preexec_fn=lambda: os.umask(0o022),
        )
        if check and process.returncode != 0:
            raise AssertionError(
                f"{' '.join(argv)} failed with status {process.returncode}\n"
                f"--- output ---\n{process.stdout}"
            )
        return process

    @classmethod
    def clone(cls, source: Path, destination: Path) -> FreshClone:
        """``git clone source destination``, making the pristine directory.

        The clone is the one command that cannot go through :meth:`run` (there is
        no clone to run it in yet), so it repeats the two things that wrapper
        guarantees: the umask git writes the checkout with -- a restrictive one
        makes the files unreadable inside the pool container (see the module
        docstring) -- and a failure that reports what git said.
        """
        result = subprocess.run(
            ["git", "clone", "--quiet", str(source), str(destination)],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            preexec_fn=lambda: os.umask(0o022),
        )
        assert result.returncode == 0, f"cannot clone {source}:\n{result.stdout}"
        return cls(root=destination)

    def problemsetting(
        self, *args: str, check: bool = True, timeout: float = COMMAND_TIMEOUT
    ) -> subprocess.CompletedProcess[str]:
        """Run the repository's root shim -- the command authors are told to type."""
        return self.run("./problemsetting", *args, check=check, timeout=timeout)

    def git(self, *args: str, cwd: Path | None = None) -> str:
        """Read one git fact out of the clone (stdout, stripped)."""
        return self.run("git", *args, cwd=cwd).stdout.strip()


# ---------------------------------------------------------------------------
# The clone, and the two half-set-up states it passes through
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def clone(tmp_path_factory: pytest.TempPathFactory) -> FreshClone:
    """``git clone``, and nothing else: the pristine state.

    The two diagnostics a half-set-up clone produces are captured *here*, before
    any later fixture mutates the directory, so the tests that assert them cannot
    be satisfied or broken by the order they happen to run in.
    """
    destination = tmp_path_factory.mktemp("problemset-clone") / "problemset"
    return FreshClone.clone(SOURCE, destination)


@pytest.fixture(scope="module")
def pristine(clone: FreshClone) -> dict[str, object]:
    """What the clone looks like before the documented steps are taken.

    Recorded rather than asserted so a test can inspect it, and split out from
    :func:`clone` so the observation happens at the only moment it is true.
    """
    shim = clone.problemsetting("--version", check=False)
    return {
        "judge_server_entries": (
            len(list(clone.judge_server.iterdir()))
            if clone.judge_server.is_dir()
            else 0
        ),
        "venv_exists": (clone.toolkit / ".venv").exists(),
        "shim_status": shim.returncode,
        "shim_output": shim.stdout,
        "shim_executable": os.access(clone.root / "problemsetting", os.X_OK),
    }


def test_a_fresh_clone_carries_sources_and_checksums_but_no_generated_data(
    clone: FreshClone, pristine: dict[str, object]
) -> None:
    """What the clone has is what the repository commits (decision Q7)."""
    assert pristine["judge_server_entries"] == 0, (
        "a plain clone leaves the nested judge-server submodule empty; a populated "
        f"one would mean the test is not starting pristine: {clone.judge_server}"
    )
    assert pristine["venv_exists"] is False, "a fresh clone has no virtualenv"
    assert pristine["shim_executable"] is True, (
        "the root shim is committed executable (decision Q13); the clone must "
        "preserve its mode"
    )

    problem = clone.root / "problems" / "suma"
    for name in ("meta.yml", "generator.py", "solution.cpp", "submissions.yml"):
        assert (problem / name).is_file(), f"{name} is a committed input"
    for suffix in CHECKSUM_SUFFIXES:
        assert (problem / f"suma.{suffix}").is_file(), f"suma.{suffix} is committed"
    for generated in ("init.yml", "cases", "suma.zip", "__meta__"):
        assert not (problem / generated).exists(), (
            f"{generated} is a build product and must not be committed; a clone "
            "that already had it would not prove regeneration works"
        )


def test_the_shim_names_the_pending_submodule_before_it_is_initialised(
    pristine: dict[str, object],
) -> None:
    """The first failure a clone can hit explains itself and its remedy."""
    assert pristine["shim_status"] == 1
    output = str(pristine["shim_output"])
    assert "git submodule update --init --recursive" in output, output


@pytest.fixture(scope="module")
def submodules(clone: FreshClone) -> FreshClone:
    """``git submodule update --init --recursive``, with the pin substitution."""
    # The substitution for the unpublished pin (see the module docstring): point
    # the submodule at the checkout under test, which is the one that has the
    # pinned commit.  `protocol.file.allow=always` is what lets git clone from a
    # local path at all.
    clone.run("git", "config", "submodule.vendor/problemsetting.url", str(checkout_root()))
    clone.run(
        "git",
        "-c",
        "protocol.file.allow=always",
        "submodule",
        "update",
        "--init",
        "--recursive",
    )
    return clone


def test_submodules_initialise_recursively(submodules: FreshClone) -> None:
    """Both submodules land, the nested one included: ``--recursive`` is not optional.

    Without ``--recursive`` the vendored toolkit arrives and its own
    ``vendor/judge-server`` stays empty, and the judge image cannot be built from
    an empty directory -- that is the failure the documentation warns about, so
    the assertion is on the nested checkout being populated, not just present.
    """
    assert (submodules.toolkit / "pyproject.toml").is_file(), "the toolkit submodule is empty"
    assert (submodules.judge_server / ".docker").is_dir(), (
        "the nested judge-server submodule is empty; `--recursive` is required"
    )

    pinned = submodules.git("rev-parse", "HEAD", cwd=submodules.toolkit)
    ancestor = submodules.run(
        "git",
        "-C",
        str(checkout_root()),
        "merge-base",
        "--is-ancestor",
        pinned,
        "HEAD",
        check=False,
    )
    assert ancestor.returncode == 0, (
        f"the vendored commit {pinned} is not an ancestor of the toolkit under test "
        f"({checkout_root()}); the pin must name a commit of this toolkit"
    )


def test_the_shim_names_the_missing_virtualenv_before_uv_sync(
    submodules: FreshClone,
) -> None:
    """With the submodule in place but no venv, the shim still explains itself."""
    result = submodules.problemsetting("--version", check=False)
    assert result.returncode == 1
    assert "uv sync" in result.stdout, result.stdout
    assert ".venv/bin/problemsetting" in result.stdout, result.stdout


@pytest.fixture(scope="module")
def usable(submodules: FreshClone) -> FreshClone:
    """``(cd vendor/problemsetting && uv sync)``: the venv the documentation creates."""
    submodules.run("uv", "sync", cwd=submodules.toolkit, timeout=COMMAND_TIMEOUT)
    return submodules


def test_uv_sync_makes_the_vendored_toolkit_usable(usable: FreshClone) -> None:
    """The step the documentation names, and the version it prints afterwards."""
    result = usable.problemsetting("--version")
    assert re.fullmatch(r"problemsetting \S+\n", result.stdout), result.stdout


# ---------------------------------------------------------------------------
# Regeneration from the committed sources
# ---------------------------------------------------------------------------


@dataclasses.dataclass(frozen=True)
class Rebuild:
    """A clone whose cases have been rebuilt, and what ``regenerate`` said."""

    clone: FreshClone
    report: subprocess.CompletedProcess[str]


@pytest.fixture(scope="module")
def rebuilt(usable: FreshClone) -> Rebuild:
    """``./problemsetting regenerate``: the whole repository, from committed sources.

    Run here rather than inside the test because the pool needs the cases it
    produces: the judge grades the generated ``init.yml`` and case data, and a
    fresh clone has neither.  The report is kept alongside the clone so the test
    asserts on what the command actually printed, not on a second run.
    """
    return Rebuild(clone=usable, report=usable.problemsetting("regenerate", timeout=COMMAND_TIMEOUT))


def _checksums(path: Path) -> dict[str, str]:
    """A committed ``sha256sum`` file as ``{relative path: digest}``.

    Comments -- the cases checksum file ends with a commented ``init.yml`` line,
    which is deliberately not asserted on -- are skipped, so only the entries the
    file actually pins are returned.
    """
    return {
        entry.split()[1]: entry.split()[0]
        for entry in path.read_text().splitlines()
        if entry and not entry.startswith("#")
    }


def test_regenerate_reproduces_the_committed_checksums(rebuilt: Rebuild) -> None:
    """Decision Q7's loop: sources and checksums are enough to rebuild the data.

    The command reports ``OK`` per problem and exits non-zero on a drift -- a
    generator that no longer reproduces the committed checksum -- so this fails
    rather than letting the mismatch be silently repaired.
    """
    assert rebuilt.report.returncode == 0, rebuilt.report.stdout
    assert "regenerate: 2 OK" in rebuilt.report.stdout, rebuilt.report.stdout
    assert "DRIFT" not in rebuilt.report.stdout, rebuilt.report.stdout
    # One OK line per problem, both named: a run that reported OK for one problem
    # while silently skipping the other would still contain "2 OK".
    for problem in ("suma", "subpalindromo"):
        assert re.search(rf"^\s+OK\s+{problem}\b", rebuilt.report.stdout, re.MULTILINE), (
            rebuilt.report.stdout
        )

    # The reported OK is not taken on faith: hash the rebuilt case data against
    # the committed checksum file, independently of the command's comparison.
    problem = rebuilt.clone.root / "problems" / "suma"
    committed = _checksums(problem / "suma.zip.cases.sha256sum")
    assert committed, "suma commits a checksum over its case data"
    for relative, digest in committed.items():
        rebuilt_case = problem / relative
        assert rebuilt_case.is_file(), f"{relative} was named but not rebuilt"
        assert hashlib.sha256(rebuilt_case.read_bytes()).hexdigest() == digest, (
            f"{relative} differs from the committed checksum"
        )

    archive = problem / "suma.zip"
    assert (
        hashlib.sha256(archive.read_bytes()).hexdigest()
        == _checksums(problem / "suma.zip.sha256sum")["suma.zip"]
    ), "the rebuilt archive does not match the committed checksum"

    # Regenerating writes build products only and leaves the committed tree
    # alone -- which is what proves the checksums were compared, not rewritten.
    assert rebuilt.clone.git("status", "--porcelain") == "", "regenerate dirtied the clone"


# ---------------------------------------------------------------------------
# Grading through the pool
# ---------------------------------------------------------------------------


def _pool_diagnostic(clone: FreshClone, name: str) -> str:
    """What podman knows about the container, for a failed ``judges start``.

    ``judges start`` reports readiness by printing ``<name> ready``, and a
    container that never gets there is otherwise a bare line with nothing to act
    on: the state and the launcher's log are what say *why* (a killed container, a
    permission failure, a crashed launcher).  Both are best-effort -- the
    container may not exist at all -- so neither can raise over the real failure.
    """
    state = clone.run("podman", "inspect", name, "--format", "{{.State.Status}}", check=False)
    logs = clone.run("podman", "logs", name, check=False)
    return (
        f"container state: {state.stdout.strip() or '(inspect failed)'}\n"
        f"--- podman logs {name} ---\n{logs.stdout}"
    )


@pytest.fixture(scope="module")
def graded(rebuilt: Rebuild) -> Iterator[tuple[Rebuild, subprocess.CompletedProcess[str]]]:
    """Run ``verify suma`` through the shim against a pool for *this* clone.

    A pool of one container is started here and stopped in teardown.  Both
    halves are deliberate: the pool's container names are fixed (decisions
    Q5/Q20), so only one pool can serve a machine at a time, and the ``stop``
    first means a container another test happened to leave running cannot make
    this test depend on it -- while the ``stop`` last means this test cannot
    become the leak for another.  A stale pool from a different root would be
    refused (correctly), and the refusal would look like a clone problem.

    One container, not the ``--count`` default: the test grades one submission
    set at a time, and every container pays a full executor self-test at boot.
    """
    if not judges.image_exists():
        pytest.skip(judges.build_instructions())

    clone = rebuilt.clone
    clone.problemsetting("judges", "stop")
    started = clone.problemsetting("judges", "start", "--count", "1", timeout=COMMAND_TIMEOUT)
    name = judges.container_name(1)
    try:
        # Inside the try: a `start` that leaves the container half-booted has to
        # be cleaned up too, and teardown is the only place that happens.
        assert re.search(rf"^\s+{name} ready$", started.stdout, re.MULTILINE), (
            "the pool never reported ready; the documented workflow did not get a "
            "usable judge.  `judges start` exits 0 either way, so readiness is read "
            f"from its output:\n{started.stdout}\n{_pool_diagnostic(clone, name)}"
        )
        yield rebuilt, clone.problemsetting("verify", "suma", timeout=COMMAND_TIMEOUT)
    finally:
        clone.problemsetting("judges", "stop", check=False)


def test_the_model_solution_grades_full_marks_in_a_fresh_clone(
    graded: tuple[Rebuild, subprocess.CompletedProcess[str]],
) -> None:
    """The end of the documented workflow: ``verify`` grades and agrees.

    ``verify`` exits zero only when every declared submission got the result it
    declares *and* every check it could run passed, so the exit status is the
    verdict, and a zero here is the whole ticket: a clone that only ran the
    documented commands produced a full-marks grade for the model solution.

    The expectation is read from ``submissions.yml`` and searched for in the
    report, so this asserts "the problem got what it declares" rather than "some
    line said AC".
    """
    rebuilt, result = graded
    assert result.returncode == 0, result.stdout
    assert "0 mismatch(es)" in result.stdout, result.stdout

    declared = yaml.safe_load(
        (rebuilt.clone.root / "problems" / "suma" / "submissions.yml").read_text()
    )["submissions"]
    model = next(entry for entry in declared if entry.get("role") == "model")
    assert model["source"] == "solution.cpp"
    assert model["verdict"] == "AC" and model["score"] == 100, (
        "this test assumes suma declares full marks for its model solution; if the "
        "problem's declaration changed, the assertions below have to change with it"
    )

    assert re.search(
        r"^\s*\d+\.\s+solution\.cpp\s+model\s+\S+\s+AC\s+score 100/100",
        result.stdout,
        re.MULTILINE,
    ), (
        "the model solution was not reported AC with the declared 100/100:\n"
        + result.stdout
    )
    assert re.search(
        r"^\s*1\. model solution scores full marks\s+PASS", result.stdout, re.MULTILINE
    ), result.stdout

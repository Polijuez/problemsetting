"""End-to-end grading through a real judge pool container.  **Opt-in.**

These tests are the toolkit's proof that the judging substrate works: they build
a problem, start a pool container, grade a submission, and read the verdicts
DMOJ reports.  They need the 15 GB ``localhost/dmoj/judge-tier3:latest`` image
and a working rootless podman, so they are skipped unless explicitly asked for::

    PROBLEMSETTING_JUDGE_TESTS=1 uv run pytest tests/test_judge_pool.py

(Decision Q29 makes the full judging pipeline an opt-in CI job for the same
reason: it is minutes of wall clock and gigabytes of image.)

They are deliberately *not* mocked.  The thing under test is whether the toolkit
and the real judge agree about a verdict, and a fake judge would agree with
anything.
"""

from __future__ import annotations

import importlib.util
import os
import shutil
import sys
import zipfile
from pathlib import Path

import pytest

from problemsetting import judges, templates

OPT_IN = os.environ.get("PROBLEMSETTING_JUDGE_TESTS") == "1"
CONTAINER = "polijuez-judge-test"

pytestmark = [
    pytest.mark.skipif(
        not OPT_IN,
        reason="set PROBLEMSETTING_JUDGE_TESTS=1 (needs the judge image and podman)",
    ),
    pytest.mark.skipif(
        shutil.which("podman") is None, reason="podman is not installed"
    ),
]


@pytest.fixture(scope="module")
def problem() -> Path:
    """A complete, buildable ``standard`` problem: cases, archive, init.yml.

    Built from the shipped template's own generator and model solution rather
    than hand-written, so this exercises the same A+B problem the toolkit ships.

    It is created *inside the checkout* on purpose: the pool mounts the checkout
    at ``/problems``, and a submission source has to be under that mount to be
    gradeable.  Building it elsewhere would test a mount layout no real pool
    uses.  The directory is removed again by the fixture that owns it.
    """
    root = judges.repository_root()
    destination = root / "judge-pool-fixture"
    if destination.exists():
        shutil.rmtree(destination)
    shutil.copytree(
        templates.template_dir("standard"),
        destination,
        ignore=shutil.ignore_patterns(*templates.TEMPLATE_IGNORE),
    )

    spec = importlib.util.spec_from_file_location(
        "judge_pool_generator", destination / "generator.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["judge_pool_generator"] = module
    spec.loader.exec_module(module)

    cases = module.Generator().get_cases()
    with zipfile.ZipFile(destination / "cases.zip", "w") as archive:
        for index, case in enumerate(cases):
            archive.writestr(f"{index}.in", f"{case.a} {case.b}\n")
            archive.writestr(f"{index}.out", f"{case.a + case.b}\n")

    # One all-or-nothing batch: the `standard` model's shape (a single subtask
    # worth everything).  Later cases are 0 points so only case 0 carries weight,
    # exactly as the model's own comment describes.
    lines = ["archive: cases.zip", "test_cases:"]
    for index in range(len(cases)):
        points = 100 if index == 0 else 0
        lines.append(f"  - {{in: {index}.in, out: {index}.out, points: {points}}}")
    (destination / "init.yml").write_text("\n".join(lines) + "\n")
    yield destination
    shutil.rmtree(destination, ignore_errors=True)

@pytest.fixture(scope="module")
def pool(problem: Path):
    """A pool of one container, started once and removed at the end.

    Started through the toolkit's own ``launch_container``, so the container the
    tests grade through is the one ``judges start`` produces.
    """
    if not judges.image_exists():
        pytest.skip(judges.build_instructions())

    config = judges.write_config(judges.pool_dir(judges.repository_root()) / "judge.yml")
    judges.stop_container(CONTAINER)
    try:
        judges.launch_container(
            CONTAINER, problems_root=judges.repository_root(), config=config
        )
    except judges.JudgeError as error:
        pytest.skip(str(error))

    if not judges.wait_ready(CONTAINER):
        judges.stop_container(CONTAINER)
        pytest.fail("the judge container never reported ready")

    yield CONTAINER
    judges.stop_container(CONTAINER)


def test_the_image_is_present_and_named_as_production_names_it() -> None:
    if not judges.image_exists():
        pytest.skip(judges.build_instructions())
    assert judges.IMAGE == "localhost/dmoj/judge-tier3:latest"


def test_problem_discovery_finds_the_test_problem(pool: str, problem: Path) -> None:
    status, output = judges.run_command(
        pool, f"problems {problem.name}", command_id="test-problems"
    )
    assert status == 0
    assert problem.name in output


def test_the_model_solution_is_accepted(pool: str, problem: Path) -> None:
    grading = judges.submit(
        pool,
        problem.name,
        "CPP17",
        problem / "solution.cpp",
        time_limit=1.0,
        memory_limit=262144,
        command_id="test-model",
    )
    assert grading.compile_error is None, grading.raw
    assert grading.accepted, grading.raw
    assert grading.verdicts["AC"] == 21


def test_an_incorrect_submission_is_rejected_and_short_circuits(
    pool: str, problem: Path
) -> None:
    grading = judges.submit(
        pool,
        problem.name,
        "CPP17",
        problem / "submissions" / "incorrecto.cpp",
        time_limit=1.0,
        memory_limit=262144,
        command_id="test-wa",
    )
    assert not grading.accepted
    assert grading.verdicts.get("WA")
    # A failed case stops the rest of the batch: the remaining cases report "--".
    assert grading.verdicts.get("--"), grading.raw


def test_haskell_is_registered_and_grades(pool: str, problem: Path) -> None:
    """The whole point of the mempolicy patch: HASK must register and run.

    Without the patch the executor's self-test faults on syscall 239 and GHC is
    never registered, so this fails with "no valid runtime" rather than with a
    wrong verdict -- which is why the assertion is on the acceptance, not on the
    presence of an error message.
    """
    source = problem / "haskell-solution.hs"
    source.write_text(
        "main :: IO ()\n"
        "main = do\n"
        "  [a, b] <- (map read . words) <$> getContents\n"
        "  print (a + b :: Integer)\n"
    )
    grading = judges.submit(
        pool,
        problem.name,
        "HASK",
        source,
        time_limit=1.0,
        memory_limit=262144,
        command_id="test-hask",
    )
    assert grading.compile_error is None, grading.raw
    assert grading.accepted, grading.raw


def test_a_rebuilt_problem_is_rediscovered_without_a_restart(
    pool: str, problem: Path
) -> None:
    """Decision Q28: regenerating cases must not need a container restart."""
    assert judges.update_problems(pool) == "200 As you wish."
    grading = judges.submit(
        pool,
        problem.name,
        "CPP17",
        problem / "solution.cpp",
        time_limit=1.0,
        memory_limit=262144,
        command_id="test-after-update",
    )
    assert grading.accepted, grading.raw


# ---------------------------------------------------------------------------
# Cross-invocation pool identity
# ---------------------------------------------------------------------------


def test_a_started_pool_is_found_by_a_later_invocation(problem: Path) -> None:
    """``judges start`` in one process, discovered from another.

    Discovery is by container name, which is what makes the pool survive between
    invocations; this asserts the name the second invocation looks for is the one
    the first created.
    """
    if not judges.image_exists():
        pytest.skip(judges.build_instructions())
    # `ensure_pool` is what `judges start` calls; the image is present, so this
    # only starts (or adopts) the container.
    _, names, _ = judges.ensure_pool(1, root=judges.repository_root())
    assert names == [judges.container_name(1)]
    assert judges.container_name(1) in judges.running_containers()
    assert judges.stop_container(judges.container_name(1))
    assert judges.container_state(judges.container_name(1)) is None

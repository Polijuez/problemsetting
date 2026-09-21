"""Per-case points: the launcher's synthetic line, and reading it back.

DMOJ's transcript reports a case's verdict, time and memory but never what the
grader awarded it (``dmoj/judge.py:216`` ``_ipc_result``), so a checker that
returns ``CheckerResult(True, 0.7 * point_value)`` is indistinguishable on the
wire from one earning full marks.  The pool launcher therefore prints one extra
line per case, ``<<<DMOJ-POOL CASE <pos> <points>/<total>>>>``, straight from
the ``Result`` DMOJ hands its packet manager before that value is dropped.

What is asserted here is the round trip and its backward compatibility: the
transcript folds into :class:`problemsetting.judges.CaseResult` unchanged when
the line is absent, and carries the award when it is present.  The end-to-end
case -- a real checker, a real container, 0.7 observed -- is opt-in, because it
needs the 15 GB judge image::

    PROBLEMSETTING_JUDGE_TESTS=1 uv run pytest tests/test_case_points.py
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

import pytest

from problemsetting import judges
from problemsetting.judge_runtime import launcher

OPT_IN = os.environ.get("PROBLEMSETTING_JUDGE_TESTS") == "1"
CONTAINER = "polijuez-judge-casepoints"


#: A run as the launcher writes it: the case line first, then the points line
#: beside it.  Two batches are present because that is the shape the ``custom``
#: models emit.  Note the case numbers are *global*, not per batch: DMOJ's
#: ``case_number`` is a single counter across the whole run (``dmoj/judge.py``),
#: and it is that same number which is handed to the packet manager -- so the
#: fold matches the position on the points line against the number on the case
#: line, which holds however the judge chooses to number.
SCORED = """\
Start grading demo/7 in CPP17...
Batch #1
Test case  1 AC [0.003s (0.003s wall) | 1844kb | 10 switches (1 involuntary)] (suboptimal)
<<<DMOJ-POOL CASE 1 21.0/30>>>
Batch #2
Test case  2 AC [0.004s (0.004s wall) | 1900kb | 11 switches (1 involuntary)] (suboptimal)
<<<DMOJ-POOL CASE 2 49.0/70>>>
Test case  3 AC [0.004s (0.004s wall) | 1900kb | 11 switches (1 involuntary)] (optimal)
<<<DMOJ-POOL CASE 3 70/70>>>
Done grading demo/7.
"""

#: The same run as it is reported *without* the points line -- what a judge
#: driven outside the pool, or a launcher from before this line existed, emits.
UNSCORED = "".join(line + "\n" for line in SCORED.splitlines() if "<<<DMOJ-POOL" not in line)


# The launcher's side of the format
# ---------------------------------------------------------------------------


def test_the_launcher_line_carries_both_numbers_exactly() -> None:
    # `repr`, not `str`: a fractional award must not be rounded on its way into
    # the transcript.
    assert launcher.case_points_line(3, 21.0, 30) == "<<<DMOJ-POOL CASE 3 21.0/30>>>"
    assert "0.7" in launcher.case_points_line(1, 0.7, 1)


def test_the_launcher_line_is_readable_back() -> None:
    line = launcher.case_points_line(2, 0.7 * 30, 30)
    assert judges.parse_case_points(line) == (2, 21.0, 30.0)


def test_the_marker_is_the_pools_own_vocabulary() -> None:
    # The client only trusts its own framing, and a submission's output can
    # contain anything; the points line must stay inside that vocabulary so a
    # transcript cannot be forged by a submission printing a lookalike.
    assert launcher.case_points_line(1, 1.0, 1.0).startswith("<<<DMOJ-POOL ")


# ---------------------------------------------------------------------------
# Reading it back
# ---------------------------------------------------------------------------


def test_points_are_folded_into_the_case_they_follow() -> None:
    cases = judges.parse_cases(SCORED)
    assert [(case.number, case.points, case.total) for case in cases] == [
        (1, 21.0, 30.0),
        (2, 49.0, 70.0),
        (3, 70.0, 70.0),
    ]


def test_a_fractional_award_is_visible_as_a_share_of_the_case() -> None:
    assert [case.fraction for case in judges.parse_cases(SCORED)] == [0.7, 0.7, 1.0]


def test_the_verdicts_are_unchanged_by_the_extra_line() -> None:
    # The points line must not be mistaken for a result of its own.
    assert judges.parse_verdicts(SCORED) == {"AC": 3}
    assert judges.parse_verdicts(SCORED) == judges.parse_verdicts(UNSCORED)


def test_batched_cases_carry_their_points_too() -> None:
    # `verify` reads the batched shape, so the fold has to survive it.
    groups = judges.parse_batch_cases(SCORED)
    assert [len(group) for group in groups] == [1, 2]
    assert [[case.points for case in group] for group in groups] == [
        [21.0],
        [49.0, 70.0],
    ]
    assert judges.parse_batches(SCORED) == [["AC"], ["AC", "AC"]]


# ---------------------------------------------------------------------------
# Backward compatibility
# ---------------------------------------------------------------------------


def test_without_the_line_every_case_simply_has_no_points() -> None:
    cases = judges.parse_cases(UNSCORED)
    assert [case.verdict for case in cases] == ["AC", "AC", "AC"]
    assert all(case.points is None and case.total is None for case in cases)
    assert all(case.fraction is None for case in cases)


def test_an_unscored_transcript_parses_exactly_as_before() -> None:
    # The verdicts, batches and measurements are what every existing consumer
    # reads; the new field must not change any of them.
    scored_cases = judges.parse_cases(SCORED)
    unscored_cases = judges.parse_cases(UNSCORED)
    assert [(case.number, case.verdict, case.time, case.memory) for case in scored_cases] == [
        (case.number, case.verdict, case.time, case.memory) for case in unscored_cases
    ]
    assert judges.parse_batches(UNSCORED) == [["AC"], ["AC", "AC"]]


def test_a_zero_point_case_has_no_share_to_report() -> None:
    # Every verdict earns all of nothing; dividing would be the mistake.
    raw = "Test case  1 AC [0.002s (0.003s wall) | 100kb | 1 switch]\n<<<DMOJ-POOL CASE 1 0.0/0.0>>>\n"
    (case,) = judges.parse_cases(raw)
    assert (case.points, case.total, case.fraction) == (0.0, 0.0, None)


def test_a_stray_or_mismatched_points_line_is_ignored() -> None:
    # A doubled line, a line before any case, and a line whose position does not
    # match the case it follows all leave the run readable rather than wrong.
    raw = (
        "<<<DMOJ-POOL CASE 1 1.0/1.0>>>\n"
        "Test case  1 AC [0.001s (0.001s wall) | 1kb | 0 switches]\n"
        "<<<DMOJ-POOL CASE 9 1.0/1.0>>>\n"
        "<<<DMOJ-POOL CASE 1 0.5/1.0>>>\n"
    )
    (case,) = judges.parse_cases(raw)
    assert (case.number, case.points, case.total) == (1, None, None)


def test_a_malformed_points_line_does_not_lose_the_run() -> None:
    assert judges.parse_case_points("<<<DMOJ-POOL CASE 1 x/y>>>") is None
    assert judges.parse_case_points("<<<DMOJ-POOL CASE 1 1.0>>>") is None
    assert judges.parse_case_points("Test case  1 AC [0.001s]") is None


def test_an_ansi_wrapped_points_line_still_parses() -> None:
    # The launcher passes --no-ansi, but the parser has never depended on that.
    assert judges.parse_case_points("\x1b[1m<<<DMOJ-POOL CASE 1 0.7/1.0>>>\x1b[0m") == (1, 0.7, 1.0)


def test_the_grading_summary_still_reports_the_verdicts() -> None:
    grading = judges.parse_grading(SCORED, 0)
    assert grading.accepted
    assert grading.compile_error is None
    assert grading.failures == 0


def test_a_short_circuited_case_still_carries_its_points() -> None:
    """Observed on a real container: a skipped case gets a points line too.

    A one-batch/three-case problem whose first case fails reports the rest as
    ``--``; DMOJ still calls ``test_case_status_packet`` for each of them
    (``dmoj/judge.py``: an ``SC`` ``Result`` is built and yielded
    unconditionally), so the launcher prints a line for every case the
    transcript mentions.  Asserted here because a consumer that assumed only
    graded cases carry points would silently lose whole batches.
    """
    raw = (
        "Batch #1\n"
        "  Test case  1 WA [0.003s (0.004s wall) | 1652kb | 11 switches (1 involuntary)] \n"
        "<<<DMOJ-POOL CASE 1 0/100>>>\n"
        "  Test case  2 -- \n"
        "<<<DMOJ-POOL CASE 2 0/100>>>\n"
        "  Test case  3 -- \n"
        "<<<DMOJ-POOL CASE 3 0/100>>>\n"
    )
    cases = judges.parse_cases(raw)
    assert [(case.number, case.verdict) for case in cases] == [(1, "WA"), (2, "--"), (3, "--")]
    assert [case.points for case in cases] == [0.0, 0.0, 0.0]
    assert judges.parse_batch_cases(raw)[0] == cases


def test_feedback_containing_a_batch_header_does_not_hide_its_case() -> None:
    """A checker's feedback can quote the submission's own text back.

    DMOJ interpolates ``result.feedback`` into the ``Test case`` line
    (``dmoj/judge.py`` ``colored_feedback``), and the shipped ``custom``
    checker echoes the submission's first token -- so a submission whose first
    token is ``Batch #1`` produces a case line that also matches the batch
    header.  :func:`parse_cases` has always read such a line as the case it
    reports; reading it as a header instead would silently drop the case and
    report a failing submission as accepted.
    """
    raw = (
        "Batch #1\n"
        "  Test case  1 AC [0.001s (0.001s wall) | 1kb | 0 switches] \n"
        "  Test case  2 WA [0.001s (0.001s wall) | 1kb | 0 switches] "
        "(la primera línea no es un entero: 'Batch #1') \n"
    )
    assert [case.verdict for case in judges.parse_cases(raw)] == ["AC", "WA"]
    grading = judges.parse_grading(raw, 0)
    assert grading.verdicts == {"AC": 1, "WA": 1}
    assert grading.failures == 1
    assert not grading.accepted


# ---------------------------------------------------------------------------
# End to end: a real checker, a real container.  Opt-in.
# ---------------------------------------------------------------------------

#: A quality checker: any integer is accepted, but only the best one is worth
#: full marks -- ``CheckerResult(True, 0.7 * point_value)``.  This is the exact
#: shape the ``custom``/``batched-custom`` models ship, and the shape that made
#: ``verify`` report 100/100 for a 70-point answer before this ticket.
CHECKER = """\
from dmoj.result import CheckerResult
from dmoj.utils.unicode import utf8text


def check(process_output, judge_output, judge_input, point_value, submission_source, **kwargs):
    got = utf8text(process_output).split()
    if not got:
        return CheckerResult(False, 0)
    try:
        claimed = int(got[0])
    except ValueError:
        return CheckerResult(False, 0)
    best = int(utf8text(judge_output).split()[0])
    if claimed != best:
        return CheckerResult(True, 0.7 * point_value, feedback="suboptimal")
    return CheckerResult(True, point_value, feedback="optimal")
"""

#: Prints the sum minus one: accepted, worth 0.7.
SUBOPTIMAL = """\
#include <cstdio>
int main() { int a, b, c; if (scanf("%d %d %d", &a, &b, &c) != 3) return 1; printf("%d\\n", a + b + c - 1); }
"""

#: Prints the sum: full marks.
OPTIMAL = """\
#include <cstdio>
int main() { int a, b, c; if (scanf("%d %d %d", &a, &b, &c) != 3) return 1; printf("%d\\n", a + b + c); }
"""


#: The end-to-end tests below need the image *and* podman; the ``pool`` fixture
#: starts a container itself, so a host without podman must skip rather than
#: raise from the fixture.  Named marks, so the reason is stated once.
NEEDS_THE_JUDGE = pytest.mark.skipif(
    not OPT_IN, reason="set PROBLEMSETTING_JUDGE_TESTS=1 (needs the judge image and podman)"
)
NEEDS_PODMAN = pytest.mark.skipif(
    shutil.which("podman") is None, reason="podman is not installed"
)


# ---------------------------------------------------------------------------
# End to end: a real checker, a real container.  Opt-in.
# ---------------------------------------------------------------------------



@pytest.fixture(scope="module")
def problem() -> Path:
    """A hand-made two-batch problem whose checker awards 0.7 on a suboptimal answer.

    It lives *inside* the checkout because the pool mounts the checkout at
    ``/problems`` and only files under that mount are gradeable; it is a normal
    directory, never a dot-directory, because DMOJ discovers problems with
    ``glob``, which skips leading-dot path components.
    """
    root = judges.repository_root()
    destination = root / "case-points-fixture"
    if destination.exists():
        shutil.rmtree(destination)
    (destination / "cases").mkdir(parents=True)

    (destination / "checker.py").write_text(CHECKER)
    (destination / "optimal.cpp").write_text(OPTIMAL)
    (destination / "suboptimal.cpp").write_text(SUBOPTIMAL)
    # Two batches with different inputs and different point values, so both the
    # per-batch totals and the (global) case numbering are exercised.  The
    # checker's `best` is the true sum, so an answer one short is accepted at
    # 0.7 and the exact sum earns full marks.
    batches = [(1, "1 2 3", 30), (2, "10 20 30", 70)]
    lines = ["checker: checker.py", "test_cases:"]
    for batch_number, values, points in batches:
        answer = sum(int(value) for value in values.split())
        (destination / "cases" / f"{batch_number}.in").write_text(values + "\n")
        (destination / "cases" / f"{batch_number}.out").write_text(f"{answer}\n")
        lines.append(f"- points: {points}")
        lines.append("  batched:")
        lines.append(
            f"  - {{in: cases/{batch_number}.in, out: cases/{batch_number}.out}}"
        )
    (destination / "init.yml").write_text("\n".join(lines) + "\n")

    yield destination
    shutil.rmtree(destination, ignore_errors=True)


@pytest.fixture(scope="module")
def pool(problem: Path):
    """A pool of one container under this module's own name.

    Started through the toolkit's own ``launch_container`` so the container the
    test grades through is exactly the one ``judges start`` produces.  It is not
    the sibling pool: those containers belong to other agents, and stopping one
    would pull the floor out from under them.
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


@NEEDS_THE_JUDGE
@NEEDS_PODMAN
def test_a_real_checker_awarding_0_7_is_observable(pool: str, problem: Path) -> None:
    """The point of the ticket: 0.7 of the case, read off a real judge.

    The verdict is ``AC`` either way -- that is exactly why the gap existed --
    so the assertion is on the points, and on the line the launcher printed to
    carry them.
    """
    grading = judges.submit(
        pool,
        problem.name,
        "CPP17",
        problem / "suboptimal.cpp",
        time_limit=1.0,
        memory_limit=262144,
        command_id="case-points-suboptimal",
    )
    assert grading.compile_error is None, grading.raw
    # The transcript carries one points line per case, beside the case line.
    # `total_points` is the `init.yml` value, so it is `30`/`70` unsuffixed,
    # while the award is drawn from it and is fractional.
    points_lines = [
        line for line in grading.raw.splitlines() if line.startswith("<<<DMOJ-POOL CASE")
    ]
    assert len(points_lines) == 2, grading.raw
    assert points_lines[0] == "<<<DMOJ-POOL CASE 1 21.0/30>>>", grading.raw
    assert points_lines[1] == "<<<DMOJ-POOL CASE 2 49.0/70>>>", grading.raw

    # And every case reports the fraction the checker awarded: 0.7 twice, over
    # batches that are worth different amounts (30 and 70) -- which is the whole
    # point, since the verdict was AC in both cases.
    cases = judges.parse_cases(grading.raw)
    assert [case.points for case in cases] == [21.0, 49.0], grading.raw
    assert [case.fraction for case in cases] == [0.7, 0.7], grading.raw
    assert judges.parse_verdicts(grading.raw) == {"AC": 2}


@NEEDS_THE_JUDGE
@NEEDS_PODMAN
def test_full_marks_still_report_as_full_marks(pool: str, problem: Path) -> None:
    grading = judges.submit(
        pool,
        problem.name,
        "CPP17",
        problem / "optimal.cpp",
        time_limit=1.0,
        memory_limit=262144,
        command_id="case-points-optimal",
    )
    assert grading.compile_error is None, grading.raw
    assert [case.fraction for case in judges.parse_cases(grading.raw)] == [1.0, 1.0]

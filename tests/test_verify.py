"""``verify``: the submissions manifest, the grading loop, and the comparison.

Everything here runs offline.  The manifest reader, the language and limit
resolution, the batch attribution and the expectation comparison are pure enough
to test directly, and they are where the mistakes are silent -- an entry quietly
dropped, limits read from the wrong language, a batch paid after a failure, a
mismatch that does not fail the run.

Grading itself goes through :mod:`problemsetting.judges`, which is exercised
against a real container by the opt-in ``test_judge_pool`` suite; what is tested
here is that ``verify`` hands the judge the values it resolved and reads back
what the judge reported.
"""

from __future__ import annotations

import dataclasses
import textwrap
from pathlib import Path

import pytest
import yaml

from problemsetting import commands
from problemsetting import judges
from problemsetting import meta as meta_mod
from problemsetting import verify
from problemsetting.errors import VerifyError

#: A real ``dmoj`` transcript for a batched problem: batch 1 passes, batch 2
#: fails and short-circuits, which is what makes partial credit visible.
BATCHED = """\
Start grading demo/1 in CPP17...
Batch #1
Test case  1 AC [0.002s (0.002s wall) | 3000kb | 10 switches (1 involuntary)]
Test case  2 AC [0.002s (0.002s wall) | 3000kb | 10 switches (1 involuntary)]
Batch #2
Test case  1 AC [0.003s (0.003s wall) | 4000kb | 10 switches (1 involuntary)]
Test case  2 WA [0.003s (0.003s wall) | 4200kb | 10 switches (1 involuntary)]
Test case  3 --
Done grading demo/1.
"""

STATEMENT = """\
class TestCase:
    def __init__(self):
        pass

    def write_file(self, f):
        f.write("1\\n")


class Generator:
    def __init__(self, seed=0):
        pass

    def get_cases(self):
        return [TestCase()]

    def get_subtasks(self):
        return [(30, lambda case: True), (70, lambda case: True)]
"""

META = """\
model: standard
solutionlang: .cpp
limits:
  .cpp:
    tl: 1.0
    ml: 262144
"""


@pytest.fixture
def problem(tmp_path: Path) -> Path:
    """A problem directory with ``meta.yml`` and one C++ source to grade."""
    (tmp_path / "meta.yml").write_text(META, encoding="utf-8")
    (tmp_path / "submissions").mkdir()
    (tmp_path / "solution.cpp").write_text("int main(){}\n", encoding="utf-8")
    (tmp_path / "submissions" / "wrong.cpp").write_text("int main(){}\n", encoding="utf-8")
    return tmp_path


def write_manifest(problem: Path, body: str) -> None:
    (problem / "submissions.yml").write_text(
        "submissions:\n" + textwrap.dedent(body).lstrip(), encoding="utf-8"
    )


def manifest_entries(problem: Path) -> list[verify.Entry]:
    _, resolved = meta_mod.load(problem)
    return verify.load_manifest(problem, resolved)


# ---------------------------------------------------------------------------
# Parsing the manifest
# ---------------------------------------------------------------------------


def test_every_field_is_read(problem: Path) -> None:
    write_manifest(
        problem,
        """\
        - source: solution.cpp
          verdict: AC
          score: 100
          role: model
        """,
    )
    (entry,) = manifest_entries(problem)
    assert entry.source == Path("solution.cpp")
    assert entry.path == (problem / "solution.cpp").resolve()
    assert entry.verdict == "AC"
    assert entry.score == 100.0
    assert entry.role == "model"
    assert entry.executor == "CPP17"


def test_the_only_required_key_is_source(problem: Path) -> None:
    write_manifest(problem, "- source: solution.cpp\n")
    (entry,) = manifest_entries(problem)
    assert not entry.declares_expectation
    assert entry.verdict is None and entry.score is None and entry.role is None


def test_a_missing_manifest_names_the_file_to_create(tmp_path: Path) -> None:
    (tmp_path / "meta.yml").write_text(META, encoding="utf-8")
    _, resolved = meta_mod.load(tmp_path)
    with pytest.raises(VerifyError, match=r"submissions\.yml"):
        verify.load_manifest(tmp_path, resolved)


def test_an_unknown_key_names_the_entry_and_the_valid_keys(problem: Path) -> None:
    write_manifest(
        problem,
        """\
        - source: solution.cpp
          verdicts: AC
        """,
    )
    with pytest.raises(VerifyError) as info:
        manifest_entries(problem)
    message = str(info.value)
    assert "entry 1" in message
    assert "solution.cpp" in message
    assert "'verdicts'" in message
    assert "valid keys: source, verdict, score, role, executor" in message


def test_a_missing_source_names_the_entry_and_the_path_looked_for(problem: Path) -> None:
    write_manifest(
        problem,
        """\
        - source: solution.cpp
        - source: submissions/typo.cpp
        """,
    )
    with pytest.raises(VerifyError) as info:
        manifest_entries(problem)
    message = str(info.value)
    assert "entry 2" in message
    assert "submissions/typo.cpp" in message
    assert str(problem / "submissions" / "typo.cpp") in message


def test_an_invalid_verdict_lists_the_codes(problem: Path) -> None:
    write_manifest(problem, "- source: solution.cpp\n  verdict: OK\n")
    with pytest.raises(VerifyError, match="must be one of AC, CE, IE, TLE"):
        manifest_entries(problem)


def test_a_score_outside_its_percentage_range_is_refused(problem: Path) -> None:
    write_manifest(problem, "- source: solution.cpp\n  score: 120\n")
    with pytest.raises(VerifyError, match="between 0 and 100"):
        manifest_entries(problem)


def test_an_empty_submissions_list_is_refused(problem: Path) -> None:
    (problem / "submissions.yml").write_text("submissions: []\n", encoding="utf-8")
    with pytest.raises(VerifyError, match="non-empty list"):
        manifest_entries(problem)


def test_a_non_mapping_entry_is_refused(problem: Path) -> None:
    (problem / "submissions.yml").write_text("submissions:\n  - solution.cpp\n", encoding="utf-8")
    with pytest.raises(VerifyError, match="entry 1 must be a mapping"):
        manifest_entries(problem)


def test_an_unknown_top_level_key_is_refused(problem: Path) -> None:
    (problem / "submissions.yml").write_text(
        "submission:\n  - source: solution.cpp\n", encoding="utf-8"
    )
    with pytest.raises(VerifyError, match="the only top-level key is 'submissions:'"):
        manifest_entries(problem)


# ---------------------------------------------------------------------------
# Language inference and limits
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("name", "executor"),
    [
        ("a.c", "C11"),
        ("a.cpp", "CPP17"),
        ("a.hs", "HASK"),
        ("a.java", "JAVA"),
        ("a.py", "PY3"),
        ("a.txt", "TEXT"),
    ],
)
def test_the_executor_is_inferred_from_the_extension(problem: Path, name: str, executor: str) -> None:
    (problem / name).write_text("x", encoding="utf-8")
    write_manifest(problem, f"- source: {name}\n")
    assert manifest_entries(problem)[0].executor == executor


def test_an_unknown_extension_says_how_to_grade_it_anyway(problem: Path) -> None:
    (problem / "a.rs").write_text("x", encoding="utf-8")
    write_manifest(problem, "- source: a.rs\n")
    with pytest.raises(VerifyError, match="add an `executor:` override"):
        manifest_entries(problem)


def test_an_executor_override_wins_over_the_extension(problem: Path) -> None:
    write_manifest(problem, "- source: solution.cpp\n  executor: CPP23\n")
    assert manifest_entries(problem)[0].executor == "CPP23"


def test_an_unknown_executor_override_is_refused(problem: Path) -> None:
    write_manifest(problem, "- source: solution.cpp\n  executor: CPP99\n")
    with pytest.raises(VerifyError, match="not a DMOJ executor"):
        manifest_entries(problem)


def test_limits_come_from_the_entrys_language_in_kib(problem: Path) -> None:
    write_manifest(problem, "- source: solution.cpp\n")
    (entry,) = manifest_entries(problem)
    assert entry.limits_key == ".cpp"
    assert entry.limits.time == 1.0
    # KiB, exactly what `submit -ml` takes: no conversion anywhere.
    assert entry.limits.memory == 262144


def test_a_language_without_a_limits_entry_falls_back_to_the_default(problem: Path) -> None:
    (problem / "a.py").write_text("x", encoding="utf-8")
    write_manifest(problem, "- source: a.py\n")
    (entry,) = manifest_entries(problem)
    assert entry.limits_key == ".py"
    assert entry.limits.time == meta_mod.DEFAULT_TL
    assert entry.limits.memory == meta_mod.DEFAULT_ML


def test_an_override_uses_the_family_it_belongs_to(problem: Path) -> None:
    """``PYPY3`` on a ``.py`` file is still a ``.py`` problem's limits."""
    (problem / "a.py").write_text("x", encoding="utf-8")
    write_manifest(problem, "- source: a.py\n  executor: PYPY3\n")
    assert manifest_entries(problem)[0].limits_key == ".py"


def test_an_override_crossing_language_families_uses_the_family_extension(problem: Path) -> None:
    """A ``.txt`` file graded as C is a C problem for limits, not a ``.txt`` one."""
    (problem / "a.txt").write_text("x", encoding="utf-8")
    write_manifest(problem, "- source: a.txt\n  executor: C11\n")
    assert manifest_entries(problem)[0].limits_key == ".c"


# ---------------------------------------------------------------------------
# Batch plans and attribution
# ---------------------------------------------------------------------------

INIT = """\
archive: demo.zip
test_cases:
- points: 30
  batched:
  - {in: cases/0.in, out: cases/0.out}
- points: 70
  batched:
  - {in: cases/1.in, out: cases/1.out}
"""


def test_batch_plans_read_each_batchs_points(problem: Path) -> None:
    (problem / "init.yml").write_text(INIT, encoding="utf-8")
    plans = verify.batch_plans(problem)
    assert [(plan.number, plan.points) for plan in plans] == [(1, 30.0), (2, 70.0)]


def test_a_case_outside_a_batch_is_refused(problem: Path) -> None:
    (problem / "init.yml").write_text(
        "archive: demo.zip\ntest_cases:\n- {in: cases/0.in, out: cases/0.out}\n",
        encoding="utf-8",
    )
    with pytest.raises(VerifyError, match="not inside a batch"):
        verify.batch_plans(problem)


def test_points_default_to_one_the_way_dmoj_defaults_them(problem: Path) -> None:
    (problem / "init.yml").write_text(
        "archive: demo.zip\ntest_cases:\n- batched:\n  - {in: a.in, out: a.out}\n",
        encoding="utf-8",
    )
    assert verify.batch_plans(problem)[0].points == 1.0


def _plans() -> list[verify.BatchPlan]:
    return [verify.BatchPlan(1, 30.0), verify.BatchPlan(2, 70.0)]


def test_a_passed_batch_earns_its_points_and_a_failed_one_earns_nothing() -> None:
    groups = judges.parse_batch_cases(BATCHED)
    scores = verify.attribute(_plans(), groups)
    assert [(batch.earned, batch.points) for batch in scores] == [(30.0, 30.0), (0.0, 70.0)]


def test_a_skipped_case_fails_its_batch() -> None:
    """``--`` is a case skipped after an earlier failure, so it cannot pass."""
    raw = "Batch #1\nTest case  1 AC [0.001s (0.001s wall) | 1kb | 0 switches]\nTest case  2 --\n"
    scores = verify.attribute(_plans()[:1], judges.parse_batch_cases(raw))
    assert scores[0].earned == 0.0
    assert scores[0].verdict == "SC"


def test_partial_credit_is_the_successful_batches() -> None:
    """The point of the whole feature: a subtask that passed is visible as 30/100."""
    groups = judges.parse_batch_cases(BATCHED)
    report = verify.Report(
        entry=_entry(), cases=judges.parse_cases(BATCHED), batches=verify.attribute(_plans(), groups), compile_error=None
    )
    assert (report.earned, report.total, report.score) == (30.0, 100.0, 30.0)
    assert [batch.passed for batch in report.batches] == [True, False]


# ---------------------------------------------------------------------------
# Verdicts
# ---------------------------------------------------------------------------


def _entry(**kwargs) -> verify.Entry:
    defaults = {
        "index": 1,
        "source": Path("solution.cpp"),
        "path": Path("/tmp/solution.cpp"),
        "executor": "CPP17",
        "limits": meta_mod.Limits(1.0, 262144),
        "limits_key": ".cpp",
        "verdict": None,
        "score": None,
        "role": None,
    }
    return verify.Entry(**{**defaults, **kwargs})


def _report(raw: str, *, compile_error: str | None = None, **entry_kwargs) -> verify.Report:
    groups = judges.parse_batch_cases(raw)
    return verify.Report(
        entry=_entry(**entry_kwargs),
        cases=judges.parse_cases(raw),
        batches=verify.attribute(_plans(), groups),
        compile_error=compile_error,
    )


def test_an_all_accepted_run_is_ac() -> None:
    raw = "Batch #1\nTest case  1 AC [0.001s (0.001s wall) | 1kb | 0 switches]\n"
    assert _report(raw).verdict == "AC"


def test_the_headline_verdict_is_the_worst_one() -> None:
    raw = (
        "Batch #1\n"
        "Test case  1 AC [0.001s (0.001s wall) | 1kb | 0 switches]\n"
        "Test case  2 WA [0.001s (0.001s wall) | 1kb | 0 switches]\n"
        "Test case  3 TLE [2.001s (2.001s wall) | 1kb | 0 switches]\n"
    )
    assert _report(raw).verdict == "TLE"


def test_a_skipped_case_does_not_mask_a_real_verdict() -> None:
    """An intended-TLE submission is TLE, not ``SC``, though its batch was skipped."""
    raw = "Batch #1\nTest case  1 TLE [2.001s (2.001s wall) | 1kb | 0 switches]\nTest case  2 --\n"
    assert _report(raw).verdict == "TLE"


def test_a_run_that_was_all_skipped_is_sc() -> None:
    assert _report("Batch #1\nTest case  1 --\n").verdict == "SC"


def test_a_compile_error_is_ce_regardless_of_status() -> None:
    report = _report("", compile_error="Failed compiling submission!")
    assert report.verdict == "CE"


def test_measurements_are_the_worst_case_the_judge_reported() -> None:
    report = _report(BATCHED)
    assert report.slowest == 0.003
    assert report.memory == 4200


def test_a_run_that_reported_nothing_is_not_accepted() -> None:
    """The one thing an `AC` expectation must never be told: nothing was graded."""
    report = verify.Report(entry=_entry(verdict="AC"), cases=[], batches=[], compile_error=None)
    assert report.verdict == "not run"
    assert verify.mismatches(report) == [("verdict AC", "verdict not run")]


def test_a_batch_the_judge_did_not_report_is_not_accepted() -> None:
    """What a compile error leaves behind: declared batches with no cases."""
    report = _report("", compile_error=None)
    assert report.verdict == "not run"
    assert [batch.verdict for batch in report.batches] == ["not run", "not run"]


def test_a_score_of_zero_is_not_satisfied_by_a_run_that_graded_nothing() -> None:
    """A declared 0 must come from a graded run, not from an ungraded one.

    ``Report.score`` is 0 when there is nothing to score, so comparing that
    against a declared ``score: 0`` would pass a submission nothing graded --
    the silent-pass failure mode `verify` exists to prevent.
    """
    report = verify.Report(entry=_entry(score=0), cases=[], batches=[], compile_error=None)
    assert verify.mismatches(report) == [("score 0/100", "score not run")]


# ---------------------------------------------------------------------------
# Expected vs actual
# ---------------------------------------------------------------------------


def test_a_matching_run_has_no_mismatches() -> None:
    report = dataclasses.replace(_report(BATCHED), entry=_entry(verdict="WA", score=30.0))
    assert verify.mismatches(report) == []


def test_a_wrong_verdict_is_a_mismatch_side_by_side() -> None:
    report = dataclasses.replace(_report(BATCHED), entry=_entry(verdict="TLE"))
    assert verify.mismatches(report) == [("verdict TLE", "verdict WA")]


def test_a_wrong_score_is_a_mismatch() -> None:
    report = dataclasses.replace(_report(BATCHED), entry=_entry(score=100))
    assert verify.mismatches(report) == [("score 100/100", "score 30/100")]


def test_a_score_declared_to_the_printed_precision_matches() -> None:
    """Three equal batches, one passed, pay a third; ``33.33`` must not fail."""
    raw = (
        "Batch #1\nTest case  1 AC [0.001s (0.001s wall) | 1kb | 0 switches]\n"
        "Batch #2\nTest case  1 WA [0.001s (0.001s wall) | 1kb | 0 switches]\n"
        "Batch #3\nTest case  1 WA [0.001s (0.001s wall) | 1kb | 0 switches]\n"
    )
    plans = [verify.BatchPlan(n, 1.0) for n in (1, 2, 3)]
    report = verify.Report(
        entry=_entry(score=33.33),
        cases=judges.parse_cases(raw),
        batches=verify.attribute(plans, judges.parse_batch_cases(raw)),
        compile_error=None,
    )
    assert report.score == pytest.approx(33.333333, abs=1e-4)
    assert verify.mismatches(report) == []


def test_an_entry_with_no_expectation_declares_none() -> None:
    assert not _entry().declares_expectation
    assert _entry(verdict="AC").declares_expectation
    assert _entry(score=0).declares_expectation

# ---------------------------------------------------------------------------
# The six checks
# ---------------------------------------------------------------------------

#: The `standard` model: no checker, so checks 5 reports a skip.
STANDARD_META = META
#: A model with a checker, so check 5 has something to assert about.
CUSTOM_META = """\
model: custom
solutionlang: .cpp
limits:
  .cpp:
    tl: 1.0
    ml: 262144
"""


def _resolved(meta_text: str = STANDARD_META) -> meta_mod.ResolvedMeta:
    return meta_mod.resolve(yaml.safe_load(meta_text))


def _report_for(raw: str, **entry_kwargs) -> verify.Report:
    """One graded run over ``raw``, with the entry fields ``entry_kwargs`` names."""
    return _report(raw, **entry_kwargs)


#: Every case accepted, which is full marks for the model solution.
AC_RUN = "Batch #1\nTest case  1 AC [0.002s (0.002s wall) | 3000kb | 1 switch]\nBatch #2\nTest case  1 AC [0.003s (0.003s wall) | 4000kb | 1 switch]\n"


def _checks(
    reports, meta_text: str = STANDARD_META, checker: str | None = None
) -> dict[int, verify.Check]:
    return {
        check.number: check
        for check in verify.run_checks(reports, _resolved(meta_text), checker)
    }


def test_check_1_passes_when_the_model_solution_scores_full_marks() -> None:
    report = _report_for(AC_RUN, role="model")
    check = _checks([report])[1]
    assert check.status == verify.PASS
    assert check.number == 1 and check.name == verify.CHECK_NAMES[1]


def test_check_1_fails_when_the_model_solution_is_not_accepted() -> None:
    """A broken model solution must be caught here, not only in the entry's own FAIL."""
    report = _report_for(BATCHED, role="model")
    check = _checks([report])[1]
    assert check.status == verify.FAIL
    assert check.problems and "solution.cpp" in check.problems[0]


def test_check_1_fails_when_an_accepted_run_earns_only_part_of_the_points() -> None:
    """A scoring checker can pass with fewer points; ``AC`` alone is not full marks."""
    shortened = "Batch #1\nTest case  1 AC [0.001s (0.001s wall) | 1kb | 1 switch]\n"
    report = _report_for(shortened, role="model")
    assert report.verdict == "AC"
    assert verify.check_model_solution([report]).status == verify.FAIL


def test_check_1_is_skipped_with_a_reason_without_a_model_role() -> None:
    check = _checks([_report_for(AC_RUN)])[1]
    assert check.status == verify.SKIP
    assert "role: model" in check.detail


def test_check_2_passes_when_the_declared_failing_verdict_matches() -> None:
    report = _report_for(BATCHED, verdict="WA")
    check = _checks([report])[2]
    assert check.status == verify.PASS


def test_check_2_fails_when_an_intended_wrong_submission_is_accepted() -> None:
    """The headline failure: the problem stopped rejecting a wrong answer."""
    report = _report_for(AC_RUN, verdict="WA")
    check = _checks([report])[2]
    assert check.status == verify.FAIL
    assert "verdict WA" in check.problems[0]


def test_check_2_does_not_exclude_a_tle_declaration() -> None:
    """TLE is a failing verdict, so it is check 2's subject as well as check 3's."""
    report = _report_for(BATCHED, verdict="TLE")
    checks = _checks([report])
    assert checks[2].status == verify.FAIL
    assert checks[3].status == verify.FAIL


def test_check_2_excludes_the_checker_test_entry() -> None:
    """A checker-test's verdict is check 5's, not this one's."""
    report = _report_for(BATCHED, verdict="WA", role="checker-test")
    assert _checks([report])[2].status == verify.SKIP


def test_check_2_is_skipped_with_a_reason_without_a_failing_declaration() -> None:
    check = _checks([_report_for(AC_RUN, verdict="AC")])[2]
    assert check.status == verify.SKIP
    assert "failing verdict" in check.detail


def test_check_3_passes_when_a_declared_tle_really_tles() -> None:
    raw = "Batch #1\nTest case  1 TLE [1.001s (1.001s wall) | 1kb | 1 switch]\nTest case  2 --\nBatch #2\nTest case  1 --\n"
    report = _report_for(raw, verdict="TLE")
    check = _checks([report])[3]
    assert check.status == verify.PASS
    assert "tl=1s" in check.detail


def test_check_3_fails_when_the_too_slow_submission_finishes() -> None:
    """A time limit that is not tight: the slow submission was accepted."""
    report = _report_for(AC_RUN, verdict="TLE")
    check = _checks([report])[3]
    assert check.status == verify.FAIL
    assert "expected TLE" in check.problems[0]


def test_check_3_is_skipped_with_a_reason_without_a_tle_declaration() -> None:
    check = _checks([_report_for(BATCHED, verdict="WA")])[3]
    assert check.status == verify.SKIP
    assert "verdict: TLE" in check.detail


def test_check_3_fails_when_the_slow_submission_was_wrong_as_well() -> None:
    """TLE alone proves nothing: a wrong-and-slow submission proves nothing about the limit."""
    raw = (
        "Batch #1\n"
        "Test case  1 WA [0.001s (0.001s wall) | 1kb | 1 switch]\n"
        "Test case  2 --\n"
        "Batch #2\n"
        "Test case  1 TLE [1.001s (1.001s wall) | 1kb | 1 switch]\n"
    )
    check = _checks([_report_for(raw, verdict="TLE")])[3]
    assert check.status == verify.FAIL
    assert "wrong-and-slow" in check.problems[0]


def test_check_3_passes_when_the_slow_submission_was_correct_until_it_timed_out() -> None:
    raw = (
        "Batch #1\n"
        "Test case  1 AC [0.001s (0.001s wall) | 1kb | 1 switch]\n"
        "Test case  2 TLE [1.001s (1.001s wall) | 1kb | 1 switch]\n"
        "Test case  3 --\n"
    )
    check = _checks([_report_for(raw, verdict="TLE")])[3]
    assert check.status == verify.PASS
    assert "AC on 1 case(s) and no wrong answer" in check.detail


def test_check_3_says_when_the_correctness_rests_on_the_declaration_alone() -> None:
    """A timeout before any case completed observed no correct case."""
    raw = "Batch #1\nTest case  1 TLE [1.001s (1.001s wall) | 1kb | 1 switch]\nTest case  2 --\n"
    check = _checks([_report_for(raw, verdict="TLE")])[3]
    assert check.status == verify.PASS
    assert "rests on its declaration" in check.detail


def test_check_4_passes_when_the_brute_force_is_accepted_on_every_declared_case() -> None:
    report = _report_for(AC_RUN, role="brute")
    check = _checks([report])[4]
    assert check.status == verify.PASS
    assert "matching the model solution" in check.detail


def test_check_4_fails_when_the_brute_force_disagrees() -> None:
    """The expected outputs are the model solution's; a rejection is a disagreement."""
    report = _report_for(BATCHED, role="brute")
    check = _checks([report])[4]
    assert check.status == verify.FAIL
    assert "disagreement" in check.problems[0]


def test_check_4_fails_when_the_brute_force_was_never_graded() -> None:
    """Not graded is not agreement: this is the check that cannot silently pass."""
    report = dataclasses.replace(
        _report_for("", role="brute"),
        compile_error="Failed compiling submission!",
    )
    check = _checks([report])[4]
    assert check.status == verify.FAIL
    assert "never graded" in check.problems[0]


def test_check_4_is_skipped_with_a_reason_without_a_brute_role() -> None:
    check = _checks([_report_for(AC_RUN)])[4]
    assert check.status == verify.SKIP
    assert "role: brute" in check.detail


CHECKER_FILE = "checker.py"


def test_check_5_passes_when_the_checker_rejects_the_malformed_output() -> None:
    report = _report_for(BATCHED, role="checker-test", verdict="WA")
    check = _checks([report], CUSTOM_META, CHECKER_FILE)[5]
    assert check.status == verify.PASS
    assert f"WA, which is {CHECKER_FILE} rejecting it" in check.detail


def test_check_5_fails_when_the_checker_accepts_it() -> None:
    report = _report_for(AC_RUN, role="checker-test", verdict="WA")
    check = _checks([report], CUSTOM_META, CHECKER_FILE)[5]
    assert check.status == verify.FAIL
    assert "accepted a deliberately malformed output" in check.problems[0]


def test_check_5_fails_when_the_malformed_output_was_never_graded() -> None:
    report = dataclasses.replace(
        _report_for("", role="checker-test", verdict="WA"),
        compile_error="Failed compiling submission!",
    )
    check = _checks([report], CUSTOM_META, CHECKER_FILE)[5]
    assert check.status == verify.FAIL
    assert "no rejection was observed" in check.problems[0]


def test_check_5_fails_on_a_verdict_that_means_the_checker_never_ran() -> None:
    """DMOJ skips the checker for a submission that already failed; RTE proves nothing."""
    raw = "Batch #1\nTest case  1 RTE [0.001s (0.001s wall) | 1kb | 1 switch]\n"
    check = _checks([_report_for(raw, role="checker-test", verdict="WA")], CUSTOM_META, CHECKER_FILE)[5]
    assert check.status == verify.FAIL
    assert "never ran" in check.problems[0]


def test_check_5_passes_only_on_a_wa_rejection() -> None:
    raw = "Batch #1\nTest case  1 WA [0.001s (0.001s wall) | 1kb | 1 switch]\n"
    check = _checks([_report_for(raw, role="checker-test", verdict="WA")], CUSTOM_META, CHECKER_FILE)[5]
    assert check.status == verify.PASS


def test_check_5_is_skipped_with_a_reason_on_a_model_without_a_checker() -> None:
    check = _checks([_report_for(BATCHED, role="checker-test", verdict="WA")])[5]
    assert check.status == verify.SKIP
    assert "no checker" in check.detail and "standard" in check.detail


def test_check_5_will_not_trust_a_checker_axis_init_yml_does_not_carry() -> None:
    """``meta.yml`` asking for a checker the judge does not have is not a pass.

    DMOJ reads ``checker:`` from ``init.yml`` (``dmoj/problem.py:506``), so a
    ``meta.yml`` whose ``checker: custom`` was never regenerated into it leaves
    the standard comparison in force -- and a ``WA`` from that comparison is not
    a checker rejecting anything.
    """
    check = _checks([_report_for(BATCHED, role="checker-test", verdict="WA")], CUSTOM_META)[5]
    assert check.status == verify.SKIP
    assert "init.yml declares no `checker:`" in check.detail
    assert "problemsetting cases" in check.detail


def test_check_5_is_skipped_when_no_checker_test_is_declared() -> None:
    check = _checks([_report_for(BATCHED, verdict="WA")], CUSTOM_META, CHECKER_FILE)[5]
    assert check.status == verify.SKIP
    assert "role: checker-test" in check.detail


def test_check_6_reports_the_measurements_and_the_limits_in_force() -> None:
    """Reporting only: the check passes by reporting, and names the limits."""
    check = _checks([_report_for(BATCHED)])[6]
    assert check.status == verify.PASS
    assert "slowest case 0.003s" in check.detail
    assert "peak 4200 KiB" in check.detail
    assert "tl=1s ml=262144KiB" in check.detail
    assert "never set from these" in check.detail


def test_check_6_reports_the_measurements_of_a_failed_run_too() -> None:
    """Calibration needs the observation even when the submission was rejected."""
    check = _checks([_report_for(BATCHED, verdict="WA")])[6]
    assert check.status == verify.PASS


def test_check_6_is_skipped_with_a_reason_when_nothing_was_measured() -> None:
    check = _checks([_report_for("Batch #1\nTest case  1 --\n")])[6]
    assert check.status == verify.SKIP
    assert "nothing to calibrate" in check.detail


def test_all_six_checks_are_returned_in_order() -> None:
    checks = verify.run_checks([_report_for(AC_RUN)], _resolved(), None)
    assert [check.number for check in checks] == [1, 2, 3, 4, 5, 6]
    assert [check.name for check in checks] == [verify.CHECK_NAMES[n] for n in range(1, 7)]
    assert all(check.status in (verify.PASS, verify.FAIL, verify.SKIP) for check in checks)


def test_every_skip_carries_a_reason() -> None:
    """A skipped check that does not say why is the silent pass this ticket forbids."""
    checks = verify.run_checks([_report_for(AC_RUN)], _resolved(), None)
    assert checks[1].status == verify.SKIP
    for check in checks:
        if check.status == verify.SKIP:
            assert check.detail.strip()
            assert not check.problems


def test_a_skip_does_not_fail_the_run_and_a_failure_does() -> None:
    """Skipped is not failed; failed is."""
    skipped = verify.run_checks([_report_for(AC_RUN, role="model")], _resolved(), None)
    assert not any(check.failed for check in skipped)
    failed = verify.run_checks(
        [_report_for(AC_RUN, role="model", verdict="WA")], _resolved(), None
    )
    assert any(check.failed for check in failed)


def test_init_checker_reads_the_key_the_judge_reads(problem: Path) -> None:
    """The checker in force comes from ``init.yml``, the file DMOJ loads."""
    (problem / "init.yml").write_text(
        "archive: demo.zip\nchecker: checker.py\ntest_cases:\n"
        "- points: 100\n  batched:\n  - {in: cases/0.in, out: cases/0.out}\n",
        encoding="utf-8",
    )
    assert verify.init_checker(problem) == "checker.py"


def test_init_checker_is_none_without_the_key(problem: Path) -> None:
    (problem / "init.yml").write_text(
        "archive: demo.zip\ntest_cases:\n"
        "- points: 100\n  batched:\n  - {in: cases/0.in, out: cases/0.out}\n",
        encoding="utf-8",
    )
    assert verify.init_checker(problem) is None


def test_the_expected_vs_actual_recap_prints_even_when_no_check_failed(capsys) -> None:
    """A mismatch no check covers still fails the run, so its recap must print.

    An entry declaring ``verdict: AC`` with no ``role:`` is the case: no check
    claims it, every check skips, and the only explanation of the exit status is
    the recap.
    """
    report = _report_for(BATCHED, verdict="AC")
    checks = verify.run_checks([report], _resolved(), None)
    assert not any(check.failed for check in checks)
    verify._print_failures(checks, [report], 20)
    out = capsys.readouterr().out
    assert "expected vs actual:" in out
    assert "expected verdict AC" in out and "actual verdict WA" in out
    assert "failed checks:" not in out


def test_the_failed_checks_block_names_each_failing_check(capsys) -> None:
    """A broken model solution and a wrong-declared entry name checks 1 and 2."""
    model = _report_for(BATCHED, role="model", verdict="AC")
    wrong = _report_for(AC_RUN, verdict="WA")
    checks = verify.run_checks([model, wrong], _resolved(), None)
    verify._print_failures(checks, [model, wrong], 20)
    out = capsys.readouterr().out
    assert "failed checks:" in out
    assert "check 1 (model solution scores full marks)" in out
    assert "check 2 (intended-wrong submissions get their declared verdict)" in out

# ---------------------------------------------------------------------------
# The command
# ---------------------------------------------------------------------------


def test_verify_is_registered_with_the_cli() -> None:
    """The subcommand is dispatched by name, which is the registry's contract."""
    assert "verify" in commands.COMMANDS
    assert commands.COMMANDS["verify"].run is verify.run


def test_grading_hands_the_judge_the_resolved_limits_and_reads_back_the_report(
    problem: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The seam between the manifest and the judge: values out, transcript in."""
    write_manifest(
        problem,
        """\
        - source: solution.cpp
          verdict: WA
          score: 30
        """,
    )
    (entry,) = manifest_entries(problem)
    seen: dict[str, object] = {}

    def fake_submit(name, problem_id, executor, source, *, time_limit, memory_limit, **_):
        seen.update(
            name=name,
            problem_id=problem_id,
            executor=executor,
            source=source,
            time_limit=time_limit,
            memory_limit=memory_limit,
        )
        return judges.parse_grading(BATCHED, 0)

    monkeypatch.setattr(judges, "submit", fake_submit)
    plans = [verify.BatchPlan(1, 30.0), verify.BatchPlan(2, 70.0)]
    report = verify.grade_entry("judge-1", problem, entry, plans)

    assert seen == {
        "name": "judge-1",
        "problem_id": problem.name,
        "executor": "CPP17",
        "source": (problem / "solution.cpp").resolve(),
        # Seconds and KiB, exactly as `submit -tl`/`-ml` take them.
        "time_limit": 1.0,
        "memory_limit": 262144,
    }
    assert report.verdict == "WA"
    assert report.score == 30.0


def test_a_run_with_more_batches_than_init_yml_declares_is_refused(
    problem: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A rebuilt problem the judge has not re-discovered must say so, not mis-score."""
    write_manifest(problem, "- source: solution.cpp\n")
    (entry,) = manifest_entries(problem)
    monkeypatch.setattr(
        judges, "submit", lambda *a, **k: judges.parse_grading(BATCHED, 0)
    )
    with pytest.raises(VerifyError, match="judges update"):
        verify.grade_entry("judge-1", problem, entry, [verify.BatchPlan(1, 100.0)])

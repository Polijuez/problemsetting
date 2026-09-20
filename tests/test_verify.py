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


def _report(raw: str, *, compile_error: str | None = None) -> verify.Report:
    groups = judges.parse_batch_cases(raw)
    return verify.Report(
        entry=_entry(),
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

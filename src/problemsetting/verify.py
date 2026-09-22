"""``problemsetting verify``: grade a problem's declared submissions.

``submissions.yml`` is the problem's list of submissions *and the result each one
is expected to get* (decision Q23).  Convention is not enough: the old toolkit
assumed everything under ``submissions/`` should be Accepted, so a submission
that silently stopped being Accepted -- because the problem, the checker or the
limits changed -- went unnoticed.  Here every entry declares what it expects, and
``verify`` fails when reality disagrees.

The manifest lives next to ``meta.yml`` and looks like this::

    submissions:
      - source: solution.cpp        # required; relative to the problem directory
        verdict: AC                 # optional: the DMOJ verdict it must get
        score: 100                  # optional: points out of 100
        role: model                 # optional: why it exists (model, brute, ...)
        executor: CPP17             # optional: override the inferred executor

An entry with no ``verdict`` and no ``score`` is *informational*: it is graded and
reported, and cannot fail the run.

Reading the run is :mod:`problemsetting.judges`' job -- it owns the container pool
and the verdict parser (``judges.parse_cases``); this module adds only the
declaration and the comparison, so there is no second parser here.

Two facts about how DMOJ reports a run decide the shape of the report:

* **A batch is all-or-nothing.**  Every case inherits its batch's ``points:``
  (``dmoj/problem.py:355``), and the batch is worth them only when every case in
  it passed, so the score is computed per batch and printed per batch.  A total
  alone would hide which subtask broke.
* **Measurements are observations.**  The judge reports each case's time and
  memory, and they are printed so limits can be calibrated by hand -- the toolkit
  never writes a limit from them.

Checks, not just a report (decision Q6).  ``verify`` answers "is this problem
correct?" with six named checks, each printed with its own number and status, so
a failure says *which* check failed: the model solution scores full marks; the
submissions meant to fail get the verdict they declare; a correct-but-too-slow
submission gets ``TLE``; the brute force agrees with the model solution on the
declared cases; the checker rejects a deliberately malformed output; and the
judge's measurements are reported so limits can be calibrated by hand.

A check the problem does not let us run -- no ``role: brute`` entry, say -- is
printed as **skipped with the reason**, never as a pass.  A check that reports
success without having run is worse than no check at all, which is why every
check below names its subject in ``submissions.yml`` (the declared role or the
declared verdict) rather than assuming it.
"""

from __future__ import annotations

import argparse
import dataclasses
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import yaml

from . import cases as cases_mod
from . import judges
from . import meta as meta_mod
from .commands import Command, register
from .errors import VerifyError

MANIFEST_FILENAME = "submissions.yml"

SOURCE_KEY = "source"
VERDICT_KEY = "verdict"
SCORE_KEY = "score"
ROLE_KEY = "role"
EXECUTOR_KEY = "executor"

#: ``init.yml``'s key that puts a checker in force -- the file DMOJ reads
#: (``dmoj/problem.py:506``: ``self.config['checker'] or 'standard'``).
CHECKER_KEY = "checker"

#: Every key an entry accepts, in canonical order.
VALID_KEYS: tuple[str, ...] = (SOURCE_KEY, VERDICT_KEY, SCORE_KEY, ROLE_KEY, EXECUTOR_KEY)

#: DMOJ's verdict codes (``dmoj/result.py``), plus ``CE`` for a submission the
#: judge could not compile -- the judge reports that out of band, so it never
#: emits ``CE`` as a case verdict, but an author declares it.
VERDICTS: tuple[str, ...] = ("AC", "CE", "IE", "TLE", "MLE", "OLE", "RTE", "IR", "WA", "SC")

#: Worst-first, exactly ``Result.CODE_DISPLAY_ORDER``: a submission's verdict is
#: the first of these any of its cases got.  ``SC`` is deliberately absent -- a
#: skipped case is what a *failure* leaves behind, so it is reported only when
#: there is nothing else, never over a real verdict.
VERDICT_SEVERITY: tuple[str, ...] = ("IE", "TLE", "MLE", "OLE", "RTE", "IR", "WA")

#: ``judges`` reports a case skipped after an earlier failure as ``--``; DMOJ's
#: own name for that code is ``SC``.
_SKIPPED = "--"

#: What a batch -- or a whole run -- reports when the judge produced no case for
#: it.  Never ``AC``: the one thing `verify` must not do is call an ungraded
#: submission accepted, which is exactly what an entry declaring ``AC`` would be
#: told if this were spelled "AC".
NOT_RUN = "not run"

#: The score is a percentage of the problem's total points -- the site's unit --
#: compared at the precision it is printed with, so an expectation of ``33.33``
#: matches a third of the points.
_SCORE_DECIMALS = 2
_SCORE_TOLERANCE = 0.5 * 10**-_SCORE_DECIMALS


def count_verdicts(cases: Sequence[judges.CaseResult]) -> dict[str, int]:
    """Per-verdict case counts, with the judge's ``--`` named DMOJ's ``SC``."""
    counts: dict[str, int] = {}
    for case in cases:
        code = "SC" if case.verdict == _SKIPPED else case.verdict
        counts[code] = counts.get(code, 0) + 1
    return counts


def worst_verdict(counts: Mapping[str, int], *, clean: str) -> str:
    """The worst code in ``counts``, or ``clean`` when every case was accepted.

    ``VERDICT_SEVERITY`` is the order (DMOJ's own ``CODE_DISPLAY_ORDER``), and a
    skipped case is only ever the answer when nothing else is: it is what a
    *failure* leaves behind, so it must not mask the verdict that caused it.
    """
    codes = set(counts) - {"AC"}
    if not codes:
        return clean
    for code in VERDICT_SEVERITY:
        if code in codes:
            return code
    return "SC" if codes == {"SC"} else sorted(codes)[0]


# ---------------------------------------------------------------------------
# The manifest
# ---------------------------------------------------------------------------


@dataclasses.dataclass(frozen=True)
class Entry:
    """One declared submission, resolved against ``meta.yml``.

    ``executor`` is the DMOJ executor id the judge is asked to grade in, and
    ``limits_key`` is the ``meta.yml`` ``limits:`` extension the limits were read
    from.  Both are reported, because inferring the wrong language and reading
    the limits of a different language are the two mistakes that would otherwise
    look like a wrong verdict.
    """

    index: int
    source: Path
    path: Path
    executor: str
    limits: meta_mod.Limits
    limits_key: str
    verdict: str | None
    score: float | None
    role: str | None

    @property
    def declares_expectation(self) -> bool:
        return self.verdict is not None or self.score is not None


def _fail(path: Path, message: str) -> VerifyError:
    return VerifyError(f"{path}: {message}")


def _entry_name(index: int, raw: Mapping[str, Any]) -> str:
    """How an entry is named in an error: its index and its source, if it has one."""
    where = f"entry {index}"
    source = raw.get(SOURCE_KEY)
    return f"{where} [source: {source}]" if isinstance(source, str) else where


def load_manifest(problem_dir: Path, resolved: meta_mod.ResolvedMeta) -> list[Entry]:
    """Read ``<problem_dir>/submissions.yml`` and resolve every entry.

    Every failure here is an authoring error and raises :class:`VerifyError`
    naming the file and the entry, because the alternative -- a traceback, or an
    entry silently dropped -- is indistinguishable from a problem that is fine.
    """
    path = problem_dir / MANIFEST_FILENAME
    if not path.is_file():
        raise VerifyError(
            f"{path} not found -- `verify` grades the submissions a problem declares; "
            f"the model template ships one to start from"
        )
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as error:
        raise _fail(path, str(error)) from error
    try:
        document = yaml.safe_load(text)
    except yaml.YAMLError as error:
        raise _fail(path, f"not valid YAML: {error}") from error

    if document is None:
        raise _fail(path, "is empty; declare at least one entry under `submissions:`")
    if not isinstance(document, Mapping):
        raise _fail(path, "expected a mapping at the top level")
    if unknown := set(document) - {"submissions"}:
        raise _fail(
            path, f"unknown key {sorted(unknown)[0]!r}; the only top-level key is 'submissions:'"
        )
    raw_entries = document.get("submissions")
    if not isinstance(raw_entries, list) or not raw_entries:
        raise _fail(path, "`submissions:` must be a non-empty list of entries")

    return [
        _read_entry(path, problem_dir, resolved, index, raw)
        for index, raw in enumerate(raw_entries, start=1)
    ]


def _read_entry(
    path: Path,
    problem_dir: Path,
    resolved: meta_mod.ResolvedMeta,
    index: int,
    raw: Any,
) -> Entry:
    if not isinstance(raw, Mapping):
        raise _fail(path, f"entry {index} must be a mapping, got {raw!r}")

    where = _entry_name(index, raw)
    if unknown := set(raw) - set(VALID_KEYS):
        raise _fail(
            path,
            f"{where}: unknown key {sorted(unknown)[0]!r}; valid keys: {', '.join(VALID_KEYS)}",
        )
    if SOURCE_KEY not in raw:
        raise _fail(path, f"{where}: missing required key {SOURCE_KEY!r}")

    source = _string(path, where, raw, SOURCE_KEY)
    source_path = (problem_dir / source).resolve()
    if not source_path.is_file():
        raise _fail(
            path,
            f"{where}: source {source!r} not found (looked for {source_path}); paths are "
            f"relative to the problem directory {problem_dir}",
        )

    executor = _executor(path, where, raw, source_path)
    limits, limits_key = _limits(resolved, source_path, executor)
    return Entry(
        index=index,
        source=Path(source),
        path=source_path,
        executor=executor,
        limits=limits,
        limits_key=limits_key,
        verdict=_verdict(path, where, raw),
        score=_score(path, where, raw),
        role=_optional_string(path, where, raw, ROLE_KEY),
    )


def _string(path: Path, where: str, raw: Mapping[str, Any], key: str) -> str:
    value = raw.get(key)
    if not isinstance(value, str) or not value.strip():
        raise _fail(path, f"{where}: {key} must be a non-empty string, got {value!r}")
    return value


def _optional_string(path: Path, where: str, raw: Mapping[str, Any], key: str) -> str | None:
    return _string(path, where, raw, key) if key in raw else None


def _verdict(path: Path, where: str, raw: Mapping[str, Any]) -> str | None:
    if VERDICT_KEY not in raw:
        return None
    value = raw[VERDICT_KEY]
    if not isinstance(value, str) or value not in VERDICTS:
        raise _fail(
            path, f"{where}: {VERDICT_KEY} must be one of {', '.join(VERDICTS)}, got {value!r}"
        )
    return value


def _score(path: Path, where: str, raw: Mapping[str, Any]) -> float | None:
    if SCORE_KEY not in raw:
        return None
    value = raw[SCORE_KEY]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise _fail(path, f"{where}: {SCORE_KEY} must be a number, got {value!r}")
    if not 0 <= value <= 100:
        raise _fail(
            path,
            f"{where}: {SCORE_KEY} is a percentage of the problem's total points, so it must "
            f"be between 0 and 100, got {value!r}",
        )
    return float(value)


def _executor(path: Path, where: str, raw: Mapping[str, Any], source_path: Path) -> str:
    """The executor to grade in: the entry's override, or the source's extension."""
    if EXECUTOR_KEY in raw:
        value = _string(path, where, raw, EXECUTOR_KEY)
        if value not in meta_mod.EXECUTOR_FAMILY:
            raise _fail(
                path,
                f"{where}: {EXECUTOR_KEY} {value!r} is not a DMOJ executor this toolkit knows; "
                f"valid values: {', '.join(sorted(meta_mod.EXECUTOR_FAMILY))}",
            )
        return value
    try:
        return meta_mod.EXECUTOR_BY_EXT[source_path.suffix]
    except KeyError:
        raise _fail(
            path,
            f"{where}: cannot infer a language from {source_path.name!r}; the known extensions "
            f"are {', '.join(sorted(meta_mod.EXECUTOR_BY_EXT))} -- add an `{EXECUTOR_KEY}:` "
            f"override to grade it anyway",
        ) from None


def _limits(
    resolved: meta_mod.ResolvedMeta, source_path: Path, executor: str
) -> tuple[meta_mod.Limits, str]:
    """``meta.yml``'s limits for this language, and the key they were read from.

    ``meta.yml`` names languages by source *extension*, so the key is the
    submission's own extension when it agrees with the executor's language family
    (``PYPY3`` on a ``.py`` file is a ``.py`` problem), and the family's canonical
    extension otherwise.  A language ``limits:`` does not name falls back to
    :data:`meta.DEFAULT_LIMITS` -- 2 s and 262144 KiB, the judge's own defaults --
    because :func:`meta.resolve` fills the table in.
    """
    family = meta_mod.EXECUTOR_FAMILY[executor]
    extension = source_path.suffix
    if meta_mod.FAMILY_BY_EXT.get(extension) != family:
        extension = meta_mod.CANONICAL_EXT[family]
    return resolved.limits[extension], extension


# ---------------------------------------------------------------------------
# Scoring, from what the judge reported
# ---------------------------------------------------------------------------


@dataclasses.dataclass(frozen=True)
class BatchPlan:
    """One batch ``init.yml`` declares, and what it is worth."""

    number: int
    points: float


@dataclasses.dataclass(frozen=True)
class BatchScore:
    """One batch's share of a run.  The points a batch is worth are ``init.yml``'s.

    Two scoring regimes, and which one applies is decided by what the judge
    reported:

    * **All-or-nothing** (the default, and every standard batch): DMOJ gives a
      batch its points only when every case in it passed, and ``--`` (a case
      skipped after an earlier failure) does not pass.  This is not inferred
      from the case *points* because a passing standard batch reports each case
      at its own value, which sums to more than the batch is worth.
    * **Fractional** (a custom checker): the checker returns
      ``CheckerResult(True, 0.7 * point_value)``, so the judge reports a case
      whose points are a *fraction* of its total.  Here the batch earns the sum
      of what its cases were actually awarded -- ``dmoj/result.py`` carries
      ``points``, and ``judges`` now surfaces it.

    A batch counts as fractional only when some case was awarded strictly
    between zero and its total.  That keeps the two regimes from being confused
    in either direction: a standard batch whose cases each report their own
    value stays all-or-nothing, and a checker that happens to award a full
    point_value on every case is indistinguishable from -- and equivalent to --
    the all-or-nothing result.
    """

    number: int
    points: float
    cases: list[judges.CaseResult]

    @property
    def fractional(self) -> bool:
        """Whether the judge reported partial credit inside this batch."""
        return any(
            case.points is not None
            and case.total is not None
            and case.total > 0
            and 0.0 < case.points < case.total
            for case in self.cases
        )

    @property
    def earned(self) -> float:
        if self.fractional:
            # The judge reports each case as ``points`` out of ``total``, where
            # ``total`` is the BATCH's declared value, not a per-case slice:
            # measured on a checker awarding 0.7 * point_value in a 100-point
            # batch, all cases report points=70.0 total=100.0, and in a two-batch
            # problem the same checker reports 21.0/30 and 49.0/70.
            #
            # So the batch's share is the awarded ratio, which the site applies
            # as sum(points) / sum(totals) -- not a sum of raw points, which
            # would multiply a fraction by the case count.  Averaging the
            # per-case fractions agrees only while every case shares one total,
            # so the ratio is stated directly.
            awarded = sum(case.points or 0.0 for case in self.cases)
            possible = sum(case.total or 0.0 for case in self.cases)
            return self.points * awarded / possible if possible else 0.0
        return self.points if self.passed else 0.0

    @property
    def passed(self) -> bool:
        return bool(self.cases) and all(case.verdict == "AC" for case in self.cases)

    @property
    def counts(self) -> dict[str, int]:
        return count_verdicts(self.cases)

    @property
    def verdict(self) -> str:
        """The worst verdict among this batch's cases, or ``not run`` with none.

        A batch with no cases at all was never graded -- which is what a compile
        error leaves behind -- and says so rather than reporting a pass.
        """
        return worst_verdict(self.counts, clean="AC" if self.cases else NOT_RUN)


@dataclasses.dataclass(frozen=True)
class Report:
    """Everything one graded submission told us."""

    entry: Entry
    cases: list[judges.CaseResult]
    batches: list[BatchScore]
    compile_error: str | None

    @property
    def verdict(self) -> str:
        """The entry's headline verdict: the worst its cases got.

        A skipped case is only the headline when nothing else is: a submission
        expected to TLE reports ``TLE``, not ``SC``, even though the rest of its
        batch was skipped because of that TLE.

        A run that reported no case at all is ``not run``, never ``AC``: an entry
        declaring ``AC`` must not be told it passed something nothing graded.
        """
        if self.compile_error is not None:
            return "CE"
        return worst_verdict(self.counts, clean="AC" if self.cases else NOT_RUN)

    @property
    def counts(self) -> dict[str, int]:
        return count_verdicts(self.cases)

    @property
    def earned(self) -> float:
        return sum(batch.earned for batch in self.batches)

    @property
    def total(self) -> float:
        return sum(batch.points for batch in self.batches)

    @property
    def score(self) -> float:
        """Earned points as a percentage of the problem's total, the site's unit."""
        return 100.0 * self.earned / self.total if self.total else 0.0

    @property
    def source_name(self) -> str:
        """The submission's path as it is printed: relative, POSIX-separated."""
        return self.entry.source.as_posix()

    @property
    def slowest(self) -> float | None:
        times = [case.time for case in self.cases if case.time is not None]
        return max(times) if times else None

    @property
    def memory(self) -> int | None:
        memories = [case.memory for case in self.cases if case.memory is not None]
        return max(memories) if memories else None


def batch_plans(problem_dir: Path) -> list[BatchPlan]:
    """The batches ``init.yml`` makes the judge report, in order, with their points.

    Every batch comes out of ``init.yml``, which ``problemsetting cases`` writes
    from the generator's ``get_subtasks()``; the points are the subtask's own.
    A case outside any batch would be scored by its own ``points`` instead, which
    is a shape the toolkit never emits -- so it is refused here rather than
    silently scored as if it were a batch.
    """
    init_path = problem_dir / cases_mod.INIT_FILENAME
    document = cases_mod.load_init(problem_dir)
    test_cases = document.get("test_cases")
    if not isinstance(test_cases, list) or not test_cases:
        raise VerifyError(f"{init_path}: no test_cases -- run `problemsetting build` first")
    plans: list[BatchPlan] = []
    for number, entry in enumerate(test_cases, start=1):
        if not isinstance(entry, Mapping):
            raise VerifyError(f"{init_path}: test_cases entries must be mappings, got {entry!r}")
        if "batched" not in entry:
            raise VerifyError(
                f"{init_path}: test case {number} is not inside a batch; this toolkit emits "
                f"one `batched:` block per subtask, so a case outside one means the file was "
                f"hand-edited -- regenerate it with `problemsetting cases`"
            )
        plans.append(BatchPlan(number=number, points=_points(init_path, entry)))
    return plans


def _points(init_path: Path, entry: Mapping[str, Any]) -> float:
    """A batch's points, defaulting the way DMOJ does (``dmoj/problem.py:315``: 1)."""
    value = entry.get("points", 1)
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
        raise VerifyError(f"{init_path}: points must be a non-negative number, got {value!r}")
    return float(value)


def attribute(plans: Sequence[BatchPlan], groups: Sequence[Sequence[judges.CaseResult]]) -> list[BatchScore]:
    """Attribute the judge's ``Batch #k`` sections to the declared batches.

    Matched by position: DMOJ numbers batches in ``init.yml`` order and reports
    them in the same order, so the two lists are the same walk of the same file.
    A declared batch the judge reported nothing for keeps no cases, which is what
    a compile error leaves behind and what :attr:`BatchScore.passed` refuses.
    """
    return [
        BatchScore(
            number=plan.number,
            points=plan.points,
            cases=list(groups[index]) if index < len(groups) else [],
        )
        for index, plan in enumerate(plans)
    ]


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------


def _percent(value: float) -> str:
    return f"{round(value, _SCORE_DECIMALS):g}"


def mismatches(report: Report) -> list[tuple[str, str]]:
    """The declared expectations this run did not meet, as ``(expected, actual)``.

    An ungraded run (no case reported at all) fails *every* declared expectation,
    including ``score: 0``: :attr:`Report.score` is 0 in that state because there
    is nothing to score, and comparing that 0 against a declared 0 would let a
    submission the judge never graded pass its check.
    """
    entry = report.entry
    graded = bool(report.cases)
    found: list[tuple[str, str]] = []
    if entry.verdict is not None and entry.verdict != report.verdict:
        found.append((f"verdict {entry.verdict}", f"verdict {report.verdict}"))
    if entry.score is not None:
        if not graded:
            found.append((f"score {_percent(entry.score)}/100", f"score {NOT_RUN}"))
        elif abs(report.score - entry.score) > _SCORE_TOLERANCE:
            found.append(
                (
                    f"score {_percent(entry.score)}/100",
                    f"score {_percent(report.score)}/100",
                )
            )
    return found

# ---------------------------------------------------------------------------
# The six checks
# ---------------------------------------------------------------------------

#: The three roles that name a check's subject (decision Q23's ``role:`` field).
#: A check reads its subject from the manifest rather than guessing it, so what
#: each check asserts is visible and editable in ``submissions.yml``.
MODEL_ROLE = "model"
BRUTE_ROLE = "brute"
CHECKER_TEST_ROLE = "checker-test"

#: A check's three states.  ``SKIP`` is not a fourth kind of pass: it means the
#: problem gave the check nothing to run on, and it carries the reason.
PASS = "pass"
FAIL = "fail"
SKIP = "skip"

#: The checks' names, by number.  One table, so a name is not restated at every
#: site that reports a check.
CHECK_NAMES: dict[int, str] = {
    1: "model solution scores full marks",
    2: "intended-wrong submissions get their declared verdict",
    3: "a correct-but-too-slow submission gets TLE",
    4: "brute force agrees with the model solution on the declared cases",
    5: "the checker rejects a deliberately malformed output",
    6: "measurements are reported for calibration",
}


@dataclasses.dataclass(frozen=True)
class Check:
    """One of the six checks: whether it ran, and what it found.

    ``detail`` is the one-line answer -- what was checked and with what result --
    and ``problems`` lists the individual submissions that failed it, so a
    failure names the submission as well as the check.  ``skip`` never comes with
    empty ``detail``: a check that did not run must say why.
    """

    number: int
    name: str
    status: str
    detail: str
    problems: tuple[str, ...] = ()

    @property
    def failed(self) -> bool:
        return self.status == FAIL


def _check(number: int, status: str, detail: str, problems: Sequence[str] = ()) -> Check:
    return Check(number, CHECK_NAMES[number], status, detail, tuple(problems))


def _skipped(number: int, reason: str) -> Check:
    """A check the problem gave nothing to run on.  The reason is the whole point."""
    return _check(number, SKIP, reason)


def _source(report: Report) -> str:
    return report.source_name


def _sources(reports: Sequence[Report]) -> str:
    return ", ".join(report.source_name for report in reports)


def _ungraded(report: Report, consequence: str) -> str:
    """A submission the judge never graded, and the observation that leaves missing.

    "Never graded" is not a pass for any check that needs an observation: a
    compile error, or a transcript with no case line at all, says nothing about
    the submission, and a check that took it as agreement would be exactly the
    silent pass this command must not produce.
    """
    return f"{_source(report)}: never graded ({report.verdict}), so {consequence}"


def _verdict_line(report: Report) -> str:
    return f"{report.verdict}, {_percent(report.score)}/100"


def check_model_solution(reports: Sequence[Report]) -> Check:
    """Check 1: the model solution scores full marks.

    Full marks is not the same as ``AC``: DMOJ takes the verdict from
    ``CheckerResult.passed`` and the points from ``CheckerResult.points``
    (``dmoj/graders/standard.py:37-40``), so a scoring checker can pass a
    submission with a fraction of the points.  Both are asserted.
    """
    models = [report for report in reports if report.entry.role == MODEL_ROLE]
    if not models:
        return _skipped(
            1,
            "no submission declares `role: model`; declare the model solution so its "
            "full-marks score is checked",
        )
    problems = [
        f"{_source(report)}: expected AC and 100/100, got {_verdict_line(report)}"
        for report in models
        if not _full_marks(report)
    ]
    if problems:
        return _check(1, FAIL, f"{len(models)} model submission(s) graded", problems)
    return _check(1, PASS, ", ".join(f"{_source(r)}: {_verdict_line(r)}" for r in models))


def _full_marks(report: Report) -> bool:
    """Whether a run earned every point the problem declares.

    A run with no cases -- a compile error, or a submission the judge never
    graded -- is not full marks: nothing was earned.
    """
    return (
        bool(report.cases)
        and report.total > 0
        and abs(report.score - 100.0) <= _SCORE_TOLERANCE
    )


def check_declared_verdicts(reports: Sequence[Report]) -> Check:
    """Check 2: intended-wrong submissions get the verdict they declare.

    The headline check.  Its subjects are the entries that declare a failing
    verdict -- ``WA``, ``TLE``, ``MLE``, ``RTE``, ... -- and their *declared
    expectations* (verdict and score together) are what must hold, because a
    submission with the right verdict and the wrong score is still a problem
    whose scoring is not what the author declared.

    ``role: checker-test`` entries are check 5's subject, not this one, and are
    the only exclusion: everything else that declares failure is graded here.
    """
    subjects = [
        report
        for report in reports
        if report.entry.role != CHECKER_TEST_ROLE
        and report.entry.verdict is not None
        and report.entry.verdict != "AC"
    ]
    if not subjects:
        return _skipped(
            2,
            "no submission declares a failing verdict (WA, TLE, MLE, ...); nothing here "
            "proves the problem rejects a wrong answer",
        )
    problems = [
        f"{_source(report)}: expected {expected}, got {actual}"
        for report in subjects
        for expected, actual in mismatches(report)
    ]
    if problems:
        return _check(2, FAIL, f"{len(subjects)} failing submission(s) declared", problems)
    return _check(
        2, PASS, f"{len(subjects)} submission(s) got their declared result: {_sources(subjects)}"
    )


def check_time_limit(reports: Sequence[Report]) -> Check:
    """Check 3: a correct-but-too-slow submission gets ``TLE``.

    Separate from check 2 because "wrong answer" and "too slow" fail for
    different reasons and a problem can be broken in either dimension alone: a
    limit that is far too generous is invisible to every other check.

    A ``TLE`` alone is not enough.  A submission that is *wrong and slow* also
    times out, and would prove nothing about the limit, so a pass here also
    requires that no case was rejected for a reason other than time -- the AC
    cases are the evidence the submission was otherwise correct.

    Note that time is not the only thing that fails a case: ``judges.submit``
    grades with ``short_circuit=False`` (``dmoj/commands/submit.py``), so a
    ``TLE`` does not stop the remaining cases the way a ``WA`` does.  The claim
    is therefore "no wrong answer was observed", not "everything before the
    timeout was correct".
    """
    subjects = [report for report in reports if report.entry.verdict == "TLE"]
    if not subjects:
        return _skipped(
            3,
            "no submission declares `verdict: TLE`; without a correct-but-too-slow "
            "submission nothing proves the time limit is tight",
        )
    problems = []
    accepted = []
    for report in subjects:
        if report.verdict != "TLE":
            problems.append(
                f"{_source(report)}: expected TLE at tl={report.entry.limits.time:g}s, "
                f"got {_verdict_line(report)}"
            )
            continue
        # A TLE alone does not say the submission was *correct* and slow: one that
        # is wrong as well can time out too, and it would prove nothing about the
        # limit.  Any verdict other than AC/TLE/SC on any case means the
        # submission was rejected for something other than time, so it is not the
        # correct-but-slow reference this check needs.
        wrong = sorted(code for code in report.counts if code not in ("AC", "TLE", "SC"))
        if wrong:
            problems.append(
                f"{_source(report)}: TLE, but it also got {', '.join(wrong)} -- a "
                f"wrong-and-slow submission does not prove the limit is tight"
            )
        else:
            graded = report.counts.get("AC", 0)
            accepted.append(
                f"{_source(report)}: TLE at tl={report.entry.limits.time:g}s"
                + (
                    f", AC on {graded} case(s) and no wrong answer, so it is correct as far "
                    f"as the judge observed"
                    if graded
                    else ", with no case completed, so its correctness rests on its "
                    "declaration"
                )
            )
    if problems:
        return _check(3, FAIL, f"{len(subjects)} submission(s) declared TLE", problems)
    return _check(3, PASS, ", ".join(accepted))


def check_brute_force(reports: Sequence[Report]) -> Check:
    """Check 4: the brute force agrees with the model solution on the declared cases.

    The expected outputs are the model solution's (``problemsetting outputs``
    runs it over the generated cases), so a brute force that is accepted on every
    declared case has, by construction, produced the model solution's answer
    there -- any disagreement shows up as a rejection.  That is why this check is
    a *declared-case* comparison and not a random one: fresh random cases are
    ``problemsetting stress``'s job (ticket 07).
    """
    brutes = [report for report in reports if report.entry.role == BRUTE_ROLE]
    if not brutes:
        return _skipped(
            4,
            "no submission declares `role: brute`; declare the reference brute force so it "
            "can be cross-checked against the model solution on the declared cases",
        )
    problems = []
    for report in brutes:
        if not report.cases:
            problems.append(
                _ungraded(report, "agreement with the model solution was not observed")
            )
        elif report.verdict != "AC":
            rejected = ", ".join(sorted(code for code in report.counts if code != "AC"))
            problems.append(
                f"{_source(report)}: {report.verdict} on the declared cases ({rejected}); the "
                f"expected outputs are the model solution's, so a rejection is a disagreement"
            )
    if problems:
        return _check(4, FAIL, f"{len(brutes)} brute force submission(s) declared", problems)
    return _check(
        4,
        PASS,
        ", ".join(
            f"{_source(report)}: AC on all {len(report.cases)} declared case(s), matching "
            f"the model solution"
            for report in brutes
        ),
    )


def init_checker(problem_dir: Path) -> str | None:
    """The ``checker:`` file the judge will load, or None when there is none.

    Read from the generated ``init.yml``, not from ``meta.yml``'s checker axis,
    because that is what DMOJ reads: ``dmoj/problem.py:506`` takes
    ``self.config['checker'] or 'standard'``.  A ``meta.yml`` whose checker axis
    is ``custom`` while ``init.yml`` predates it has **no checker in force**, and
    a check that trusted the axis would call the standard comparison's verdict a
    checker rejection.
    """
    value = cases_mod.load_init(problem_dir).get(CHECKER_KEY)
    return value if isinstance(value, str) and value else None


def check_checker_rejects(
    reports: Sequence[Report], resolved: meta_mod.ResolvedMeta, checker: str | None
) -> Check:
    """Check 5: the checker rejects a deliberately malformed output.

    The malformed output is declared as ``role: checker-test``, never hardcoded,
    so what the checker must reject is visible and editable like every other
    expectation.

    ``checker`` is the checker ``init.yml`` puts in force -- see
    :func:`init_checker`.  With none, the standard comparison grades the entry
    instead and its verdict proves nothing about a checker, so the check skips
    and says why; that includes the case where ``meta.yml`` asks for a checker
    the ``init.yml`` in front of the judge does not have, which is a build the
    author must regenerate rather than a pass.

    A rejection is only a rejection when the checker actually decided: DMOJ
    folds its verdict in as ``[WA, AC][check.passed]`` and **skips running it**
    for a submission that already failed on its own
    (``dmoj/graders/standard.py:39, 53-56`` -- checkers may be very expensive).
    So a rejection is exactly ``WA``; an ``RTE``/``MLE``/``OLE`` means the
    malformed output crashed or was killed and the checker never saw it, and a
    submission that was never graded observed nothing at all.
    """
    subjects = _checker_tests(reports)
    declared = f" (declared anyway: {_sources(subjects)})" if subjects else ""
    if checker is None:
        if resolved.uses_checker:
            return _skipped(
                5,
                f"meta.yml declares checker: custom, but init.yml declares no `checker:`, so the "
                f"judge is running the standard comparison and nothing here tests a checker. "
                f"Regenerate init.yml with `problemsetting cases`{declared}",
            )
        return _skipped(
            5,
            f"model {resolved.model!r} has no checker (`checker: none`), so there is no "
            f"checker for a malformed output to be rejected by{declared}",
        )
    if not subjects:
        return _skipped(
            5,
            f"{checker} is in force, but no submission declares `role: checker-test`; declare "
            f"the deliberately malformed output the checker must reject",
        )
    problems = []
    for report in subjects:
        if not report.cases:
            problems.append(_ungraded(report, "no rejection was observed"))
        elif report.verdict == "AC":
            problems.append(
                f"{_source(report)}: AC -- {checker} accepted a deliberately malformed output"
            )
        elif report.verdict != "WA":
            problems.append(
                f"{_source(report)}: {report.verdict} -- {checker} never ran (DMOJ skips it for "
                f"a submission that failed on its own), so no rejection was observed"
            )
    if problems:
        return _check(5, FAIL, f"{len(subjects)} checker-test submission(s) declared", problems)
    return _check(
        5,
        PASS,
        ", ".join(
            f"{_source(report)}: WA, which is {checker} rejecting it" for report in subjects
        ),
    )


def _checker_tests(reports: Sequence[Report]) -> list[Report]:
    return [report for report in reports if report.entry.role == CHECKER_TEST_ROLE]


def check_measurements(reports: Sequence[Report], resolved: meta_mod.ResolvedMeta) -> Check:
    """Check 6: the judge's measurements are reported so limits can be calibrated.

    **Reporting only.**  The measured time and memory are never written back as a
    limit -- calibrating is a human decision about the problem statement, and a
    toolkit that silently set a limit from one run would bake in the machine's
    speed.  The limits actually in force are printed beside so the observations
    can be read against them.
    """
    measured = [
        report
        for report in reports
        if report.cases and (report.slowest is not None or report.memory is not None)
    ]
    if not measured:
        return _skipped(
            6,
            "no graded case reported a time or memory measurement; there is nothing to "
            "calibrate a limit from",
        )
    slowest = max(report.slowest for report in measured if report.slowest is not None)
    memories = [report.memory for report in measured if report.memory is not None]
    keys = sorted({report.entry.limits_key for report in measured})
    in_force = ", ".join(
        f"{key} tl={resolved.limits[key].time:g}s ml={resolved.limits[key].memory}KiB"
        for key in keys
    )
    return _check(
        6,
        PASS,
        f"slowest case {slowest:.3f}s, peak {max(memories) if memories else 0} KiB over "
        f"{len(measured)} submission(s); limits in force: {in_force} (reported only, "
        f"never set from these)",
    )


def run_checks(
    reports: Sequence[Report],
    resolved: meta_mod.ResolvedMeta,
    checker: str | None,
) -> list[Check]:
    """All six checks, in order, over the runs that were graded.

    ``checker`` is ``init.yml``'s ``checker:`` (see :func:`init_checker`), not
    ``resolved.uses_checker``: check 5 has to ask the judge's own source of
    truth, or a ``meta.yml`` whose checker axis is newer than the built
    ``init.yml`` would be read as a checker that is not in force.
    """
    return [
        check_model_solution(reports),
        check_declared_verdicts(reports),
        check_time_limit(reports),
        check_brute_force(reports),
        check_checker_rejects(reports, resolved, checker),
        check_measurements(reports, resolved),
    ]


def _print_batches(report: Report) -> None:
    for batch in report.batches:
        counts = ", ".join(f"{code} {n}" for code, n in sorted(batch.counts.items()))
        detail = f"  ({counts})" if counts else ""
        print(
            f"      batch {batch.number}  {batch.earned:g}/{batch.points:g} pts  "
            f"{batch.verdict}{detail}"
        )


def _print_entry(report: Report, width: int, index: int) -> None:
    entry = report.entry
    role = entry.role or "-"
    print(
        f"  {index}. {entry.source.as_posix():<{width}}  {role:<8}  {entry.executor:<6}  "
        f"{report.verdict:<3}  score {_percent(report.score)}/100 "
        f"({report.earned:g}/{report.total:g} pts, tl={entry.limits.time:g}s "
        f"ml={entry.limits.memory}KiB from limits[{entry.limits_key}])"
    )
    if report.compile_error is not None:
        first = report.compile_error.splitlines()[0] if report.compile_error else "compile error"
        print(f"      compile error: {first}")
    _print_batches(report)
    measurements = []
    if report.slowest is not None:
        measurements.append(f"slowest case {report.slowest:.3f}s")
    if report.memory is not None:
        measurements.append(f"max {report.memory} KiB")
    if measurements:
        # Observation only: reported so a limit can be calibrated by hand, and
        # never fed back as one.
        print(f"      measured  {', '.join(measurements)}")


# ---------------------------------------------------------------------------
# The command
# ---------------------------------------------------------------------------

HELP = "grade the submissions declared in submissions.yml and check their expectations"


def add_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("problem", help="problem directory to verify")


def run(args: argparse.Namespace) -> int:
    return run_verify(args.problem)


def grade_entry(
    name: str,
    problem_dir: Path,
    entry: Entry,
    plans: Sequence[BatchPlan],
    *,
    problems_root: Path | None = None,
) -> Report:
    """Grade one declared submission through the pool and read the run.

    ``problems_root`` is the host directory mounted at ``/problems`` -- the
    problemset repo's ``problems/`` when the problem lives in one.  It is threaded
    through because the source path is expressed relative to *that* mount, and
    mapping against the toolkit checkout instead would silently grade a
    different file (or refuse a problem that is perfectly gradeable).
    """
    grading = judges.submit(
        name,
        problem_dir.name,
        entry.executor,
        entry.path,
        time_limit=entry.limits.time,
        memory_limit=entry.limits.memory,
        problems_root=problems_root,
    )
    # A run that produced no result is not a result.  Raising here keeps an
    # infrastructure failure (a timed-out command, a dead container, a rejected
    # invocation) from being reported as a submission verdict -- previously a
    # non-zero status with no verdicts was classified as a compile error, which
    # meant a declared `verdict: CE` could be *satisfied* by a run that never
    # compiled anything.
    if grading.run_error is not None:
        raise VerifyError(
            f"{problem_dir.name}: grading {entry.source} produced no verdict: "
            f"{grading.run_error.splitlines()[0] if grading.run_error else 'no output'}"
        )
    groups = judges.parse_batch_cases(grading.raw)
    if groups and len(groups) != len(plans):
        raise VerifyError(
            f"{problem_dir.name}: {entry.source} was graded with {len(groups)} batch(es) but "
            f"init.yml declares {len(plans)}; the problem was rebuilt after the judge's last "
            f"discovery -- run 'problemsetting judges update'"
        )
    return Report(
        entry=entry,
        cases=judges.parse_cases(grading.raw),
        batches=attribute(plans, groups),
        compile_error=grading.compile_error,
    )


def run_verify(problem: str) -> int:
    problem_dir = judges.resolve_problem(problem)
    problems_root = judges.problems_root()
    _, resolved = meta_mod.load(problem_dir)
    entries = load_manifest(problem_dir, resolved)
    plans = batch_plans(problem_dir)

    name = _running_container(problems_root)
    # Decision Q28: a problem rebuilt after the judge booted is re-discovered
    # rather than needing the container restarted.
    judges.update_problems(name)

    print(f"==> verify {problem_dir.name}  (model {resolved.model}, judge {name})")
    width = max(len(entry.source.as_posix()) for entry in entries)
    mismatched: list[Report] = []
    reports: list[Report] = []
    for entry in entries:
        report = grade_entry(name, problem_dir, entry, plans, problems_root=problems_root)
        reports.append(report)
        _print_entry(report, width, entry.index)
        if not entry.declares_expectation:
            print("      no expectation declared: reported for information only")
            continue
        if found := mismatches(report):
            mismatched.append(report)
            print("      FAIL")
            for expected, actual in found:
                print(f"        expected {expected}")
                print(f"        actual   {actual}")

    declared = sum(1 for entry in entries if entry.declares_expectation)
    print(
        f"verify: {len(entries)} submission(s), {declared} with expectations, "
        f"{len(mismatched)} mismatch(es)"
    )
    checks = run_checks(reports, resolved, init_checker(problem_dir))
    _print_checks(checks)
    _print_failures(checks, mismatched, width)
    if mismatched or any(check.failed for check in checks):
        return 1
    return 0


def _print_checks(checks: Sequence[Check]) -> None:
    """One line per check, each named and numbered, so a failure is attributable."""
    print("checks:")
    for check in checks:
        print(f"  {check.number}. {check.name:<58}  {check.status.upper()}")
        print(f"       {check.detail}")
        for problem in check.problems:
            print(f"       - {problem}")


def _print_failures(checks: Sequence[Check], mismatched: Sequence[Report], width: int) -> None:
    """What failed: each check by name, then the entries whose expectation missed.

    The two blocks are independent.  A mismatch that no check covers -- an entry
    declaring ``verdict: AC`` with no ``role:`` makes every check skip -- still
    fails the run, so its recap prints whether or not a check failed.
    """
    if failed := [check for check in checks if check.failed]:
        print("failed checks:")
        for check in failed:
            print(f"  check {check.number} ({check.name})")
            for problem in check.problems:
                print(f"    {problem}")
    if mismatched:
        print("expected vs actual:")
        for report in mismatched:
            entry = report.entry
            expected = ", ".join(
                part
                for part in (
                    f"verdict {entry.verdict}" if entry.verdict else "",
                    f"score {_percent(entry.score)}/100" if entry.score is not None else "",
                )
                if part
            )
            actual = f"verdict {report.verdict}, score {_percent(report.score)}/100"
            print(f"  {report.source_name:<{width}}  expected {expected}  |  actual {actual}")


def _running_container(problems_root: Path | None = None) -> str:
    """A running pool container, starting one if the pool is empty.

    ``verify`` is the command that answers "is this problem correct?", so needing
    a second command first would defeat it.  This is the same pool
    ``problemsetting judges`` manages, and it is reused when it is already up.

    A pool started here mounts ``problems_root`` at ``/problems`` -- the
    problemset repo's own ``problems/`` when verify runs inside one, so the
    problem being graded is the one the judge can actually see.
    """
    if running := judges.running_containers():
        return running[0]
    print("no judge container is running; starting one (discovery takes a minute)")
    _, names, _ = judges.ensure_pool(1, problems_root=problems_root)
    name = names[0]
    if not judges.wait_ready(name):
        raise VerifyError(
            f"the judge container {name} never finished discovery; check it with "
            f"'podman logs {name}'"
        )
    return name


register(Command(name="verify", help=HELP, add_arguments=add_arguments, run=run))

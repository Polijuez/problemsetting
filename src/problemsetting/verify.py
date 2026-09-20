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

    ``earned`` is derived rather than stored so that "this batch paid" is stated
    once, in :attr:`passed`: DMOJ gives a batch its points only when every case in
    it passed, and ``--`` (a case skipped after an earlier failure) does not pass.
    """

    number: int
    points: float
    cases: list[judges.CaseResult]

    @property
    def earned(self) -> float:
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


def grade_entry(name: str, problem_dir: Path, entry: Entry, plans: Sequence[BatchPlan]) -> Report:
    """Grade one declared submission through the pool and read the run."""
    grading = judges.submit(
        name,
        problem_dir.name,
        entry.executor,
        entry.path,
        time_limit=entry.limits.time,
        memory_limit=entry.limits.memory,
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
    problem_dir = Path.cwd() / problem
    _, resolved = meta_mod.load(problem_dir)
    entries = load_manifest(problem_dir, resolved)
    plans = batch_plans(problem_dir)

    name = _running_container()
    # Decision Q28: a problem rebuilt after the judge booted is re-discovered
    # rather than needing the container restarted.
    judges.update_problems(name)

    print(f"==> verify {problem_dir.name}  (model {resolved.model}, judge {name})")
    width = max(len(entry.source.as_posix()) for entry in entries)
    mismatched: list[Report] = []
    for entry in entries:
        report = grade_entry(name, problem_dir, entry, plans)
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
            print(f"  {entry.source.as_posix():<{width}}  expected {expected}  |  actual {actual}")
        return 1
    return 0


def _running_container() -> str:
    """A running pool container, starting one if the pool is empty.

    ``verify`` is the command that answers "is this problem correct?", so needing
    a second command first would defeat it.  This is the same pool
    ``problemsetting judges`` manages, and it is reused when it is already up.
    """
    if running := judges.running_containers():
        return running[0]
    print("no judge container is running; starting one (discovery takes a minute)")
    _, names, _ = judges.ensure_pool(1)
    name = names[0]
    if not judges.wait_ready(name):
        raise VerifyError(
            f"the judge container {name} never finished discovery; check it with "
            f"'podman logs {name}'"
        )
    return name


register(Command(name="verify", help=HELP, add_arguments=add_arguments, run=run))

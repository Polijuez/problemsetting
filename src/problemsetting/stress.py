"""``stress``: hunt for a tiny input where the model solution and the brute force disagree.

The expected outputs of every case are the model solution's answers, so a model
solution that is wrong is the one defect nothing else in the toolkit catches: the
judge grades every submission against a wrong yardstick, and the brute force
declared in ``submissions.yml`` (``role: brute``) is the only other statement of
what the answer is.  ``verify``'s check 4 cross-checks the two on the *declared*
cases -- the ones the model solution itself produced, so they agree by
construction.  This module cross-checks them on cases nobody designed:
``Generator.gen_small(rand)``'s tiny random inputs, where a slow brute force is
still an honest reference.

**Both programs run in the judge, and the judge decides.**  Decision Q17 puts
stress testing through the container rather than an in-process sandbox, so the
comparison here is DMOJ's own ``standard`` checker, applied by a scratch problem
whose expected outputs are the model solution's answers.  Nothing is
re-implemented: a disagreement is a ``WA`` the judge reported.

That takes **two passes**, because DMOJ's CLI has no way to hand a submission's
stdout back -- ``submit`` reports verdicts and measurements only.  Pass A submits
the *model solution* to a scratch problem whose checker accepts anything and
echoes the submission's output into its *feedback* (``dmoj/judge.py:_ipc_result``
prints a checker's feedback, so the transcript carries it); the toolkit reads the
answers out of that transcript and writes them as the scratch problem's expected
outputs.  Pass B submits the *brute force* against those expected outputs, with a
checker that applies DMOJ's ``standard`` comparison and echoes both outputs when
they differ.  Both runs are the judge's, the comparison is the judge's, and a
disagreement arrives with both answers attached.

**Where the scratch problems live.**  The pool mounts the *problems root* at
``/problems`` -- the problemset repo's ``problems/`` when stress runs inside one,
and the toolkit checkout only when the toolkit is itself the problems root -- and
DMOJ discovers a problem as ``<root>/<id>/init.yml`` where ``<root>`` is two
directories above each matched ``init.yml``.  A scratch problem therefore has to
be a *direct child of the problems root*, not something under the problem being
stressed.  It must also never be a dot-directory: ``glob``'s recursive walk skips
hidden directories, and a problem the judge cannot see fails every submission
with ``unknown problem``.  The scratch directories are therefore
``stress-<problem>-<pass><chunk>`` at the problems root, created before the first
submission and removed in a ``finally``, and the pool is asked to re-discover
them (``POST /update/problems``, decision Q28) since discovery happens once, at
container start.

**Parallelism is the pool's.**  The cases are split into one chunk per judge
container and each chunk gets its own scratch problem, so a run of thousands of
cases is one submission per container per pass rather than thousands of round
trips.  One chunk per container is the whole parallelism: the pool's launcher
reads its command FIFO in a single loop, so a second submission to one container
would queue behind the first rather than overlap with it.

The cost driver the ticket names is container round-trips, and this is what bounds
them: a run's round trips are **two per container** regardless of ``--cases``, and
only the size of one submission's case list grows with the count.  Measured on
this machine against the shipped ``standard`` template: ~13 s wall at
``--cases 300`` and ~39 s at ``--cases 1000`` on one container, most of it the
judge's own process launches rather than the comparison, which is why the default
is 200.

**A run must be reproducible.**  Every run reports the seed it used, and
``--seed`` fixes it: the same seed means the same ``gen_small`` calls in the same
order, hence the same cases.  A counterexample that cannot be reproduced is not
actionable, so the failing input and the command that regenerates it are printed
with it, and a clean run reports how many cases it compared -- "no counterexample
found" must not be confusable with "nothing ran".
"""

from __future__ import annotations

import argparse
import base64
import binascii
import dataclasses
import random
import re
import shutil
from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from . import cases as cases_mod
from . import judges
from . import meta as meta_mod
from . import verify
from .commands import Command, register
from .errors import CaseError, JudgeError, OutputError

#: How many tiny cases are generated and compared when ``--cases`` is not given.
#: Enough to be a real fuzz run over a tiny input space, few enough that the whole
#: thing is a couple of seconds of judging per container.
DEFAULT_CASES = 200

#: The scratch problem's layout.  The two names come from :mod:`cases` rather than
#: being spelled again here: a scratch problem is a problem the judge reads through
#: the same discovery path, and a second copy of the layout would drift into
#: scratch ``init.yml`` files naming files that do not exist.
CASES_DIRNAME = cases_mod.CASES_DIRNAME
INIT_FILENAME = cases_mod.INIT_FILENAME

#: Prefix of every scratch problem directory.  They live at the problems root,
#: which is the one place the pool's mount makes discoverable, so the name is
#: there to be unmistakable in that listing.
SCRATCH_PREFIX = "stress-"

#: The two scratch checkers, one per pass.  A checker is named by its problem's
#: ``init.yml``, so each pass gets its own problem rather than the two sharing a
#: file the judge has already read.
ECHO_CHECKER = "echo.py"
DIFF_CHECKER = "diff.py"

#: Grammar of a checker's feedback.  Each shape is written **once**, as a format
#: string: the generated checkers interpolate it, and the regex that reads it back
#: is derived from it by :func:`_pattern`.  A second hand-maintained regex is what
#: would let a checker and its reader drift apart -- the checkers would emit one
#: grammar and the toolkit would look for another, and the run would report "no
#: answer" instead of the real cause.
#:
#: The case number is carried because DMOJ hands the checker ``case_position`` and
#: a flat case list makes it the case's own number.  It is **0-based**
#: (``dmoj/problem.py:_resolve_testcases`` numbers cases with a counter starting at
#: zero) while the transcript's ``Test case N`` is 1-based, so the checkers emit
#: ``case_position + 1`` and both sides then name a case the same way.
OUT_FEEDBACK = "stress-out:%d:%s"
DIFF_FEEDBACK = "stress-diff:%d:model=%s:brute=%s"

#: The two placeholder kinds a feedback format may use -- an integer, and a base64
#: blob -- and what each matches in a transcript.  ``%s`` is deliberately the
#: base64 alphabet rather than ``.*``: the value is decoded, so the pattern has to
#: be the set of characters that can decode.
_PLACEHOLDER_GROUPS = {"d": r"(\d+)", "s": r"([A-Za-z0-9+/=]*)"}


def _pattern(format_string: str) -> re.Pattern[str]:
    """A regex matching ``format_string``'s output, with one group per placeholder."""
    head, *rest = format_string.split("%")
    parts = [re.escape(head)]
    for piece in rest:
        parts.append(_PLACEHOLDER_GROUPS[piece[0]])
        parts.append(re.escape(piece[1:]))
    return re.compile("".join(parts))


_OUT_RE = _pattern(OUT_FEEDBACK)
_DIFF_RE = _pattern(DIFF_FEEDBACK)

#: Points every scratch case is worth.  Non-zero on purpose: DMOJ turns on
#: short-circuiting for the rest of a run after a *failed 0-point case*
#: (``dmoj/judge.py:_grade_cases``), which would skip exactly the cases a run is
#: looking at.
CASE_POINTS = 1

_SCRATCH_HEADER = (
    "# Generated by `problemsetting stress` -- a scratch problem for one stress run.\n"
    "# It is deleted when the run ends; nothing in it is meant to be edited or kept.\n"
)

ECHO_CHECKER_SOURCE = f'''\
"""Scratch checker: accept whatever the submission printed, and echo it back.

`problemsetting stress`'s first pass uses this to read the model solution's
answer for each tiny case, because DMOJ's `submit` command reports verdicts and
measurements but never a submission's stdout -- while a checker's feedback *is*
printed (`dmoj/judge.py:_ipc_result`).
"""

import base64

from dmoj.result import CheckerResult

FEEDBACK = {OUT_FEEDBACK!r}


def check(process_output, judge_output, point_value=1, case_position=None, **kwargs):
    # A `CheckerResult` rather than `True`, because `True` would become a result
    # with no feedback at all (`dmoj/graders/standard.py:37-40`).
    return CheckerResult(
        True,
        point_value,
        feedback=FEEDBACK % (case_position + 1, base64.b64encode(process_output).decode()),
    )
'''

DIFF_CHECKER_SOURCE = f'''\
"""Scratch checker: DMOJ's own comparison, with both outputs echoed on failure.

This is the stress test.  `dmoj.checkers.standard` is the checker a plain
problem's cases are compared with, so an input on which the two programs' outputs
differ is reported as the `WA` the judge would give that submission.
"""

import base64

from dmoj.checkers.standard import check as standard_check
from dmoj.result import CheckerResult

FEEDBACK = {DIFF_FEEDBACK!r}


def check(process_output, judge_output, point_value=1, case_position=None, **kwargs):
    if standard_check(process_output, judge_output):
        return True
    return CheckerResult(
        False,
        0,
        feedback=FEEDBACK
        % (
            case_position + 1,
            base64.b64encode(judge_output).decode(),
            base64.b64encode(process_output).decode(),
        ),
    )
'''


# ---------------------------------------------------------------------------
# Reading the judge's transcript
# ---------------------------------------------------------------------------


@dataclasses.dataclass(frozen=True)
class Observed:
    """One ``Test case`` line: its verdict, and what its checker echoed for it.

    The position is the caller's dictionary key, not a field: the two must be the
    same number, and one of them being authoritative is what keeps that true.
    """

    verdict: str
    payload: Any


def _decode(text: str) -> bytes | None:
    try:
        return base64.b64decode(text, validate=True)
    except (binascii.Error, ValueError):
        return None


def _transcript(
    raw: str, pattern: re.Pattern[str], payload: Callable[[re.Match[str]], Any]
) -> dict[int, Observed]:
    """The cases a transcript reports, keyed by case position.

    The verdict comes from :func:`judges.parse_cases` -- the toolkit's one reader
    of ``Test case`` lines, ANSI stripping included -- and the payload from this
    run's own checker feedback, paired by the position *the judge* put in it.  A
    case the feedback does not name has no payload, which for pass A means the
    checker never ran: the model solution was killed on that case.
    """
    echoed = {int(match.group(1)): payload(match) for match in pattern.finditer(raw)}
    return {
        case.number: Observed(case.verdict, echoed.get(case.number))
        for case in judges.parse_cases(raw)
    }


def echoed_outputs(raw: str) -> dict[int, Observed]:
    """Pass A's transcript: per case, the bytes the submission printed."""
    return _transcript(raw, _OUT_RE, lambda match: _decode(match.group(2)))


def compared_outputs(raw: str) -> dict[int, Observed]:
    """Pass B's transcript: per rejected case, the model's and the brute's answers."""
    return _transcript(
        raw,
        _DIFF_RE,
        lambda match: (_decode(match.group(2)), _decode(match.group(3))),
    )


def render(case: Any, index: int, source: str) -> str:
    """One tiny case's input text, through ``cases``' own renderer.

    A stress run has to feed the programs exactly the bytes a real case would, so
    this is deliberately the same call ``cases`` makes for the declared cases --
    reimplementing it here is how the two would drift apart.
    """
    return cases_mod._render_input(case, index, source)


def small_cases(generator: Any, seed: int, count: int, source: str) -> list[str]:
    """``count`` tiny inputs from ``Generator.gen_small(rand)``, as input text.

    The hook is called with this module's own ``random.Random(seed)``, in a fixed
    order, so a seed determines the cases exactly -- that is what makes ``--seed``
    reproduce a failure.  A hook may return several cases per call (a problem
    whose small inputs come in pairs has one natural way to write it), so its
    results are accumulated until ``count`` is reached.
    """
    rand = random.Random(seed)
    hook = generator.gen_small
    texts: list[str] = []
    while len(texts) < count:
        try:
            produced = hook(rand)
        except Exception as error:  # author code: report it without the traceback
            raise CaseError(f"{source}: gen_small() failed: {error}") from error
        cases_mod.require_sequence(produced, source, "gen_small() must return a list of cases")
        if not produced:
            raise CaseError(
                f"{source}: gen_small() returned no cases; a stress run with nothing to "
                f"compare would report success without having tested anything"
            )
        for case in produced:
            if not callable(getattr(case, "write_file", None)):
                raise CaseError(
                    f"{source}: a case from gen_small() ({type(case).__name__}) has no "
                    f"write_file() method; it needs the same two methods as every other case"
                )
            texts.append(render(case, len(texts), source))
            if len(texts) == count:
                break
    return texts


def split(items: Sequence[str], parts: int) -> list[list[str]]:
    """``items`` in ``parts`` contiguous chunks, as evenly as they divide.

    Contiguous rather than round-robin so a chunk is a range of case numbers: the
    index a counterexample is reported for then names both the input and where
    ``--seed`` regenerates it.
    """
    size, remainder = divmod(len(items), parts)
    chunks, start = [], 0
    for index in range(parts):
        length = size + (1 if index < remainder else 0)
        chunks.append(list(items[start : start + length]))
        start += length
    return [chunk for chunk in chunks if chunk]


# ---------------------------------------------------------------------------
# Scratch problems
# ---------------------------------------------------------------------------


def scratch_name(problem: str, pass_letter: str, chunk: int) -> str:
    return f"{SCRATCH_PREFIX}{problem}-{pass_letter}{chunk}"


def render_init(case_count: int, checker: str) -> str:
    """The scratch problem's ``init.yml``: a flat case list, one checker.

    Not batched, because a batch's *first* failure short-circuits the rest of the
    batch (``dmoj/judge.py:_grade_cases``) and a stress run wants every
    disagreement, not the first one per chunk.  A flat list of non-zero-point cases
    runs all of them and reports every one.
    """
    lines = [_SCRATCH_HEADER, f"checker: {checker}", "test_cases:"]
    for index in range(case_count):
        lines.append(
            f"- {{in: {CASES_DIRNAME}/{index}.in, out: {CASES_DIRNAME}/{index}.out, "
            f"points: {CASE_POINTS}}}"
        )
    return "\n".join(lines) + "\n"


def write_scratch(directory: Path, inputs: Sequence[str], checker: str, source: str) -> None:
    """Create one scratch problem: its inputs, its checker, and its ``init.yml``.

    The directory is cleared first, not merely created: a run killed between its
    ``finally`` and its cleanup leaves the tree behind, and a leftover problem with
    a stale ``cases/`` would otherwise make every later run of this command fail
    on its own leftovers.  This command owns that name, so it may replace it.

    Expected outputs start empty.  Pass A's checker accepts anything so it compares
    nothing, and pass B's outputs are written before the pool is asked to discover
    the problem, so the empty file is never graded against.
    """
    shutil.rmtree(directory, ignore_errors=True)
    (directory / CASES_DIRNAME).mkdir(parents=True)
    (directory / checker).write_text(source, encoding="utf-8")
    (directory / INIT_FILENAME).write_text(render_init(len(inputs), checker), encoding="utf-8")
    for index, text in enumerate(inputs):
        (directory / CASES_DIRNAME / f"{index}.in").write_text(text, encoding="utf-8")
        (directory / CASES_DIRNAME / f"{index}.out").write_bytes(b"")


def write_expected(directory: Path, outputs: Sequence[bytes]) -> None:
    """Write the model solution's answers as the scratch problem's expected outputs.

    Verbatim: the judge normalises an ``out`` file exactly as it normalises a real
    problem's (``dmoj/problem.py:TestCase._normalize``) and compares with its own
    checker, so these bytes are what a real ``cases/{i}.out`` would hold.
    """
    for index, output in enumerate(outputs):
        (directory / CASES_DIRNAME / f"{index}.out").write_bytes(output)


def remove_scratch(directories: Sequence[Path]) -> None:
    """Delete the scratch problems, whatever the run did.

    The whole tree, unconditionally: a scratch directory is this run's own creation
    at the problems root, and leaving one behind would leave a problem the judge
    keeps reporting on every later discovery.
    """
    for directory in directories:
        shutil.rmtree(directory, ignore_errors=True)


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------


def _limits_text(limits: meta_mod.Limits) -> str:
    return str(limits)


def _indented(text: str) -> str:
    return ("\n" + " " * 14).join(text.splitlines() or [""])


def skip(reason: str) -> int:
    """A problem this tool has nothing to say about, and why.

    Not a failure: a problem with no brute force or no small-case hook is simply
    outside the stress run's reach, and saying so with its reason is the whole
    requirement -- the alternative is a run that reports success having compared
    nothing.
    """
    print(f"stress: skipped - {reason}")
    return 0



def _indented(text: str) -> str:
    return ("\n" + " " * 14).join(text.splitlines() or [""])


def print_finding(
    entry: verify.Entry,
    index: int,
    total: int,
    verdict: str,
    seed: int,
    input_text: str,
    model_output: bytes,
    brute_output: bytes | None,
    problem: str,
) -> None:
    """The first case the judge did not accept, with both answers and the seed.

    ``WA`` is the finding this command exists for -- the two programs disagreed --
    and it is named as such.  Anything else (``TLE``, ``RTE``, ``IR``) is the judge
    saying the brute force produced no comparable answer, which is a different
    thing to go and fix, so it is reported as what it is rather than under a
    "counterexample" heading it does not deserve.
    """
    if verdict == "WA":
        print("stress: counterexample found")
    else:
        print(f"stress: no comparable answer -- the judge reported {verdict}")
    print(f"  brute       {entry.source.as_posix()} ({entry.executor})")
    print(f"  case        {index + 1} of {total}")
    print(f"  verdict     {verdict}")
    print(f"  seed        {seed}")
    print(f"  reproduce   problemsetting stress {problem} --seed {seed} --cases {total}")
    print(f"  input       {_indented(input_text)}")
    print(f"  model       {_indented(model_output.decode('utf-8', 'replace'))}")
    brute = (
        "<not reported: the judge stopped before the checker ran>"
        if brute_output is None
        else brute_output.decode("utf-8", "replace")
    )
    print(f"  brute       {_indented(brute)}")


# ---------------------------------------------------------------------------
# The pool, and both passes
# ---------------------------------------------------------------------------


def containers(wanted: int, problems_root: Path) -> list[str]:
    """Running pool containers, starting a pool when there is none.

    The pool is shared: a running one is reused rather than added to, which is what
    makes ``stress`` cheap to repeat (the expensive part is the judge's discovery,
    and a container that is up has already paid it).  Never more containers than
    the run has chunks for -- a container with an empty chunk would be a submission
    with nothing to grade.

    ``problems_root`` is the directory the pool mounts at ``/problems``; the
    scratch problems live directly under it, so a pool started here must be the
    one mounted on it.
    """
    running = judges.running_containers()
    if running:
        return running[: min(len(running), wanted)]
    names = judges.ensure_pool(
        min(wanted, judges.default_count()), problems_root=problems_root
    )[1]
    for name in names:
        if not judges.wait_ready(name):
            raise JudgeError(
                f"the judge container {name} never finished discovery; check it with "
                f"'podman logs {name}'"
            )
    return names


def submit_chunks(
    names: Sequence[str],
    chunks: Sequence[Sequence[str]],
    submit: Callable[[str, int], Any],
) -> list[Any]:
    """Run ``submit(container, chunk)`` for every chunk; one lane per container.

    Chunk ``k`` is handled by lane ``k % len(names)``, so chunks sharing a container
    also share a lane and are submitted one after another, never at the same time --
    the pool's launcher reads its command FIFO in a single loop, so overlapping
    submissions to one container could only queue.  Lanes are separate threads, so
    different containers do overlap, which is the parallelism the pool exists for.
    The result is aligned with ``chunks``, not with the order the tasks finished.
    """
    results: list[Any] = [None] * len(chunks)

    def lane(container_index: int) -> None:
        name = names[container_index]
        for chunk in range(container_index, len(chunks), len(names)):
            results[chunk] = submit(name, chunk)

    with ThreadPoolExecutor(max_workers=len(names)) as pool:
        list(pool.map(lane, range(len(names))))
    return results


def capture_answers(
    names: Sequence[str],
    chunks: Sequence[Sequence[str]],
    directories: Sequence[Path],
    resolved: meta_mod.ResolvedMeta,
    model_source: Path,
    problems_root: Path,
) -> list[list[bytes]]:
    """Pass A: run the model solution per chunk, and keep its answers.

    A case the model solution did not answer (any non-``AC`` verdict, or a checker
    that never ran) is reported rather than tolerated: an empty answer would make
    pass B meaningless for that case, and "the model solution fails on a valid tiny
    input" is a finding in its own right.
    """

    def one(container: str, chunk: int) -> list[bytes]:
        grading = judges.submit(
            container,
            directories[chunk].name,
            resolved.executor,
            model_source,
            time_limit=resolved.solution_limits.time,
            memory_limit=resolved.solution_limits.memory,
            problems_root=problems_root,
        )
        if grading.compile_error:
            raise JudgeError(
                f"{model_source.name} did not compile in {container}: {grading.compile_error}"
            )
        found = echoed_outputs(grading.raw)
        answers: list[bytes] = []
        for case in range(len(chunks[chunk])):
            observation = found.get(case + 1)
            if observation is None or observation.verdict != "AC" or observation.payload is None:
                verdict = observation.verdict if observation is not None else "not reported"
                raise JudgeError(
                    f"the model solution did not answer case {case + 1} of "
                    f"{directories[chunk].name} (verdict {verdict}); gen_small() has to "
                    f"produce inputs the model solution can answer"
                )
            answers.append(observation.payload)
        return answers

    return submit_chunks(names, chunks, one)


@dataclasses.dataclass(frozen=True)
class Disagreement:
    """One case where the judge did not accept the brute force, with both answers."""

    index: int
    verdict: str
    outputs: tuple[bytes | None, bytes | None] | None


def compare(
    names: Sequence[str],
    chunks: Sequence[Sequence[str]],
    offsets: Sequence[int],
    directories: Sequence[Path],
    entry: verify.Entry,
    problems_root: Path,
) -> Disagreement | None:
    """Pass B: run one brute force per chunk, and return the first disagreement.

    The judge's verdict is the finding -- ``AC`` is agreement, and anything else is
    something the brute force could not confirm.  Which of several real
    disagreements to report is the only choice here, and it is the lowest case
    number: the one ``--seed`` regenerates first.
    """

    def one(container: str, chunk: int) -> list[Disagreement]:
        grading = judges.submit(
            container,
            directories[chunk].name,
            entry.executor,
            entry.path,
            time_limit=entry.limits.time,
            memory_limit=entry.limits.memory,
            problems_root=problems_root,
        )
        if grading.compile_error:
            raise JudgeError(
                f"{entry.source.as_posix()} did not compile in {container}: "
                f"{grading.compile_error}"
            )
        return [
            Disagreement(offsets[chunk] + position - 1, observation.verdict, observation.payload)
            for position, observation in sorted(compared_outputs(grading.raw).items())
            if observation.verdict != "AC"
        ]

    found = sorted(
        (
            disagreement
            for per_chunk in submit_chunks(names, chunks, one)
            for disagreement in per_chunk
        ),
        key=lambda disagreement: disagreement.index,
    )
    return found[0] if found else None


# ---------------------------------------------------------------------------
# The command
# ---------------------------------------------------------------------------

HELP = "compare the model solution against the declared brute force on tiny random cases"


def add_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("problem", help="problem directory to stress-test")
    parser.add_argument(
        "--cases",
        type=int,
        default=DEFAULT_CASES,
        help=f"how many tiny cases to compare (default: {DEFAULT_CASES})",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=None,
        help="seed for the tiny cases (default: one per run, always reported)",
    )


def run(args: argparse.Namespace) -> int:
    return run_stress(args.problem, count=args.cases, seed=args.seed)


def run_stress(
    problem: str,
    *,
    count: int = DEFAULT_CASES,
    seed: int | None = None,
) -> int:
    problem_dir = judges.resolve_problem(problem)
    _, resolved = meta_mod.load(problem_dir)

    # The one model whose submission is not a stdin/stdout program: an
    # `output-only` submission is a text file (`cat`), so there is no program to
    # compare a brute force against.
    if resolved.is_output_only:
        return skip(
            f"model {resolved.model!r} grades a text file rather than a program, so there "
            f"is no model solution to compare a brute force against"
        )

    if count < 1:
        raise CaseError(f"--cases must be at least 1, got {count}")
    seed = seed if seed is not None else random.SystemRandom().randrange(1, 2**31)

    generator_file = problem_dir / cases_mod.GENERATOR_FILENAME
    # The same seed drives the generator's own `Generator(seed)` and the hook's
    # `rand`, so `--seed` pins every random choice the run makes.
    generator = cases_mod.load_generator(problem_dir, seed)
    if not callable(getattr(generator, "gen_small", None)):
        return skip(
            f"{generator_file}: the generator defines no gen_small(rand), so there are no "
            f"tiny cases to compare on.  Add one (the `standard` template's Generator "
            f"docstring has the shape: return case object(s) holding a small input, using "
            f"`rand` for every random choice)"
        )

    entries = verify.load_manifest(problem_dir, resolved)
    brutes = [entry for entry in entries if entry.role == verify.BRUTE_ROLE]
    if not brutes:
        return skip(
            f"{problem_dir / verify.MANIFEST_FILENAME}: no submission declares "
            f"`role: brute`; declare the reference brute force there so it can be compared "
            f"against the model solution"
        )

    model_source = problem_dir / f"solution{resolved.solutionlang}"
    if not model_source.is_file():
        raise OutputError(
            f"{model_source} not found: a stress run compares the brute force against the "
            f"model solution, and meta.yml declares solutionlang: {resolved.solutionlang}"
        )

    root = judges.problems_root()
    inputs = small_cases(generator, seed, count, str(generator_file))
    names = containers(len(inputs), root)
    chunks = split(inputs, len(names))
    offsets: list[int] = []
    start = 0
    for chunk in chunks:
        offsets.append(start)
        start += len(chunk)
    total = start
    above = [root / scratch_name(problem_dir.name, "a", chunk) for chunk in range(len(chunks))]
    below = [root / scratch_name(problem_dir.name, "b", chunk) for chunk in range(len(chunks))]

    print(
        f"==> stress {problem_dir.name}  (model {resolved.model}, seed {seed}, "
        f"{total} case(s) from gen_small)"
    )
    print(
        f"    model     {model_source.name} ({resolved.executor}, "
        f"{_limits_text(resolved.solution_limits)})"
    )
    for entry in brutes:
        print(
            f"    brute     {entry.source.as_posix()} ({entry.executor}, "
            f"{_limits_text(entry.limits)})"
        )
    print(f"    judges    {', '.join(names)}  ({len(chunks)} chunk(s) of ~{len(chunks[0])})")

    try:
        for chunk, directory in enumerate(above):
            write_scratch(directory, chunks[chunk], ECHO_CHECKER, ECHO_CHECKER_SOURCE)
        for chunk, directory in enumerate(below):
            write_scratch(directory, chunks[chunk], DIFF_CHECKER, DIFF_CHECKER_SOURCE)
        # Discovery happens once, at container start (decision Q28), so a pool that
        # was already up has to be told about problems it has never seen.
        for name in names:
            judges.update_problems(name)

        answers = capture_answers(names, chunks, above, resolved, model_source, root)
        for chunk, directory in enumerate(below):
            write_expected(directory, answers[chunk])

        for entry in brutes:
            disagreement = compare(names, chunks, offsets, below, entry, root)
            if disagreement is not None:
                index = disagreement.index
                chunk = max(position for position, offset in enumerate(offsets) if offset <= index)
                print_finding(
                    entry,
                    index,
                    total,
                    disagreement.verdict,
                    seed,
                    chunks[chunk][index - offsets[chunk]],
                    answers[chunk][index - offsets[chunk]],
                    disagreement.outputs[1] if disagreement.outputs else None,
                    problem,
                )
                return 1
            print(f"    brute     {entry.source.as_posix()}: no disagreement on {total} case(s)")
    finally:
        remove_scratch([*above, *below])

    print(
        f"stress: no counterexample -- the brute force agreed with the model solution on "
        f"all {total} case(s) (seed {seed})"
    )
    return 0


register(Command(name="stress", help=HELP, add_arguments=add_arguments, run=run))

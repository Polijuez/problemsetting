"""The ``batched-custom`` template: subtasks *and* a quality checker together.

The model exists because the two mechanisms interact, so these tests defend the
interaction rather than either piece alone -- the pieces are
:mod:`tests.test_model_batched` and :mod:`tests.test_model_custom`.

What the interaction means, and what is therefore asserted here:

* the checker is called **once per case**, with that case's *batch*
  ``point_value`` -- so the same fraction of the optimum yields a different
  number in each subtask (``0.7 * 10`` in ST1, ``0.7 * 40`` in ST4);
* a case the checker **rejects** short-circuits the rest of its batch, so how
  much partial credit survives depends on *where* in the batch the failure is;
* a subtask that earned a *fraction* still counts as passed for
  ``dependencies``, because the judge looks at the verdict flag, not the points.

The end-to-end numbers in ``submissions.yml`` are the other half of that claim:
they are only correct if the fraction composes with the batch points the way
this file says, and the ticket's acceptance criteria check them against a real
container with ``problemsetting verify`` by hand.
"""

from __future__ import annotations

import dataclasses
import io
import random
import shutil
import subprocess
import sys
import textwrap
import types
from pathlib import Path

import pytest
import yaml

import support
from problemsetting import cases as cases_mod
from problemsetting import cli
from problemsetting import meta as meta_mod
from problemsetting import templates
from problemsetting import verify

MODEL = "batched-custom"


# ---------------------------------------------------------------------------
# Loading the template's own files
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def template() -> Path:
    return templates.template_dir(MODEL)


@pytest.fixture(scope="module")
def generator_module(template: Path):
    # Via support.load_module, not importlib: a template is shipped package data,
    # and importlib's file loader would leave __pycache__ inside it.
    return support.load_module(template / "generator.py", "_batched_custom_generator")


@pytest.fixture(scope="module")
def checker_module(template: Path):
    """The checker, loaded with a stub ``dmoj`` -- the host has no judge installed.

    The stub is only enough of ``dmoj`` for the module to import; it is not a
    mock of the checker's behaviour, so the code under test is the template's own.
    """
    if "dmoj.result" not in sys.modules:

        @dataclasses.dataclass
        class CheckerResult:
            passed: bool
            points: float = 0.0
            feedback: str | None = None
            extended_feedback: str | None = None

        def utf8text(data, errors="strict"):
            return data.decode("utf-8", errors) if isinstance(data, bytes) else str(data)

        modules = {
            "dmoj": types.ModuleType("dmoj"),
            "dmoj.result": types.ModuleType("dmoj.result"),
            "dmoj.utils": types.ModuleType("dmoj.utils"),
            "dmoj.utils.unicode": types.ModuleType("dmoj.utils.unicode"),
        }
        modules["dmoj.result"].CheckerResult = CheckerResult
        modules["dmoj.utils.unicode"].utf8text = utf8text
        sys.modules.update(modules)

    return support.load_module(template / "checker.py", "_batched_custom_checker")


#: The checker's own signature, as DMOJ calls it (``dmoj/graders/standard.py:57``).
#: ``point_value`` is the *batch's* points, which is the whole subject of this file.
def check(checker_module, output: str, *, n: int, model_out: str, point_value: float = 100.0):
    return checker_module.check(
        process_output=output.encode(),
        judge_output=model_out.encode(),
        judge_input=f"{n}\n".encode(),
        point_value=point_value,
        submission_source=b"",
    )


#: The model solution's answer for ``n``, as the ``.out`` files hold it:
#: ``ceil(n/5)`` lamps at 3, 8, 13, ...  Built here rather than read from the
#: template, so a test states the fact it depends on instead of inheriting it.
def model_output(n: int) -> str:
    lamps = [((2 + 5 * j) % n) + 1 for j in range(-(-n // 5))]
    return f"{len(lamps)}\n" + " ".join(str(lamp) for lamp in lamps) + "\n"


def copy_template(tmp_path: Path) -> Path:
    """The shipped template, copied out of the package into a scratch directory."""
    destination = tmp_path / MODEL
    shutil.copytree(
        templates.template_dir(MODEL),
        destination,
        ignore=shutil.ignore_patterns(*templates.TEMPLATE_IGNORE),
    )
    return destination


def render_init(destination: Path) -> str:
    """Run the real ``init.yml`` emission against ``destination``, no CLI needed."""
    _, resolved = meta_mod.load(destination)
    generator = cases_mod.load_generator(destination)
    source = str(destination / cases_mod.GENERATOR_FILENAME)
    cases = cases_mod.read_cases(generator, source)
    subtasks = cases_mod.read_subtasks(generator, source)
    membership = cases_mod.classify(subtasks, cases, source)
    files, _ = cases_mod.write_case_files(destination, cases, has_input=True, source=source)
    return cases_mod.render_init(destination.name, resolved, subtasks, membership, files)


def membership_of(generator_module):
    """The case list and the per-subtask membership the real emission computes."""
    generator = generator_module.Generator()
    cases = generator.get_cases()
    subtasks = cases_mod.read_subtasks(generator, "generator.py")
    return cases, cases_mod.classify(subtasks, cases, "generator.py")


# ---------------------------------------------------------------------------
# The template is a complete problem
# ---------------------------------------------------------------------------


def test_template_ships_the_whole_problem(template: Path) -> None:
    for name in ("meta.yml", "generator.py", "checker.py", "solution.cpp", "submissions.yml"):
        assert (template / name).is_file(), name
    assert (template / "media" / "statement.md").is_file()
    assert list((template / "submissions").glob("*.cpp"))


def test_template_meta_yml_declares_batched_custom(template: Path) -> None:
    authoring, resolved = meta_mod.load(template)
    assert authoring["model"] == MODEL
    assert resolved.model == MODEL
    assert resolved.axes == {
        "grader": "standard",
        "checker": "custom",
        "batch": "subtasks",
        "io": "stdio",
        "submission": "program",
        "executor": "CPP17",
    }
    assert resolved.uses_checker
    assert resolved.is_batched
    assert resolved.executor == "CPP17"


def test_template_meta_yml_header_matches_meta_HEADER(template: Path) -> None:
    """The template's header is the one users see, so it tracks ``meta.HEADER``."""
    assert (template / "meta.yml").read_text(encoding="utf-8").startswith(meta_mod.HEADER)


def test_the_template_documents_the_two_axes_and_their_interaction(template: Path) -> None:
    """The file is package data *and* documentation; the interaction is the point."""
    text = (template / "meta.yml").read_text(encoding="utf-8")
    # The distinction `checker:` vs `custom_judge:` decides which grader drives,
    # and this model is the one where both axes are live at once.
    assert "custom_judge" in text
    # The fact the whole model turns on: point_value is the case's BATCH.
    assert "point_value" in text


def test_the_checker_is_declared_as_a_plain_module_path(template: Path, tmp_path: Path) -> None:
    """``checker: checker.py``, not ``custom_judge:`` -- two different mechanisms."""
    source = (template / "checker.py").read_text(encoding="utf-8")
    assert "def check(" in source
    assert "class Grader" not in source

    init = render_init(copy_template(tmp_path))
    assert "checker: checker.py" in init
    assert "custom_judge" not in init


# ---------------------------------------------------------------------------
# Generator protocol
# ---------------------------------------------------------------------------


def test_get_cases_returns_ordered_cases_with_the_required_methods(generator_module) -> None:
    cases = generator_module.Generator().get_cases()
    assert cases
    for case in cases:
        assert isinstance(case.n, int)
        assert callable(case.check)
        assert callable(case.write_file)


def test_generator_is_deterministic_per_seed(generator_module) -> None:
    first = generator_module.Generator().get_cases()
    second = generator_module.Generator().get_cases()
    assert [c.n for c in first] == [c.n for c in second]


def test_case_write_file_emits_the_declared_input_format(generator_module) -> None:
    buffer = io.StringIO()
    generator_module.TestCase(2000).write_file(buffer)
    assert buffer.getvalue() == "2000\n"


def test_case_check_rejects_sizes_outside_the_statements_range(generator_module) -> None:
    limit = generator_module.N_MAX
    generator_module.TestCase(1)
    generator_module.TestCase(limit)  # the boundary is fine
    with pytest.raises(AssertionError):
        generator_module.TestCase(0)
    with pytest.raises(AssertionError):
        generator_module.TestCase(limit + 1)


def test_get_subtasks_yields_points_and_callable_classifiers(generator_module) -> None:
    subtasks = generator_module.Generator().get_subtasks()
    assert subtasks
    total = 0
    for number, entry in enumerate(subtasks, start=1):
        assert len(entry) in (2, 3)
        points, classifier = entry[0], entry[1]
        assert isinstance(points, (int, float)) and points > 0
        assert callable(classifier)
        total += points
        if len(entry) == 3:
            assert all(dependency < number for dependency in entry[2])
    # Acceptance criterion: the subtask points sum to 100.
    assert total == 100


def test_the_last_subtask_accepts_every_case(generator_module) -> None:
    """The convention init.yml emission relies on: the last check is all-accepting."""
    cases = generator_module.Generator().get_cases()
    assert all(generator_module.check_st4(case) for case in cases)


def test_subtask_classifiers_accumulate_upward(generator_module) -> None:
    _, membership = membership_of(generator_module)
    assert [len(group) for group in membership] == sorted(len(group) for group in membership)
    # Every case in ST1 is also in ST2, ST3 and ST4.
    assert set(membership[0]) <= set(membership[1]) <= set(membership[2]) <= set(membership[3])


def test_the_cases_are_ordered_largest_first_within_each_subtask(generator_module) -> None:
    """The ordering is load-bearing, so it is asserted rather than left implicit.

    A batch short-circuits on the first case it fails, so putting the largest
    case first is what keeps an inadequate submission from collecting the
    fraction of the small cases it happened to get right before the failure.
    """
    cases, membership = membership_of(generator_module)
    for group in membership:
        sizes = [cases[index].n for index in group]
        assert sizes == sorted(sizes, reverse=True), sizes


def test_at_least_one_subtask_declares_a_dependency(generator_module) -> None:
    """The ``dependencies`` mechanism is demonstrated, not merely documented."""
    subtasks = generator_module.Generator().get_subtasks()
    dependencies = [entry[2] for entry in subtasks if len(entry) == 3]
    assert any(dependencies)
    for number, entry in enumerate(subtasks, start=1):
        if len(entry) == 3:
            assert all(dep < number for dep in entry[2]), "a batch may only depend on earlier batches"


def test_gen_small_returns_cases_a_suboptimal_construction_can_use(generator_module) -> None:
    """The tiny cases stay in the range where ``optimo + 1`` lamps exist.

    ``n = 1`` has a single position and the optimum already uses it, so a
    "suboptimal by one" submission would have nowhere to put the extra lamp.
    """
    rand = random.Random(1234)
    for _ in range(50):
        (case,) = generator_module.Generator().gen_small(rand)
        assert 6 <= case.n <= 60


# ---------------------------------------------------------------------------
# The model solution
# ---------------------------------------------------------------------------


def test_the_model_solution_is_the_optimal_formula(checker_module) -> None:
    """``ceil(n/5)``, recomputed by the checker rather than read from the model."""
    assert [checker_module.optimo(n) for n in (48, 49, 50, 51, 200000)] == [10, 10, 10, 11, 40000]


def test_the_model_solution_covers_the_circle_at_every_declared_size(
    generator_module, checker_module, template: Path, tmp_path: Path
) -> None:
    """Compile ``solution.cpp`` and check it actually illuminates the round.

    Checked as a *program*, not as a transcribed algorithm: the C++ is what
    produces the ``.out`` files, and the checker rejects a model output that is
    not optimal, so a wrong model would be a broken problem rather than a
    failing test somewhere else.  ``g++`` is on PATH everywhere the toolkit
    runs; a missing compiler is a skip, so this stays green on a host with only
    Python.
    """
    compiler = shutil.which("g++")
    if compiler is None:
        pytest.skip("g++ is not on PATH")

    binary = tmp_path / "solution"
    subprocess.run(
        [compiler, "-O2", "-std=c++17", str(template / "solution.cpp"), "-o", str(binary)],
        check=True,
        capture_output=True,
    )

    def run_program(n: int) -> list[int]:
        completed = subprocess.run(
            [str(binary)], input=f"{n}\n", capture_output=True, text=True, check=True
        )
        return [int(token) for token in completed.stdout.split()[1:]]

    for case in generator_module.Generator().get_cases():
        printed = run_program(case.n)
        assert len(printed) == checker_module.optimo(case.n), case.n
        assert checker_module.cubre(printed, case.n), case.n


def test_no_test_run_writes_into_the_template() -> None:
    """The template directory is package data; nothing here may write into it."""
    template_dir = templates.template_dir(MODEL)
    assert not (template_dir / "__pycache__").exists(), (
        "a previous run left bytecode inside the shipped template"
    )


# ---------------------------------------------------------------------------
# The checker: fractional points, composed with the batch's point_value
# ---------------------------------------------------------------------------


def test_optimal_output_earns_full_marks_in_its_batch(checker_module) -> None:
    result = check(checker_module, model_output(6), n=6, model_out=model_output(6))
    assert result.passed and result.points == 100.0


def test_valid_but_suboptimal_output_earns_partial_credit(checker_module) -> None:
    result = check(checker_module, "3\n3 1 2\n", n=6, model_out=model_output(6))
    assert result.passed is True
    assert result.points == pytest.approx(0.7 * 100.0)


def test_a_valid_but_very_inefficient_output_earns_the_lower_band(checker_module) -> None:
    """The score is a function of quality, not an accept/reject switch."""
    # 6 lamps for n = 6: more than double the optimum of 2.
    result = check(checker_module, "6\n1 2 3 4 5 6\n", n=6, model_out=model_output(6))
    assert result.passed is True
    assert result.points == pytest.approx(0.4 * 100.0)


def test_the_partial_fraction_composes_with_the_batchs_point_value(checker_module) -> None:
    """The subject of the model: ``point_value`` is the case's BATCH, not the problem.

    The same suboptimal construction is graded once per batch.  The fraction is
    identical; the points are not, because each call is handed a different
    ``point_value`` -- which is what ``dmoj/problem.py:234-238`` does by
    propagating the batch's ``points:`` down to every case inside it.
    """
    for batch_points in (10, 20, 30, 40):  # the template's four subtasks
        result = check(
            checker_module, "3\n3 1 2\n", n=6, model_out=model_output(6), point_value=batch_points
        )
        assert result.passed is True
        assert result.points == pytest.approx(0.7 * batch_points), batch_points


def test_no_single_case_can_award_the_problems_points(checker_module) -> None:
    """Each call sees only its batch, so the ceiling is the batch's value.

    A checker that (wrongly) assumed ``point_value`` was the problem total would
    return 70 for a suboptimal answer in a 10-point batch -- seven times what the
    batch is worth.
    """
    result = check(checker_module, "3\n3 1 2\n", n=6, model_out=model_output(6), point_value=10)
    assert result.points == pytest.approx(7.0)
    assert result.points < 10


def test_an_invalid_construction_earns_zero_despite_a_well_formed_output(checker_module) -> None:
    """A rejection is what makes a batch short-circuit; a fraction does not."""
    result = check(checker_module, "1\n1\n", n=6, model_out=model_output(6))
    assert result.passed is False and result.points == 0.0


def test_a_rejection_is_distinct_from_a_partial_award(checker_module) -> None:
    """``passed`` is the flag the judge short-circuits on; the fraction is not.

    DMOJ sets ``is_short_circuiting`` on ``Result.WA``, which comes from
    ``check.passed`` -- not from ``check.points`` (``dmoj/graders/standard.py``
    fuses them as ``[WA, AC][check.passed]``).  So a batch of suboptimal answers
    keeps running, while one rejection ends it.  This is the fact the manifest's
    ``21`` depends on.
    """
    partial = check(checker_module, "3\n3 1 2\n", n=6, model_out=model_output(6), point_value=20)
    rejected = check(checker_module, "1\n1\n", n=6, model_out=model_output(6), point_value=20)
    assert (partial.passed, rejected.passed) == (True, False)
    assert partial.points == pytest.approx(14.0) and rejected.points == 0.0


def test_the_partial_fraction_is_a_named_constant(checker_module) -> None:
    """The fraction the manifest documents is the checker's own constant."""
    assert checker_module.PUNTAJE_PARCIAL == 0.7
    assert checker_module.PUNTAJE_POBRE == 0.4
    assert checker_module.PUNTAJE_POBRE < checker_module.PUNTAJE_PARCIAL


def test_the_optimum_is_the_circles_covering_number(checker_module) -> None:
    """``ceil(n/5)``: a lamp covers five positions, so nothing smaller can work."""
    assert checker_module.RADIO == 2
    assert checker_module.ALCANCE == 5
    assert [checker_module.optimo(n) for n in (1, 5, 6, 11)] == [1, 1, 2, 3]


# ---------------------------------------------------------------------------
# The checker validates the object, not the claimed count
# ---------------------------------------------------------------------------


def test_a_claimed_count_that_does_not_match_the_object_is_not_rewarded(checker_module) -> None:
    """Lying about how many lamps were placed is not a way to earn full marks."""
    # Three lamps claimed, two actually sent.  The claim alone would be optimal
    # if the checker believed it, so this is not a rejection of the count -- it is
    # the checker refusing to score a construction it cannot trust.
    result = check(checker_module, "3\n3 2\n", n=6, model_out=model_output(6))
    assert result.passed is False and result.points == 0.0
    assert "declara" in (result.feedback or "")


def test_repeated_positions_do_not_count_towards_the_score(checker_module) -> None:
    """Two lamps at one position illuminate no more than one."""
    result = check(checker_module, "3\n1 1 1\n", n=6, model_out=model_output(6))
    assert result.passed is False
    assert "repetidas" in (result.feedback or "")


def test_positions_outside_the_round_are_refused(checker_module) -> None:
    result = check(checker_module, "2\n1 99\n", n=6, model_out=model_output(6))
    assert result.passed is False and result.points == 0.0
    assert "fuera de 1..6" in (result.feedback or "")


def test_an_empty_output_is_rejected_without_a_crash(checker_module) -> None:
    result = check(checker_module, "", n=6, model_out=model_output(6))
    assert result.passed is False and result.points == 0.0


def test_a_first_line_that_is_not_a_number_is_rejected(checker_module) -> None:
    result = check(checker_module, "tantos\n", n=6, model_out=model_output(6))
    assert result.passed is False and result.points == 0.0


def test_a_claim_of_zero_lamps_is_rejected(checker_module) -> None:
    result = check(checker_module, "0\n\n", n=6, model_out=model_output(6))
    assert result.passed is False and result.points == 0.0


def test_a_claim_larger_than_the_round_is_rejected(checker_module) -> None:
    result = check(
        checker_module, "99\n" + " ".join(["1"] * 99) + "\n", n=6, model_out=model_output(6)
    )
    assert result.passed is False and result.points == 0.0


@pytest.mark.parametrize(
    "output",
    ["", "\n", "basura", "1 2 3 4", "3\nuno dos tres\n", "-1\n-1\n", "3\n1 2\n", "3\n1 2 99\n"],
)
def test_malformed_output_never_raises(checker_module, output: str) -> None:
    """A checker that raises is graded as an internal error: a broken problem."""
    result = check(checker_module, output, n=6, model_out=model_output(6))
    assert result.passed in (True, False)
    assert 0.0 <= result.points <= 100.0


def test_garbage_after_a_valid_first_line_is_a_rejection_not_a_partial_score(checker_module) -> None:
    """The deliberate contrast with ``custom``.

    ``custom`` gives a valid first line the partial floor even when the rest is
    unreadable, because there the score rewards having understood the problem.
    Here the score is a function of the *construction*, and a construction whose
    positions cannot be read has no quality to reward -- so it is refused
    deterministically rather than scored.  What is not optional is that the
    refusal is deterministic and never an exception.
    """
    result = check(checker_module, "3\na b c\n", n=6, model_out=model_output(6))
    assert result.passed is False and result.points == 0.0


def test_malformed_input_data_is_an_error_not_a_partial_score(checker_module) -> None:
    """The asymmetry: the *problem's* input is ours, so a bad one is a real error."""
    with pytest.raises(ValueError):
        checker_module.check(
            process_output=b"2\n3 2\n",
            judge_output=model_output(6).encode(),
            judge_input=b"",
            point_value=10,
            submission_source=b"",
        )


def test_a_non_optimal_model_output_is_an_error_not_a_partial_score(checker_module) -> None:
    """Our ``.out`` is generated from the model solution, so it must be optimal."""
    with pytest.raises(ValueError, match="óptimo"):
        check(checker_module, "2\n3 2\n", n=6, model_out="1\n1\n")


def test_the_checker_recomputes_coverage_from_the_positions_it_received(checker_module) -> None:
    """The object is what was sent, not what the first line claims."""
    # A lamp covers five positions, so for n = 6 a single lamp always leaves one
    # dark: the position three ahead of it, which is exactly what is not covered.
    assert checker_module.cubre([3, 2], 6)
    assert not checker_module.cubre([3], 6)
    result = check(checker_module, "1\n3\n", n=6, model_out=model_output(6))
    assert result.passed is False


# ---------------------------------------------------------------------------
# The manifest verify reads
# ---------------------------------------------------------------------------


def test_the_template_manifest_matches_the_schema_verify_reads(template: Path) -> None:
    """The template ships the manifest users start from, so it must parse."""
    _, resolved = meta_mod.load(template)
    entries = verify.load_manifest(template, resolved)
    assert entries
    assert all(entry.declares_expectation for entry in entries)
    assert all(entry.limits == resolved.limits[entry.limits_key] for entry in entries)


def test_the_manifest_declares_the_subjects_the_ticket_requires(template: Path) -> None:
    """Full marks, a fraction, a zero, and one that fails a specific subtask."""
    _, resolved = meta_mod.load(template)
    entries = {entry.source.name: entry for entry in verify.load_manifest(template, resolved)}

    # Full marks.
    assert entries["solution.cpp"].role == "model"
    assert entries["solution.cpp"].score == 100.0
    # Partial credit in a smaller subtask only: 0.7 of the 10-point ST1.
    assert entries["solo-chicos.cpp"].score == 7.0
    assert entries["solo-chicos.cpp"].verdict == "WA"
    # Partial credit in two subtasks and an outright failure in a third: 7 + 14.
    assert entries["hasta-2000.cpp"].score == 21.0
    assert entries["hasta-2000.cpp"].verdict == "WA"
    # Zero for an invalid output.
    assert entries["invalido.cpp"].score == 0.0 and entries["invalido.cpp"].verdict == "WA"
    # And the rejected-garbage subject.
    assert entries["malformado.cpp"].role == "checker-test"


def test_the_partial_submissions_declare_real_fractions_not_full_marks(template: Path) -> None:
    """Guards against the old workaround, which declared ``score: 100``.

    Before ticket 17 the judge transcript carried no per-case points, so a
    fractional checker was indistinguishable from full marks and the manifest
    had to declare 100 with a comment.  ``verify`` now scores the fraction, so a
    partial submission declaring 100 would mean the fraction is not measured.
    """
    _, resolved = meta_mod.load(template)
    entries = {entry.source.name: entry for entry in verify.load_manifest(template, resolved)}
    for name in ("solo-chicos.cpp", "hasta-2000.cpp"):
        assert 0 < entries[name].score < 100, name


def test_the_partial_submissions_are_not_declared_as_checker_tests(template: Path) -> None:
    """``role: checker-test`` means "the checker must reject this"."""
    _, resolved = meta_mod.load(template)
    entries = {entry.source.name: entry for entry in verify.load_manifest(template, resolved)}
    assert entries["solo-chicos.cpp"].role is None
    assert entries["hasta-2000.cpp"].role is None
    assert entries["malformado.cpp"].role == "checker-test"


def test_the_manifest_explains_where_the_partial_scores_come_from(template: Path) -> None:
    """The numbers come from a run, and the file has to say so."""
    text = (template / "submissions.yml").read_text(encoding="utf-8")
    assert "point_value" in text
    assert "verify" in text


def test_the_manifest_explains_the_absent_brute_force(template: Path) -> None:
    """The ticket allows an absence that is explained rather than demonstrated."""
    text = (template / "submissions.yml").read_text(encoding="utf-8")
    assert "role: brute" in text
    assert "exponencial" in text or "subconjuntos" in text


# ---------------------------------------------------------------------------
# The problem is buildable (the real generator, no CLI)
# ---------------------------------------------------------------------------


def test_the_shipped_template_renders_init_yml_with_the_checker(tmp_path: Path) -> None:
    init = render_init(copy_template(tmp_path))
    assert "checker: checker.py" in init
    assert "test_cases:" in init
    # Four batches, one per subtask, summing to 100.
    assert init.count("- points:") == 4
    for points in (10, 20, 30, 40):
        assert f"- points: {points}" in init
    # Exactly one dependency, and it names an earlier batch.
    assert init.count("dependencies:") == 1
    assert "dependencies: [2]" in init


def test_init_yml_declares_the_dependency_only_where_the_generator_does(tmp_path: Path) -> None:
    """A `dependencies:` key is emitted only for the subtask that declares one."""
    document = yaml.safe_load(render_init(copy_template(tmp_path)))
    declared = [entry.get("dependencies", []) for entry in document["test_cases"]]
    assert declared == [[], [], [2], []]


# ---------------------------------------------------------------------------
# The CLI scaffolds it
# ---------------------------------------------------------------------------


def test_new_scaffolds_a_batched_custom_problem(tmp_path: Path, monkeypatch) -> None:
    """``new --model batched-custom`` produces a problem the toolkit recognises."""
    monkeypatch.chdir(tmp_path)
    assert cli.main(["new", "--model", MODEL, "ronda-demo"]) == 0

    problem = tmp_path / "ronda-demo"
    assert (problem / "checker.py").is_file()
    assert (problem / "generator.py").is_file()
    assert (problem / "submissions.yml").is_file()
    _, resolved = meta_mod.load(problem)
    assert resolved.model == MODEL
    assert resolved.uses_checker and resolved.is_batched


def test_new_scaffolds_into_a_directory_the_pool_can_discover(tmp_path: Path, monkeypatch) -> None:
    """DMOJ discovers problems with ``glob``, which skips leading-dot components.

    A problem scaffolded into ``.work/`` is never found, and every submission
    fails with ``unknown problem`` -- so the scaffolded directory is a normal one.
    """
    monkeypatch.chdir(tmp_path)
    assert cli.main(["new", "--model", MODEL, "ronda-demo"]) == 0
    problem = tmp_path / "ronda-demo"
    assert not any(part.startswith(".") for part in problem.relative_to(tmp_path).parts)


def test_batched_custom_is_shipped() -> None:
    """``templates.shipped()`` discovers templates by directory presence."""
    assert MODEL in templates.shipped()


def test_the_scaffolded_problem_builds_the_ladder_and_the_checker(tmp_path: Path, monkeypatch) -> None:
    """``new`` → ``cases``: the emitted init.yml has the checker and the ladder."""
    monkeypatch.chdir(tmp_path)
    assert cli.main(["new", "--model", MODEL, "ronda-demo"]) == 0
    assert cli.main(["cases", "ronda-demo"]) == 0

    document = yaml.safe_load((tmp_path / "ronda-demo" / "init.yml").read_text(encoding="utf-8"))
    assert document["checker"] == "checker.py"
    assert [entry["points"] for entry in document["test_cases"]] == [10, 20, 30, 40]
    assert document["test_cases"][2]["dependencies"] == [2]


def write_stub_problem(problem: Path, subtasks: str) -> None:
    """A minimal problem whose generator returns ``subtasks`` verbatim."""
    problem.mkdir()
    meta_mod.write(problem, meta_mod.normalize({"model": MODEL, "solutionlang": ".cpp"}))
    (problem / "checker.py").write_text("def check(**_):\n    return True\n")
    (problem / cases_mod.GENERATOR_FILENAME).write_text(
        textwrap.dedent(
            f"""
            class TestCase:
                def __init__(self, v):
                    self.v = v

                def write_file(self, f):
                    f.write(f"{{self.v}}\\n")

            class Generator:
                def __init__(self, seed=0):
                    pass

                def get_cases(self):
                    return [TestCase(6)]

                def get_subtasks(self):
                    return {subtasks}
            """
        )
    )


def test_a_single_subtask_is_refused(tmp_path: Path, monkeypatch) -> None:
    """The guard that keeps the ladder from silently disappearing.

    `batch: subtasks` with one subtask would still emit valid YAML -- a single
    batch worth everything -- and the model would no longer be what it says.
    """
    write_stub_problem(tmp_path / "sola", "[(100, lambda c: True)]")
    monkeypatch.chdir(tmp_path)
    assert cli.main(["cases", "sola"]) == 1


def test_a_missing_checker_file_is_refused(tmp_path: Path, monkeypatch) -> None:
    """``init.yml`` will name ``checker.py``, so its absence is an authoring error."""
    problem = tmp_path / "sinchecker"
    write_stub_problem(problem, "[(40, lambda c: c.v <= 6), (60, lambda c: True)]")
    (problem / "checker.py").unlink()
    monkeypatch.chdir(tmp_path)
    assert cli.main(["cases", "sinchecker"]) == 1


def test_a_dependency_on_a_later_batch_is_refused(tmp_path: Path, monkeypatch) -> None:
    """The toolkit refuses what DMOJ would refuse at load time."""
    write_stub_problem(tmp_path / "tarde", "[(40, lambda c: True), (60, lambda c: True, [2])]")
    monkeypatch.chdir(tmp_path)
    assert cli.main(["cases", "tarde"]) == 1

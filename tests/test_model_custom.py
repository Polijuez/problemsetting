"""The ``custom`` template: a checker that scores by quality, plus the codegolf recipe.

The template is a *problem*: a generator, a model solution, a checker and a
manifest.  The tests below exercise it the way the toolkit does -- loading the
files rather than re-implementing them -- and the checker in particular is
driven through the real ``check()`` signature with a stubbed ``dmoj``, because
"what does the judge do with this output?" is the whole question this model
exists to answer.

The end-to-end run (``new`` → ``build`` → ``verify`` against a real judge
container) lives in :mod:`tests.test_model_custom_judge`, which is opt-in for the
same reason :mod:`tests.test_judge_pool` is: it needs the 15 GB image.
"""

from __future__ import annotations

import io
import random
import shutil
import subprocess
import sys
import textwrap
import types
from pathlib import Path

import pytest
from problemsetting import cases as cases_mod
from problemsetting import cli
from problemsetting import meta as meta_mod
from problemsetting import templates

MODEL = "custom"


# ---------------------------------------------------------------------------
# Loading the template's own files
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def template() -> Path:
    return templates.template_dir(MODEL)


def load_module(name: str, path: Path):
    """Load an author file the way the toolkit does: compile it from source.

    ``cases.load_generator`` is explicit that ``importlib``'s file loader is the
    wrong tool here -- it honours a stale sibling ``__pycache__`` entry and
    writes a new one -- so the template is loaded the same way the toolkit loads
    it, which also keeps a test run from leaving a cache directory inside the
    shipped package data.
    """
    module = types.ModuleType(name)
    module.__file__ = str(path)
    exec(compile(path.read_text(encoding="utf-8"), str(path), "exec"), module.__dict__)
    return module


@pytest.fixture(scope="module")
def generator_module(template: Path):
    return load_module("custom_generator", template / "generator.py")


@pytest.fixture(scope="module")
def checker_module(template: Path):
    """The checker, loaded with a stub ``dmoj`` -- the host has no judge installed.

    The stub is the same shape ``test_solutions.py`` (the retired in-process
    sandbox) used, and it is deliberately *not* a mock of the checker's
    behaviour: it is only enough of ``dmoj`` for the module to import, so the
    code under test is the template's own.
    """
    import dataclasses

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

    return load_module("custom_checker", template / "checker.py")


#: The checker's own signature, as DMOJ calls it (``dmoj/graders/standard.py:57``).
def check(checker_module, output: str, *, n: int, model_out: str, point_value: float = 100.0, source=b""):
    return checker_module.check(
        process_output=output.encode(),
        judge_output=model_out.encode(),
        judge_input=f"{n}\n".encode(),
        point_value=point_value,
        submission_source=source,
    )


# ---------------------------------------------------------------------------
# The template is a complete problem
# ---------------------------------------------------------------------------


def test_template_ships_the_whole_problem(template: Path) -> None:
    for name in (
        "meta.yml",
        "generator.py",
        "solution.cpp",
        "checker.py",
        "submissions.yml",
        "media/statement.md",
    ):
        assert (template / name).is_file(), name
    assert (template / "submissions").glob("*.cpp")


def test_template_meta_yml_is_a_valid_custom_problem() -> None:
    authoring, resolved = meta_mod.load(templates.template_dir(MODEL))
    assert authoring["model"] == MODEL
    assert resolved.uses_checker
    # `custom` is a checker model, not a batched one: one batch that pays once.
    assert not resolved.is_batched
    assert not resolved.uses_signature
    # The checker and the batch axis are what distinguish `custom` from the
    # other checker models, so assert them as axes rather than by name.
    assert resolved.axes["checker"] == "custom"
    assert resolved.axes["batch"] == "single"


def test_template_meta_yml_header_matches_meta_HEADER(template: Path) -> None:
    """The template's header is the one users see, so it tracks ``meta.HEADER``."""
    assert (template / "meta.yml").read_text(encoding="utf-8").startswith(meta_mod.HEADER)


def test_template_declares_the_checker_as_a_plain_module_path(template: Path) -> None:
    """``checker: checker.py``, not ``custom_judge:``.

    The two are different mechanisms: ``checker:`` replaces only the comparison
    and leaves ``StandardGrader`` driving, while ``custom_judge:`` replaces the
    whole grader.  This model's entire claim is that it needs the first one, so
    the name of the key is part of the contract.
    """
    init = cases_mod.render_init(
        MODEL,
        meta_mod.resolve(meta_mod.load(template)[0]),
        cases_mod.read_subtasks(load_module("custom_gen_init", template / "generator.py").Generator(), "g"),
        [[0]],
        [cases_mod.CaseFile(index=0, has_input=True)],
    )
    assert "checker: checker.py" in init
    assert "custom_judge" not in init
    assert "signature_grader" not in init


# ---------------------------------------------------------------------------
# Generator protocol
# ---------------------------------------------------------------------------


def test_get_cases_returns_ordered_cases_with_the_required_methods(generator_module) -> None:
    cases = generator_module.Generator().get_cases()
    assert len(cases) >= 5
    for case in cases:
        assert callable(case.check)
        assert callable(case.write_file)


def test_generator_is_deterministic_per_seed(generator_module) -> None:
    first = generator_module.Generator().get_cases()
    second = generator_module.Generator().get_cases()
    assert [c.n for c in first] == [c.n for c in second]


def test_case_write_file_emits_the_declared_input_format(generator_module) -> None:
    case = generator_module.TestCase(6)
    buffer = io.StringIO()
    case.write_file(buffer)
    assert buffer.getvalue() == "6\n"


def test_case_check_enforces_the_statements_own_range(generator_module) -> None:
    """``check()`` carries the statement's restriction, which holds for every case."""
    with pytest.raises(AssertionError, match="fuera de rango"):
        generator_module.TestCase(0)
    with pytest.raises(AssertionError, match="fuera de rango"):
        generator_module.TestCase(generator_module.N_MAX + 1)


def test_the_problems_sizes_hold_the_partial_band_premise(generator_module) -> None:
    """``TAMANOS`` is asserted where the constant lives, not per case.

    ``submissions/suboptimo.cpp`` earns exactly ``0.7`` only because
    ``n/3 < n/2 <= 2*(n/3)``: with ``n`` a multiple of 3 and at least 6 that
    holds, and with ``n = 3`` it does not (the even-position construction is
    optimal there).  The assertion is on the constant, because ``gen_small``
    deliberately produces sizes that violate it -- those are the sizes where an
    index bug shows up.
    """
    assert generator_module.TAMANOS
    for n in generator_module.TAMANOS:
        assert n % 3 == 0 and n >= 6, n


def test_a_size_the_partial_band_does_not_hold_for_is_still_a_valid_case(generator_module) -> None:
    """``n = 3`` breaks the ``0.7`` premise but must remain constructible.

    Confusing the two is the trap this split avoids: the band's premise is a fact
    about the problem's chosen sizes, not about the problem's domain, so
    ``check()`` must not enforce it.
    """
    assert generator_module.TestCase(3).n == 3


def test_get_subtasks_is_the_single_batch_that_pays_everything(generator_module) -> None:
    subtasks = generator_module.Generator().get_subtasks()
    # `custom` is `batch: single`: a ladder here would be partial credit by
    # subtask, which is `batched-custom`'s model, not this one's.
    assert len(subtasks) == 1
    points, classifier = subtasks[0]
    assert points == 100
    assert callable(classifier)
    assert all(classifier(case) for case in generator_module.Generator().get_cases())


def test_gen_small_returns_cases_inside_a_small_range(generator_module) -> None:
    rand = random.Random(1234)
    for _ in range(50):
        (case,) = generator_module.Generator().gen_small(rand)
        assert 1 <= case.n <= 9


def test_gen_small_exercises_sizes_the_problem_itself_never_uses(generator_module) -> None:
    """The stress hook exists to leave the real cases' restrictions behind.

    ``TAMANOS`` are all multiples of 3 (so the declared partial fraction holds);
    the border sizes where an index bug shows up are exactly the ones excluded.
    """
    rand = random.Random(1234)
    sizes = {generator_module.Generator().gen_small(rand)[0].n for _ in range(200)}
    assert sizes - set(generator_module.TAMANOS)
    assert any(size % 3 for size in sizes)


# ---------------------------------------------------------------------------
# The model solution and the brute force
# ---------------------------------------------------------------------------


def _covers(checker_module, positions, n) -> bool:
    return checker_module.cubre(positions, n)


#: The C++ compilation the toolkit itself uses for `outputs`, reproduced here so
#: the model solution is checked as a *program* rather than as a transcribed
#: algorithm.  ``g++`` is on PATH everywhere the toolkit runs (the plan lists it
#: among the host toolchains), and a missing compiler is a skip rather than a
#: failure so this file stays green on a machine that only has Python.
def _cxx() -> str:
    compiler = shutil.which("g++")
    if compiler is None:
        pytest.skip("g++ is not installed; the model solution cannot be compiled")
    return compiler


def _compile(source: Path, output: Path) -> Path:
    """Compile ``source`` into ``output``, which lives in the test's own tmp dir.

    The binary goes to ``output`` rather than beside the source on purpose: the
    template directory is package data, and a test that leaves a compiled
    ``.testbin`` inside it would both pollute the shipped template and write into
    the repository from a test run.
    """
    result = subprocess.run(
        [_cxx(), "-O2", "-std=c++17", "-o", str(output), str(source)],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        pytest.fail(f"{source.name} does not compile:\n{result.stderr}")
    return output


def _run_model(binary: Path, n: int) -> list[int]:
    """The model solution's lamps for ``n``, from its own stdout."""
    result = subprocess.run([str(binary)], input=f"{n}\n", capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    tokens = result.stdout.split()
    assert tokens, f"no output for n={n}"
    declared = int(tokens[0])
    lamps = [int(token) for token in tokens[1:]]
    # The output format the statement declares: the count and the positions agree.
    assert len(lamps) == declared, f"n={n}: declared {declared}, printed {len(lamps)}"
    return lamps


def test_the_optimal_formula_is_ceil_n_over_3(checker_module) -> None:
    """The checker computes the optimum itself rather than reading it from the model."""
    assert [checker_module.optimo(n) for n in (1, 2, 3, 4, 5, 6, 7)] == [1, 1, 1, 2, 2, 2, 3]
    # The formula, not a table: it must hold past the sizes this problem uses.
    assert [checker_module.optimo(n) for n in (100, 101, 102)] == [34, 34, 34]


def test_the_model_solution_is_optimal_for_every_n_its_own_helper_covers(
    checker_module, tmp_path: Path
) -> None:
    """The C++ model solution is optimal for every ``n``, not just the problem's cases.

    The checker recomputes the optimum and refuses a model output that is not it,
    so this is the property ``problemsetting outputs`` depends on -- and the
    reason ``gen_small``'s sizes (which ``TAMANOS`` deliberately excludes) are
    safe.  The construction is re-derived here from the algorithm the C++ uses --
    greedy over the circle -- and checked against the checker's own ``optimo``
    and ``cubre``, so the test cannot disagree with the checker about either.

    This runs the *actual* ``solution.cpp`` through ``g++``: the previous
    toolkit's class of bug (a model solution that no longer compiles, or that
    drifts from the checker) is exactly what a re-implementation in Python would
    fail to catch.
    """
    template = templates.template_dir(MODEL)
    binary = _compile(template / "solution.cpp", tmp_path / "solution.testbin")

    def greedy(n: int) -> list[int]:
        """The C++'s construction, transcribed: a lamp next to the first dark spot."""
        covered = [False] * (n + 1)
        lamps: list[int] = []
        for first in range(1, n + 1):
            if covered[first]:
                continue
            lamp = first % n + 1
            lamps.append(lamp)
            for delta in (-1, 0, 1):
                covered[(lamp - 1 + delta + n) % n + 1] = True
        return lamps

    for n in range(1, 40):
        printed = _run_model(binary, n)
        assert printed == greedy(n), n
        assert len(printed) == checker_module.optimo(n), n
        assert _covers(checker_module, printed, n), n


def test_no_test_run_writes_into_the_template() -> None:
    """The template directory is package data; nothing here may write into it.

    Two mistakes this guards.  Compiling ``solution.cpp`` beside its source would
    leave a binary in the shipped template (and dirty the repository).  Loading
    an author file through ``importlib`` instead of compiling it from source --
    which ``cases.load_generator`` is explicit about avoiding -- would leave a
    ``__pycache__`` directory there.
    """
    template = templates.template_dir(MODEL)
    strays = sorted(
        path.name
        for path in template.iterdir()
        if path.name not in {"checker.py", "generator.py", "meta.yml", "solution.cpp",
                             "submissions.yml", "media", "submissions"}
    )
    assert strays == []


def test_partial_submission_is_valid_but_never_optimal(generator_module, checker_module) -> None:
    """The declared ``0.7`` is a property of the problem, not of one run.

    ``suboptimo.cpp`` puts a lamp on every even position: valid, but ``n/2``
    lamps against an optimum of ``ceil(n/3)``.  With ``n`` a multiple of 3 and
    ``n >= 6`` that is strictly more than the optimum and at most twice it, so
    the checker's partial branch is the one it always lands in.
    """
    optimum = checker_module.optimo
    for n in generator_module.TAMANOS:
        lamps = list(range(2, n + 1, 2))
        assert _covers(checker_module, lamps, n), n
        assert len(lamps) > optimum(n), n
        assert len(lamps) <= 2 * optimum(n), n


def test_invalid_submission_does_not_illuminate_the_circle(generator_module, checker_module) -> None:
    """``invalido.cpp``'s single lamp leaves positions dark at every real size."""
    for n in generator_module.TAMANOS:
        assert not _covers(checker_module, [1], n), n


# ---------------------------------------------------------------------------
# The checker: verdicts and fractional points
# ---------------------------------------------------------------------------


def test_optimal_output_earns_full_marks(checker_module) -> None:
    result = check(checker_module, "2\n2 5\n", n=6, model_out="2\n2 5\n")
    assert result.passed and result.points == 100.0


def test_valid_but_suboptimal_output_earns_partial_credit(checker_module) -> None:
    result = check(checker_module, "3\n2 4 6\n", n=6, model_out="2\n2 5\n")
    assert result.passed is True
    assert result.points == pytest.approx(0.7 * 100.0)


def test_a_valid_but_very_inefficient_output_earns_the_lower_band(checker_module) -> None:
    """The score is a function of quality, not an accept/reject switch."""
    result = check(checker_module, "5\n1 2 3 4 5\n", n=6, model_out="2\n2 5\n")
    assert result.passed is True
    assert result.points == pytest.approx(0.4 * 100.0)


def test_an_invalid_construction_earns_zero_despite_a_well_formed_output(checker_module) -> None:
    result = check(checker_module, "1\n1\n", n=6, model_out="2\n2 5\n")
    assert result.passed is False and result.points == 0.0


def test_partial_credit_scales_with_the_batchs_point_value(checker_module) -> None:
    """``point_value`` is the batch's, so a fraction composes with subtasks."""
    result = check(checker_module, "3\n2 4 6\n", n=6, model_out="2\n2 5\n", point_value=30.0)
    assert result.points == pytest.approx(0.7 * 30.0)


def test_the_partial_fraction_is_a_named_constant(checker_module) -> None:
    """The fraction the manifest documents is the checker's own constant.

    A literal ``0.7`` duplicated in the checker and the manifest is the drift
    ``submissions.yml`` exists to prevent, so the number has one home and the
    manifest quotes it.
    """
    assert checker_module.PUNTAJE_PARCIAL == 0.7
    assert checker_module.PUNTAJE_POBRE < checker_module.PUNTAJE_PARCIAL


# ---------------------------------------------------------------------------
# The checker validates the object, not the claimed score
# ---------------------------------------------------------------------------


def test_a_claimed_cost_that_does_not_match_the_object_is_not_rewarded(checker_module) -> None:
    """Lying about how many lamps were placed gets partial credit, never full.

    The output says ``2`` but carries three positions.  A checker that scored
    from the first line would pay full marks for having written a small number.
    """
    result = check(checker_module, "2\n2 4 6\n", n=6, model_out="2\n2 5\n")
    assert result.passed is True
    assert result.points == pytest.approx(0.7 * 100.0)
    assert "declara" in (result.feedback or "")


def test_the_optimal_score_needs_the_object_and_the_claim_to_agree(checker_module) -> None:
    """The mirror of the above: the right object with the wrong count is not full."""
    result = check(checker_module, "3\n2 5\n", n=6, model_out="2\n2 5\n")
    assert result.points < 100.0


def test_repeated_positions_do_not_count_towards_the_score(checker_module) -> None:
    """Two lamps at one position illuminate no more than one."""
    result = check(checker_module, "2\n2 2\n", n=6, model_out="2\n2 5\n")
    assert result.points == pytest.approx(0.7 * 100.0)
    assert "repetidas" in (result.feedback or "")


def test_positions_outside_the_circle_are_refused(checker_module) -> None:
    result = check(checker_module, "2\n2 99\n", n=6, model_out="2\n2 5\n")
    assert result.points == pytest.approx(0.7 * 100.0)
    assert "fuera de 1..6" in (result.feedback or "")


def test_an_empty_output_is_rejected_without_a_crash(checker_module) -> None:
    result = check(checker_module, "", n=6, model_out="2\n2 5\n")
    assert result.passed is False and result.points == 0.0


def test_a_first_line_that_is_not_a_number_is_rejected(checker_module) -> None:
    result = check(checker_module, "tantos\n", n=6, model_out="2\n2 5\n")
    assert result.passed is False and result.points == 0.0


def test_a_claim_of_zero_lamps_is_rejected(checker_module) -> None:
    result = check(checker_module, "0\n\n", n=6, model_out="2\n2 5\n")
    assert result.passed is False and result.points == 0.0


def test_a_claim_larger_than_the_circle_is_rejected(checker_module) -> None:
    result = check(checker_module, "99\n" + " ".join(["1"] * 99) + "\n", n=6, model_out="2\n2 5\n")
    assert result.passed is False and result.points == 0.0


# ---------------------------------------------------------------------------
# The checker never crashes on garbage
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "output",
    [
        "2\nx y\n",          # garbage tokens after a valid first line
        "2\n2 cinco\n",      # one good position and one word
        "2\n-1 -2\n",        # negative positions
        "2\n99999999999999999999 2\n",  # token too large for an int
        "2\n",               # a valid claim with no positions at all
        "2\n\n\n",
        "2\n\t\n",
        "\n",
        "   \n",
        "\x00\x01\x02\n",
    ],
)
def test_malformed_output_never_raises(checker_module, output: str) -> None:
    """A checker that raises is graded as an internal error: a broken problem.

    Every one of these must come back as a ``CheckerResult`` -- passed or not,
    full or partial -- and never as an exception.  That is the whole reason the
    submission's parse sits inside a ``try``.
    """
    result = check(checker_module, output, n=6, model_out="2\n2 5\n")
    assert result.passed in (True, False)
    assert 0.0 <= result.points <= 100.0


def test_garbage_after_a_valid_first_line_yields_deterministic_partial_credit(checker_module) -> None:
    """The documented behaviour: a valid first line is worth the partial floor.

    Deterministic is part of the contract -- the same input must always give the
    same score, so the grant cannot depend on parse order or randomness.
    """
    scores = {
        check(checker_module, "2\nx y\n", n=6, model_out="2\n2 5\n").points for _ in range(5)
    }
    assert len(scores) == 1 and scores.pop() == pytest.approx(0.7 * 100.0)


def test_malformed_input_data_is_an_error_not_a_partial_score(checker_module) -> None:
    """The asymmetry: the *problem's* input is ours, so a bad one is a real error.

    The submission is untrusted and tolerated; the problem's own artifacts are
    not, so a case whose input cannot be read surfaces instead of being priced.
    """
    with pytest.raises(ValueError, match="único entero"):
        checker_module.check(
            process_output=b"2\n2 5\n",
            judge_output=b"2\n2 5\n",
            judge_input=b"6 7 8\n",
            point_value=100.0,
            submission_source=b"",
        )


def test_a_non_optimal_model_output_is_an_error_not_a_partial_score(checker_module) -> None:
    """Our ``.out`` is generated from the model solution, so it must be optimal."""
    with pytest.raises(ValueError, match="óptimo"):
        check(checker_module, "2\n2 5\n", n=6, model_out="1\n1\n")


# ---------------------------------------------------------------------------
# The codegolf recipe
# ---------------------------------------------------------------------------


def test_the_codegolf_recipe_is_documented_in_the_checker(template: Path) -> None:
    """The recipe is a recipe: documented here, not shipped as a ninth model.

    Decision Q27 puts codegolf inside ``custom`` because it needs no machinery
    ``custom`` lacks -- ``submission_source`` is already passed to ``check()``.
    """
    source = (template / "checker.py").read_text(encoding="utf-8")
    assert "codegolf" in source
    assert "submission_source" in source
    assert "len(submission_source)" in source
    # The byte-vs-character trap, which is the one thing a reader would get wrong.
    assert "utf8text(submission_source)" in source
    # And the honest note about what would have to change.
    assert "custom_judge" in source
    assert "LIMITE" in source


def test_the_template_is_not_registered_as_a_ninth_model() -> None:
    """Codegolf is a recipe inside ``custom``; the model list must not grow."""
    assert "codegolf" not in meta_mod.MODELS
    assert "custom" in meta_mod.MODELS
    assert len(meta_mod.MODELS) == 8


def test_a_codegolf_style_score_is_a_function_of_the_source_length(checker_module, template: Path) -> None:
    """The recipe's mechanism is exercised, so the documentation is not a lie.

    A codegolf checker's shape is "correct first, then length", and the length of
    ``submission_source`` is available at the checker's own call site.  This
    builds a throwaway checker in the recipe's image and drives it, which is the
    only way to show the documented recipe actually works with the arguments the
    judge passes.
    """
    # Reuse the template's own helpers rather than re-implementing the problem,
    # and the stubbed `CheckerResult` the checker itself was loaded against.
    import dmoj.result as dmoj_result

    limite = 512

    def codegolf(process_output, judge_output, judge_input, point_value, submission_source, **kwargs):
        if not checker_module.cubre(
            [int(t) for t in process_output.decode().split()[1:]], int(judge_input.decode())
        ):
            return dmoj_result.CheckerResult(False, 0.0, feedback="no resuelve el problema")
        byte_count = len(submission_source)
        if byte_count >= limite:
            return dmoj_result.CheckerResult(True, 0.0, feedback=f"{byte_count} bytes")
        return dmoj_result.CheckerResult(True, point_value * (limite - byte_count) / limite)

    optimal = "2\n2 5\n".encode()
    args = dict(
        process_output=optimal,
        judge_output=b"2\n2 5\n",
        judge_input=b"6\n",
        point_value=100.0,
    )
    short = codegolf(submission_source=b"x" * 100, **args)
    long = codegolf(submission_source=b"x" * limite, **args)
    wrong = codegolf(submission_source=b"x" * 100, **{**args, "process_output": b"1\n1\n"})
    assert short.points > long.points == 0.0
    assert wrong.passed is False and wrong.points == 0.0


def test_the_recipe_counts_bytes_not_characters(checker_module) -> None:
    """``submission_source`` arrives as bytes, so ``len()`` is the byte count.

    This is asserted against the real value rather than by reading the docs: a
    checker that did ``len(utf8text(...))`` would under-count any source with a
    non-ASCII identifier, and the recipe would be wrong in a way that only shows
    up for some submissions.
    """
    source = "// faro\n".encode() + "int ñ = 1;\n".encode()
    assert isinstance(source, bytes)
    import dmoj.utils.unicode as dmoj_unicode

    assert len(source) > len(dmoj_unicode.utf8text(source))


# ---------------------------------------------------------------------------
# The manifest
# ---------------------------------------------------------------------------


def test_the_template_manifest_matches_the_schema_verify_reads(template: Path) -> None:
    """The shipped manifest must parse, and must declare every kind of subject.

    Read through ``verify.load_manifest`` rather than by loading the YAML here:
    the point is that the file the template ships is accepted by the code that
    consumes it.
    """
    from problemsetting import verify

    _, resolved = meta_mod.load(template)
    entries = verify.load_manifest(template, resolved)
    assert [entry.source.as_posix() for entry in entries] == [
        "solution.cpp",
        "submissions/suboptimo.cpp",
        "submissions/invalido.cpp",
        "submissions/malformado.cpp",
        "submissions/fuerza-bruta.cpp",
    ]
    assert [entry.role for entry in entries] == ["model", None, None, "checker-test", "brute"]
    assert all(entry.declares_expectation for entry in entries)


def test_the_manifest_declares_the_four_subjects_the_ticket_requires(template: Path) -> None:
    """Full marks, a partial band, a zero and a rejected-garbage subject."""
    from problemsetting import verify

    _, resolved = meta_mod.load(template)
    by_role = {entry.role: entry for entry in verify.load_manifest(template, resolved) if entry.role}
    assert by_role["model"].verdict == "AC" and by_role["model"].score == 100
    assert by_role["brute"].verdict == "AC"
    assert by_role["checker-test"].verdict == "WA"

    partial = [e for e in verify.load_manifest(template, resolved) if e.source.name == "suboptimo.cpp"]
    assert len(partial) == 1


def test_the_partial_submission_is_not_declared_as_the_checker_test(template: Path) -> None:
    """``role: checker-test`` means "the checker must reject this".

    The partial submission is *accepted* with a fraction, so mislabelling it
    would make check 5 read it as a missing rejection.
    """
    from problemsetting import verify

    _, resolved = meta_mod.load(template)
    entries = {e.source.name: e for e in verify.load_manifest(template, resolved)}
    assert entries["suboptimo.cpp"].role is None
    assert entries["malformado.cpp"].role == "checker-test"


def test_the_manifest_explains_why_the_partial_score_is_what_it_is(template: Path) -> None:
    """The declared ``score`` and the site's ``0.7`` differ; the file must say why.

    This is the measurement gap, not a bug: DMOJ's console transcript carries no
    per-case points, so ``verify`` cannot observe the fraction yet.  An
    undocumented mismatch here is exactly the silent drift ``verify`` exists to
    prevent, so the explanation is part of the deliverable.
    """
    text = (template / "submissions.yml").read_text(encoding="utf-8")
    assert "0.7" in text
    assert "_ipc_result" in text
    assert "verify" in text


# ---------------------------------------------------------------------------
# The problem is buildable (the real generator, no CLI)
# ---------------------------------------------------------------------------


def test_the_shipped_template_renders_init_yml_with_the_checker(tmp_path: Path) -> None:
    """Runs the real emission against the shipped template, no CLI needed."""
    import shutil

    destination = tmp_path / MODEL
    shutil.copytree(
        templates.template_dir(MODEL),
        destination,
        ignore=shutil.ignore_patterns(*templates.TEMPLATE_IGNORE),
    )
    authoring, resolved = meta_mod.load(destination)
    generator = cases_mod.load_generator(destination)
    source = str(destination / cases_mod.GENERATOR_FILENAME)
    cases = cases_mod.read_cases(generator, source)
    subtasks = cases_mod.read_subtasks(generator, source)
    membership = cases_mod.classify(subtasks, cases, source)
    files, _ = cases_mod.write_case_files(destination, cases, has_input=True, source=source)
    init = cases_mod.render_init(MODEL, resolved, subtasks, membership, files)

    assert "checker: checker.py" in init
    assert "test_cases:" in init
    # One batch, worth everything: `custom` pays partial credit through the
    # checker, not through a ladder of subtasks.
    assert init.count("- points:") == 1
    assert "- points: 100" in init


# ---------------------------------------------------------------------------
# The CLI scaffolds it (acceptance criterion 1)
# ---------------------------------------------------------------------------


def test_new_scaffolds_a_custom_problem(tmp_path: Path, monkeypatch) -> None:
    """``new --model custom`` produces a problem the toolkit recognises."""
    monkeypatch.chdir(tmp_path)
    assert cli.main(["new", "--model", MODEL, "faros-demo"]) == 0

    problem = tmp_path / "faros-demo"
    assert (problem / "checker.py").is_file()
    assert (problem / "submissions.yml").is_file()
    _, resolved = meta_mod.load(problem)
    assert resolved.model == MODEL
    assert resolved.uses_checker


def test_custom_is_shipped() -> None:
    """``templates.shipped()`` discovers templates by directory presence."""
    assert MODEL in templates.shipped()


def test_cases_rejects_a_ladder_of_subtasks_in_a_single_batch_model(tmp_path: Path, monkeypatch) -> None:
    """The guard that keeps `custom` from silently becoming partial-by-subtask.

    A generator with several subtasks would produce valid YAML with several
    sibling batches, and the scoring would no longer be what the model says.
    """
    from problemsetting import meta as meta_mod_local

    problem = tmp_path / "ladder"
    problem.mkdir()
    meta_mod_local.write(problem, meta_mod_local.normalize({"model": MODEL, "solutionlang": ".cpp"}))
    (problem / cases_mod.GENERATOR_FILENAME).write_text(
        textwrap.dedent(
            """
            class TestCase:
                def __init__(self, v):
                    self.v = v

                def write_file(self, f):
                    f.write(f"{self.v}\\n")

            class Generator:
                def __init__(self, seed=0):
                    pass

                def get_cases(self):
                    return [TestCase(6)]

                def get_subtasks(self):
                    return [(30, lambda c: True), (70, lambda c: True)]
            """
        )
    )
    monkeypatch.chdir(tmp_path)
    assert cli.main(["cases", "ladder"]) == 1


def test_a_single_batch_model_without_a_checker_file_is_refused(tmp_path: Path, monkeypatch) -> None:
    """``init.yml`` will name ``checker.py``, so its absence is an authoring error."""
    problem = tmp_path / "noc"
    problem.mkdir()
    meta_mod.write(problem, meta_mod.normalize({"model": MODEL, "solutionlang": ".cpp"}))
    (problem / cases_mod.GENERATOR_FILENAME).write_text(
        textwrap.dedent(
            """
            class TestCase:
                def __init__(self, v):
                    self.v = v

                def write_file(self, f):
                    f.write(f"{self.v}\\n")

            class Generator:
                def __init__(self, seed=0):
                    pass

                def get_cases(self):
                    return [TestCase(6)]

                def get_subtasks(self):
                    return [(100, lambda c: True)]
            """
        )
    )
    monkeypatch.chdir(tmp_path)
    assert cli.main(["cases", "noc"]) == 1

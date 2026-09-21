"""The ``output-only-custom`` template: a text submission that a checker *scores*.

The model is the crossing of two axes the toolkit already had separately:
``submission: text`` (as in ``output-only``) and ``checker: custom`` (as in
``custom``).  Neither is invented here -- what this model adds is the combination,
and with it a consequence that neither of the others has on its own:

* ``output-only`` has no checker, so it compares for equality;
* ``custom`` has a checker, but has input, so its checker reads the instance from
  ``judge_input``;
* ``output-only-custom`` has a checker and **no** input: ``judge_input`` arrives
  empty, so the problem's target is a *constant of the problem* and there can be
  only one case.

So these tests defend the three things that fall out of that:

* the model resolves to ``submission: text`` **and** ``checker: custom`` → ``.txt``
  → ``TEXT``, with ``init.yml`` declaring ``checker: checker.py`` and cases with
  only ``out:``;
* the checker returns *fractional* ``CheckerResult`` points -- full, partial and
  zero are three distinguishable outcomes, driven through the real ``check()``
  signature against a stub ``dmoj``;
* the checker never raises on garbage, because a checker that raises is graded as
  an internal error, i.e. a broken problem rather than a rejected submission.

The end-to-end run (``new`` → ``build`` → ``verify`` against a real judge
container) is exercised by hand in the ticket's report; the tests here cover
everything that does not need the 15 GB image.
"""

from __future__ import annotations

import dataclasses
import shutil
import sys
import types
from pathlib import Path

import pytest
import support
import yaml

from problemsetting import cases as cases_mod
from problemsetting import cli
from problemsetting import meta as meta_mod
from problemsetting import outputs as outputs_mod
from problemsetting import templates
from problemsetting import verify

MODEL = "output-only-custom"

#: The target of the shipped problem, and the minimum number of Fibonacci
#: summands that represent it.  Both are properties of the problem, pinned here
#: so a test that disagrees with the template fails loudly.
OBJETIVO = 100000
MINIMO = 9
TOPE = 20

#: The shipped answer: Zeckendorf's representation of 100000.
ANSWER = "9\n75025 17711 6765 377 89 21 8 3 1\n"


@pytest.fixture(scope="module")
def template() -> Path:
    return templates.template_dir(MODEL)


@pytest.fixture(scope="module")
def generator_module(template: Path):
    return support.load_module(template / "generator.py", "ooc_generator")


@pytest.fixture(scope="module")
def checker_module(template: Path):
    """The checker, loaded with a stub ``dmoj`` -- the host has no judge installed.

    The stub is only enough of ``dmoj`` for the module to import, so the code
    under test is the template's own and not a mock of its behaviour.
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

    return support.load_module(template / "checker.py", "ooc_checker")


#: The checker's own signature, as DMOJ calls it (``dmoj/graders/standard.py:60``).
#:
#: ``judge_input`` is empty on purpose: this model has no inputs, so the judge
#: hands the checker a sealed empty stdin -- and the checker must not read the
#: target from anywhere but its own constant.
def check(checker_module, output, *, model_out=ANSWER, point_value=100.0, judge_input=b""):
    return checker_module.check(
        process_output=output.encode(),
        judge_output=model_out.encode(),
        judge_input=judge_input,
        point_value=point_value,
        submission_source=b"",
    )


def run(argv: list[str], monkeypatch, cwd: Path) -> int:
    monkeypatch.chdir(cwd)
    return cli.main(argv)


def scaffold(tmp_path: Path, monkeypatch, name: str = "fibsum") -> Path:
    """``problemsetting new --model output-only-custom <name>`` into a scratch directory."""
    assert run(["new", "--model", MODEL, name], monkeypatch, tmp_path) == 0
    return tmp_path / name


# ---------------------------------------------------------------------------
# The template is a complete problem
# ---------------------------------------------------------------------------


def test_template_ships_the_whole_problem(template: Path) -> None:
    for name in (
        "meta.yml",
        "generator.py",
        "checker.py",
        "solution.txt",
        "submissions.yml",
        "media/statement.md",
        "submissions/parcial.txt",
        "submissions/no-representa.txt",
        "submissions/malformado.txt",
    ):
        assert (template / name).is_file(), name


def test_the_two_text_models_are_distinct_and_both_reachable() -> None:
    """Sharing the machinery is not sharing the model.

    Both text models run on the same axes -- ``submission: text`` and its
    ``TEXT``/``.txt`` mapping -- and the toolkit implements that once, keyed by
    the resolved axis rather than by the model's name.  What must stay distinct is
    the *preset*: an author asking for one must not get the other, and their
    checkers differ in whether one exists at all.
    """
    assert meta_mod.MODELS["output-only"]["checker"] == "none"
    assert meta_mod.MODELS[MODEL]["checker"] == "custom"
    # Everything else is identical, which is exactly why sharing was possible.
    for axis in ("grader", "batch", "io", "submission"):
        assert meta_mod.MODELS["output-only"][axis] == meta_mod.MODELS[MODEL][axis]
    assert templates.template_dir("output-only") != templates.template_dir(MODEL)
    # The two templates are different problems, not copies of one.
    assert (templates.template_dir(MODEL) / "checker.py").is_file()
    assert not (templates.template_dir("output-only") / "checker.py").exists()


def test_template_meta_yml_resolves_to_text_plus_a_checker() -> None:
    authoring, resolved = meta_mod.load(templates.template_dir(MODEL))
    assert authoring["model"] == MODEL
    assert authoring["solutionlang"] == ".txt"
    assert resolved.executor == "TEXT"
    assert resolved.is_output_only
    assert resolved.uses_checker
    assert not resolved.is_batched and not resolved.uses_signature
    # Asserted as axes, not by name: the axes are what the toolkit acts on.
    assert resolved.axes["checker"] == "custom"
    assert resolved.axes["submission"] == "text"


def test_template_comment_header_matches_the_generator_of_meta_yml(template: Path) -> None:
    """The template's header is the one users see, so it tracks ``meta.HEADER``."""
    assert (template / "meta.yml").read_text().startswith(meta_mod.HEADER), (
        "the output-only-custom template's meta.yml comment block has drifted from "
        "problemsetting.meta.HEADER"
    )


def test_txt_maps_to_the_text_executor_and_is_the_only_extension_allowed() -> None:
    assert meta_mod.EXECUTOR_BY_EXT[".txt"] == "TEXT"
    assert meta_mod.FAMILY_BY_EXT[".txt"] == "text"
    assert meta_mod.allowed_extensions(meta_mod.MODELS[MODEL]) == (".txt",)
    assert meta_mod.EXECUTOR_FAMILY["TEXT"] == "text"


def test_verify_infers_text_for_every_txt_submission(template: Path) -> None:
    _, resolved = meta_mod.load(template)
    entries = verify.load_manifest(template, resolved)
    assert all(entry.source.suffix == ".txt" for entry in entries)
    assert {entry.executor for entry in entries} == {"TEXT"}


def test_cases_emits_out_only_cases_and_declares_the_checker(template: Path, tmp_path: Path) -> None:
    """``checker:`` in ``init.yml`` and no ``in:`` in any case -- both observed."""
    problem = tmp_path / "fibsum"
    shutil.copytree(template, problem)
    generator = cases_mod.load_generator(problem)
    subtasks = cases_mod.read_subtasks(generator, "generator.py")
    _, resolved = meta_mod.load(problem)
    init = cases_mod.render_init(
        problem.name,
        resolved,
        subtasks,
        cases_mod.classify(subtasks, cases_mod.read_cases(generator, "generator.py"), "generator.py"),
        [cases_mod.CaseFile(index=0, has_input=False)],
    )
    document = yaml.safe_load(init)
    assert document["checker"] == "checker.py"
    assert "custom_judge" not in init
    assert "signature_grader" not in init
    entries = [entry for batch in document["test_cases"] for entry in batch["batched"]]
    assert entries == [{"out": "cases/0.out"}]
    assert all("in" not in entry for entry in entries)
    # One batch worth everything: this model's partial credit comes from the
    # checker, not from a ladder of subtasks.
    assert [batch["points"] for batch in document["test_cases"]] == [100]


# ---------------------------------------------------------------------------
# Generator protocol
# ---------------------------------------------------------------------------


def test_get_cases_returns_one_case_with_the_required_methods(generator_module) -> None:
    cases = generator_module.Generator().get_cases()
    assert len(cases) == 1
    case = cases[0]
    assert callable(case.check) and callable(case.write_file)


def test_generator_is_deterministic_per_seed(generator_module) -> None:
    first = generator_module.Generator().get_cases()
    second = generator_module.Generator(seed=99).get_cases()
    assert [case.answer for case in first] == [case.answer for case in second]


def test_write_file_refuses_because_these_cases_have_no_input(generator_module) -> None:
    """An output-only case must not silently write an empty input either.

    ``init.yml`` declares no ``in:``, so the toolkit never calls ``write_file``;
    if something did, an empty file would be a different problem from "this case
    has no input", and the test pins the loud refusal instead.
    """
    case = generator_module.Generator().get_cases()[0]
    with pytest.raises(AssertionError, match="no tienen input"):
        case.write_file(None)


def test_get_subtasks_yields_a_single_checked_batch(generator_module) -> None:
    subtasks = generator_module.Generator().get_subtasks()
    assert len(subtasks) == 1
    points, classify = subtasks[0]
    assert points == 100
    assert classify(generator_module.TestCase(ANSWER))


def test_case_check_accepts_the_shipped_answer_and_refuses_a_broken_one(
    generator_module,
) -> None:
    """The build-time ``check()`` and the judge-time checker must agree.

    ``TestCase.check()`` runs during ``problemsetting cases`` and ``checker.check()``
    runs inside the judge; they are separate implementations in separate files.  A
    template whose own answer fails its own checker would publish an unsolvable
    problem, so the generator validates the same structure the checker enforces.
    """
    assert generator_module.TestCase(ANSWER).answer == ANSWER
    # Each broken answer must be refused, and the assertion must hold for the
    # message the code actually raises.  Matching one shared regex across all
    # four was wrong: the sum-mismatch case says "los sumandos suman 71343, no
    # 100000" and the count case says "la respuesta declara 9 sumandos y trae
    # 10", so a single /respuesta|Fibonacci/ pattern would accept a *wrong*
    # refusal.  Pinning the expected message keyword per case keeps the test
    # honest about which invariant caught which answer.
    broken = {
        "no llega al objetivo": ("9\n46368 17711 6765 377 89 21 8 3 1\n", "suman"),
        "la cantidad no coincide": (
            "9\n75025 17711 6765 377 89 21 8 3 1 1\n",
            "declara",
        ),
        "se pasa del tope": ("21\n" + " ".join(["1"] * 21) + "\n", "sumandos"),
        "no es de Fibonacci": ("2\n4 99996\n", "Fibonacci"),
    }
    for label, (answer, expected) in broken.items():
        with pytest.raises((AssertionError, ValueError), match=expected):
            generator_module.TestCase(answer)


def test_case_check_refuses_a_valid_but_not_minimal_answer(generator_module) -> None:
    """The build must catch what the judge cannot report.

    ``solution.txt`` is copied verbatim to ``cases/0.out``, and the checker demands
    a *minimal* model output -- so a valid-but-not-minimal solution builds cleanly
    and then makes every submission ungraded, because the ``ValueError`` is
    swallowed inside the judge and the author sees "not run" rather than an error.
    The shipped ``output-only`` template avoids this by deriving its answer from
    its generator; here the check is what closes the gap.  The case pinned is the
    one a plausible edit produces: split the largest summand, keep the sum.
    """
    parcial = "10\n46368 28657 17711 6765 377 89 21 8 3 1\n"
    assert sum(int(t) for t in parcial.split()[1:]) == OBJETIVO  # valid, not minimal
    with pytest.raises(AssertionError, match="el mínimo"):
        generator_module.TestCase(parcial)


def test_the_generator_has_no_stress_hook(generator_module) -> None:
    """``stress`` needs two programs; a text submission gives it none."""
    assert not hasattr(generator_module.Generator(), "gen_small")


def test_stress_cuts_this_model_off_with_the_reason_not_the_missing_hook(
    tmp_path, monkeypatch, capsys
) -> None:
    """Which skip ``stress`` reports, observed rather than assumed.

    ``run_stress`` returns on ``is_output_only`` *before* it looks for
    ``gen_small``, so the reason a reader of the generator might expect -- "no
    tiny-case hook" -- is not the one this model gets.  Note that this is the
    ``is_output_only`` cut-off and not a checker-related one: having a checker
    does not give ``stress`` anything to compare either.
    """
    scaffold(tmp_path, monkeypatch)
    assert run(["stress", "fibsum"], monkeypatch, tmp_path) == 0
    out = capsys.readouterr().out
    assert "grades a text file rather than a program" in out
    assert "gen_small" not in out


# ---------------------------------------------------------------------------
# The shipped answer and its optimality
# ---------------------------------------------------------------------------


def _fibonacci_hasta(limite: int) -> list[int]:
    numeros, anterior, actual = [], 1, 2
    while anterior <= limite:
        numeros.append(anterior)
        anterior, actual = actual, anterior + actual
    return numeros


def _tabla_optimos(objetivo: int) -> list[int]:
    """``tabla[s]`` = minimum summand count for every ``s <= objetivo``, by DP.

    A *different* method from the generator's greedy, so the two agreeing is
    evidence and not a tautology.  Kept as a table because two tests need it --
    one for the shipped target, one to walk every target below it.
    """
    tabla = [0] + [objetivo + 1] * objetivo
    for numero in _fibonacci_hasta(objetivo):
        for suma in range(numero, objetivo + 1):
            tabla[suma] = min(tabla[suma], tabla[suma - numero] + 1)
    return tabla


def test_the_shipped_answer_is_a_minimal_representation_of_the_target(generator_module) -> None:
    assert generator_module.OBJETIVO == OBJETIVO
    assert generator_module.RESPUESTA == ANSWER

    sumandos = [int(token) for token in ANSWER.split()[1:]]
    numeros = set(_fibonacci_hasta(OBJETIVO))
    assert sum(sumandos) == OBJETIVO
    assert all(sumando in numeros for sumando in sumandos)
    assert len(sumandos) == MINIMO == _tabla_optimos(OBJETIVO)[OBJETIVO]


def _representar_con_al_menos(objetivo: int, maximo: int) -> list[int]:
    """A representation of ``objetivo`` inflated until it uses exactly ``maximo`` summands.

    Splitting one summand ``F(m)`` into ``F(m-1) + F(m-2)`` keeps the sum and adds
    exactly one summand, so repeating it walks from the minimum up to any larger
    count.  Used to build the boundary case the checker's cap is about.
    """
    sumandos = [int(token) for token in ANSWER.split()[1:]]
    while len(sumandos) < maximo:
        sumandos.sort(reverse=True)
        mayor = sumandos.pop(0)
        anterior, actual = 1, 2
        while anterior + actual < mayor:
            anterior, actual = actual, anterior + actual
        assert anterior + actual == mayor, f"{mayor} no es un Fibonacci partible"
        sumandos += [anterior, actual]
    assert sum(sumandos) == objetivo
    assert all(sumando in set(_fibonacci_hasta(objetivo)) for sumando in sumandos)
    return sumandos


def test_the_greedy_answer_really_is_minimal_over_every_smaller_target(generator_module) -> None:
    """Zeckendorf's theorem, exercised rather than quoted.

    The generator's answer comes from the greedy algorithm; the checker scores
    against a DP.  They agree at the shipped target, and this asserts they agree
    at *every* target up to it -- otherwise the template would be teaching a
    method that only happens to work once.
    """
    fibs = _fibonacci_hasta(OBJETIVO)
    tabla = _tabla_optimos(OBJETIVO)
    for objetivo in range(1, OBJETIVO + 1):
        greedy = generator_module.zeckendorf(objetivo, fibs)
        assert sum(greedy) == objetivo, objetivo
        assert len(greedy) == tabla[objetivo], objetivo


def test_solution_txt_is_the_generators_answer(template: Path, generator_module) -> None:
    """``outputs`` copies the file without checking it, so the two must agree."""
    assert (template / "solution.txt").read_text() == generator_module.RESPUESTA


def test_the_generator_and_the_checker_agree_on_the_target_and_the_cap(
    template: Path, generator_module, checker_module
) -> None:
    """The target and the cap live in two files that never see each other.

    ``generator.py`` runs during the build; ``checker.py`` runs inside the judge.
    Nothing in the toolkit can tie them together, so this test does -- a
    template whose checker scored a different number than the one the generator
    emitted would publish an unsolvable problem.
    """
    assert checker_module.OBJETIVO == generator_module.OBJETIVO
    assert checker_module.TOPE == generator_module.TOPE


# ---------------------------------------------------------------------------
# outputs: a file copy, with no compiler and no program run
# ---------------------------------------------------------------------------


def test_outputs_copies_the_text_instead_of_running_anything(
    tmp_path, monkeypatch, capsys
) -> None:
    """The decisive test: nothing that could run or build is reachable.

    The checker is a file the judge loads, never something the toolkit executes,
    so the copy path must not have grown a way to run it either.
    """
    problem = scaffold(tmp_path, monkeypatch)

    def explode(*args, **kwargs):  # pragma: no cover - only reached on a regression
        raise AssertionError("output-only-custom must not compile or run anything")

    monkeypatch.setattr(outputs_mod, "resolve_tools", explode)
    monkeypatch.setattr(outputs_mod, "run_tool", explode)
    monkeypatch.setattr(outputs_mod, "run_case", explode)

    assert run(["cases", "fibsum"], monkeypatch, tmp_path) == 0
    assert run(["outputs", "fibsum"], monkeypatch, tmp_path) == 0
    assert "copying the model solution" in capsys.readouterr().out

    assert (problem / "cases" / "0.out").read_bytes() == (problem / "solution.txt").read_bytes()
    assert (problem / "cases" / "0.out").read_text() == ANSWER
    assert not list(problem.glob("__meta__/solution*"))


def test_a_re_edited_solution_is_re_copied(tmp_path, monkeypatch) -> None:
    """The copy must never go stale, because the checker grades against it."""
    problem = scaffold(tmp_path, monkeypatch)
    assert run(["cases", "fibsum"], monkeypatch, tmp_path) == 0
    assert run(["outputs", "fibsum"], monkeypatch, tmp_path) == 0
    assert (problem / "cases" / "0.out").read_text() == ANSWER

    (problem / "solution.txt").write_text("10\n46368 28657 17711 6765 377 89 21 8 3 1\n")
    assert run(["outputs", "fibsum"], monkeypatch, tmp_path) == 0
    assert (problem / "cases" / "0.out").read_text().startswith("10\n")


def test_build_produces_the_case_the_archive_and_the_checker(tmp_path, monkeypatch) -> None:
    problem = scaffold(tmp_path, monkeypatch)
    assert run(["build", "fibsum"], monkeypatch, tmp_path) == 0
    assert (problem / "cases" / "0.out").read_text() == ANSWER
    assert (problem / "fibsum.zip").is_file()
    assert (problem / cases_mod.INIT_FILENAME).is_file()
    assert not list(problem.glob("cases/*.in"))
    assert run(["archive", "fibsum"], monkeypatch, tmp_path) == 0


def test_a_missing_checker_file_is_refused_by_the_build(tmp_path, monkeypatch, capsys) -> None:
    """``init.yml`` will name ``checker.py``, so its absence is an authoring error."""
    problem = scaffold(tmp_path, monkeypatch)
    (problem / cases_mod.CHECKER_FILENAME).unlink()
    assert run(["cases", "fibsum"], monkeypatch, tmp_path) == 1
    assert "checker.py" in capsys.readouterr().err


def test_a_dot_prefixed_name_is_refused_so_a_problem_can_never_be_unreachable(
    tmp_path, monkeypatch, capsys
) -> None:
    """The pool discovers problems with ``glob``, which skips leading-dot paths."""
    for name in (".fibsum", ".", ".."):
        assert run(["new", "--model", MODEL, name], monkeypatch, tmp_path) == 1
        assert capsys.readouterr().err.startswith("error: ")
    assert not list(tmp_path.iterdir())


# ---------------------------------------------------------------------------
# The checker: three distinguishable score levels
# ---------------------------------------------------------------------------


def test_the_minimal_representation_earns_full_marks(checker_module) -> None:
    result = check(checker_module, ANSWER)
    assert result.passed is True
    assert result.points == 100.0


def test_a_valid_but_not_minimal_representation_earns_partial_credit(checker_module) -> None:
    """The whole point of the model: a different score for a worse answer."""
    result = check(checker_module, "10\n46368 28657 17711 6765 377 89 21 8 3 1\n")
    assert result.passed is True
    assert result.points == pytest.approx(0.7 * 100.0)
    assert "no mínima" in (result.feedback or "")


def test_partial_credit_scales_with_the_batchs_point_value(checker_module) -> None:
    """``point_value`` is the batch's, so a fraction composes with subtasks."""
    result = check(
        checker_module,
        "10\n46368 28657 17711 6765 377 89 21 8 3 1\n",
        point_value=30.0,
    )
    assert result.points == pytest.approx(0.7 * 30.0)


def test_the_partial_fraction_is_a_named_constant(checker_module) -> None:
    """The fraction the manifest documents is the checker's own constant."""
    assert checker_module.PUNTAJE_PARCIAL == 0.7


def test_summands_that_do_not_reach_the_target_earn_zero(checker_module, template: Path) -> None:
    """A well-formed answer whose *object* is wrong scores 0, not partial.

    This is the distinction the model exists to show: the score measures the
    construction, not having got the format right.  Driven through the shipped
    file, so the manifest's ``verdict: WA, score: 0`` is asserted against the
    checker rather than against a literal a reader has to compare by eye.
    """
    output = (template / "submissions" / "no-representa.txt").read_text()
    result = check(checker_module, output)
    assert result.passed is False
    assert result.points == 0.0
    assert "71343" in (result.feedback or "")


def test_a_summand_that_is_not_fibonacci_earns_zero(checker_module) -> None:
    """``4`` is not a Fibonacci number, so the answer is not a representation.

    The declaration is well formed (``2`` for two summands), but format does not
    pay here: an invalid object scores 0.  This is the ban on the ``custom``
    template's "partial floor" -- see ``checker.check``'s docstring for why this
    model drops it.
    """
    result = check(checker_module, "2\n4 99996\n")
    assert result.passed is False
    assert result.points == 0.0
    assert "Fibonacci" in (result.feedback or "")


def test_a_claimed_count_that_disagrees_with_the_body_earns_zero(checker_module) -> None:
    """Lying about how many summands were sent is a self-contradiction, not an answer."""
    result = check(checker_module, "9\n75025 17711 6765 377 89 21 8 3 1 1\n")
    assert result.passed is False
    assert result.points == 0.0
    assert "declara 9" in (result.feedback or "")


def test_a_bare_declaration_with_no_summands_earns_zero(checker_module) -> None:
    """The decisive case against a partial floor.

    A ``.txt`` holding just ``9`` costs nothing to write -- there is no input to
    understand -- so paying it 70% would hand out most of the problem for free.
    The published scoring table calls this "mal formada" and 0.
    """
    for output in ("9\n", "9", "9\n\n", "  9  \n"):
        result = check(checker_module, output)
        assert result.passed is False and result.points == 0.0, output


def test_a_body_that_is_not_numbers_earns_zero(checker_module) -> None:
    """Garbage after a valid first line is malformed, not a partial answer."""
    for output in ("9\nx y z\n", "9\n75025 x\n"):
        result = check(checker_module, output)
        assert result.passed is False and result.points == 0.0, output


def test_an_empty_output_is_rejected_without_a_crash(checker_module) -> None:
    result = check(checker_module, "")
    assert result.passed is False and result.points == 0.0


def test_a_first_line_that_is_not_a_number_is_rejected(checker_module) -> None:
    result = check(checker_module, "no soy una lista de numeros\n")
    assert result.passed is False and result.points == 0.0


def test_a_claim_below_one_or_above_the_cap_is_rejected(checker_module) -> None:
    for output in ("0\n", f"{TOPE + 1}\n" + " ".join(["1"] * (TOPE + 1)) + "\n"):
        result = check(checker_module, output)
        assert result.passed is False and result.points == 0.0, output


def test_exactly_the_cap_is_accepted_but_is_not_full_marks(checker_module) -> None:
    """The cap is a bound, not an exclusive one: 20 summands is admitted.

    An admitted non-minimal answer earns partial credit and not a rejection --
    which is the boundary the ``1 <= K <= TOPE`` test above has to leave open.
    """
    sumandos = _representar_con_al_menos(OBJETIVO, TOPE)
    assert len(sumandos) == TOPE, sumandos
    result = check(checker_module, f"{len(sumandos)}\n" + " ".join(map(str, sumandos)) + "\n")
    assert result.passed is True
    assert result.points == pytest.approx(0.7 * 100.0)


def test_only_ascii_digits_are_numbers(checker_module) -> None:
    """The statement says only digits count, so ``int()``'s extras must not.

    ``int()`` accepts a leading ``+``, ``_`` separators and non-ASCII decimal
    digits (``٩``, ``９``).  A published rule the checker does not enforce is the
    same class of statement/checker divergence as the partial floor that was
    removed, so the parse is restricted and the gap is pinned here: each of these
    parses to a *correct* value under bare ``int()`` and must still score 0.
    """
    casos = {
        # `int("+9")` and `int("+75025")` both succeed.
        "un signo adelante": f"+9\n" + " ".join(f"+{s}" for s in ANSWER.split()[1:]) + "\n",
        # `int("100_000")` succeeds; Python's own literal separator.
        "guiones bajos": "1\n100_000\n",
        "dígitos arábigo-índicos": ANSWER.translate(str.maketrans("0123456789", "٠١٢٣٤٥٦٧٨٩")),
        "dígitos de ancho completo": ANSWER.translate(str.maketrans("0123456789", "０１２３４５６７８９")),
        "BOM al principio": "\ufeff" + ANSWER,
    }
    for nombre, output in casos.items():
        result = check(checker_module, output)
        assert result.passed is False and result.points == 0.0, nombre
    # The control: the same answer in plain ASCII digits is untouched by the
    # restriction and still earns full marks.
    assert check(checker_module, ANSWER).points == 100.0


# ---------------------------------------------------------------------------
# The checker never crashes on garbage
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "output",
    [
        "",
        "\n",
        "   \n",
        "x\n",
        "9\nx y z\n",
        "9\n75025 x y\n",
        "9\n",
        "-9\n-1 -2\n",
        "9\n1.5 2.5\n",
        "9\n" + "9 " * 40 + "\n",
        "999999999999999999999999\n1\n",
        "9\n" + "0 " * 9 + "\n",
        "\x00\x01\x02\n",
    ],
)
def test_malformed_output_never_raises(checker_module, output: str) -> None:
    """A checker that raises is graded as an internal error: a broken problem.

    Every one of these must come back as a ``CheckerResult`` -- passed or not,
    full, partial or zero -- and never as an exception.  That is the whole reason
    the submission's parse sits inside a ``try``.
    """
    result = check(checker_module, output)
    assert result.passed in (True, False)
    assert 0.0 <= result.points <= 100.0


def test_malformed_output_scores_zero_deterministically(checker_module) -> None:
    """Deterministic is part of the contract: the same input must always score the
    same, so a contestant cannot be paid differently on two identical runs.

    Note the value: zero.  Unlike the ``custom`` template -- whose checker has a
    floor for garbage after a valid first line, because its ``judge_input`` makes
    that first line cost something -- this model's declaration is free, so garbage
    is simply rejected.
    """
    for output in ("9\nx y z\n", "9\n75025 x y\n", "9\n"):
        scores = {check(checker_module, output).points for _ in range(5)}
        assert len(scores) == 1 and scores.pop() == 0.0, output


def test_carriage_returns_do_not_change_the_score(checker_module) -> None:
    """``TEXT`` strips carriage returns (``StripCarriageReturnsMixin``), because
    the source is output byte-for-byte and the judge's test data strips them too.

    The checker splits on whitespace, so a ``\\r`` that survived normalisation
    still would not change a verdict -- asserted rather than assumed, because
    discovering a line-ending sensitivity inside a judge run is the expensive way
    to find out.
    """
    lf = check(checker_module, "10\n46368 28657 17711 6765 377 89 21 8 3 1\n")
    crlf = check(checker_module, "10\r\n46368 28657 17711 6765 377 89 21 8 3 1\r\n")
    assert crlf.points == lf.points == pytest.approx(0.7 * 100.0)
    assert crlf.passed == lf.passed is True
    # A lone `\r` is whitespace to `split()`, so a Mac-classic file is read too.
    cr = check(checker_module, "10\r46368 28657 17711 6765 377 89 21 8 3 1\r")
    assert cr.points == pytest.approx(0.7 * 100.0)


# ---------------------------------------------------------------------------
# The problem's own artifacts are held to a higher standard than the submission
# ---------------------------------------------------------------------------


def test_a_model_output_that_is_not_minimal_is_an_error_not_a_partial_score(
    checker_module,
) -> None:
    """Our ``.out`` is copied from ``solution.txt``, so it must be minimal.

    The asymmetry is the point: the submission is untrusted and tolerated, the
    problem's artifacts are ours and are demanded.  A checker that scored its own
    model output as "partial" would silently cap every contestant below full marks.
    """
    with pytest.raises(ValueError, match="no son óptimos"):
        check(checker_module, ANSWER, model_out="10\n46368 28657 17711 6765 377 89 21 8 3 1\n")


def test_a_model_output_that_misses_the_target_is_an_error(checker_module) -> None:
    with pytest.raises(ValueError, match="no representan"):
        check(checker_module, ANSWER, model_out="9\n46368 17711 6765 377 89 21 8 3 1\n")


def test_an_empty_model_output_is_an_error(checker_module) -> None:
    with pytest.raises(ValueError, match="vacía"):
        check(checker_module, ANSWER, model_out="")


def test_a_model_output_with_a_bad_declared_count_is_an_error(checker_module) -> None:
    with pytest.raises(ValueError, match="declara 8 sumandos y trae 9"):
        check(checker_module, ANSWER, model_out="8\n75025 17711 6765 377 89 21 8 3 1\n")


# ---------------------------------------------------------------------------
# The manifest
# ---------------------------------------------------------------------------


def test_the_template_manifest_matches_the_schema_verify_reads(template: Path) -> None:
    _, resolved = meta_mod.load(template)
    entries = verify.load_manifest(template, resolved)
    assert [entry.source.as_posix() for entry in entries] == [
        "solution.txt",
        "submissions/parcial.txt",
        "submissions/no-representa.txt",
        "submissions/malformado.txt",
    ]
    assert [entry.role for entry in entries] == ["model", None, None, "checker-test"]
    assert [(entry.verdict, entry.score) for entry in entries] == [
        ("AC", 100.0),
        ("AC", 70.0),
        ("WA", 0.0),
        ("WA", 0.0),
    ]
    assert all(entry.declares_expectation for entry in entries)


def test_the_partial_score_is_the_checkers_own_fraction(template: Path, checker_module) -> None:
    """``score: 70`` is not a number an author typed and hoped for.

    It is the checker's ``PUNTAJE_PARCIAL`` applied to the shipped partial
    submission, computed here through the real ``check()`` so the manifest cannot
    drift from the checker.
    """
    _, resolved = meta_mod.load(template)
    entries = {entry.source.name: entry for entry in verify.load_manifest(template, resolved)}
    parcial = (template / "submissions" / "parcial.txt").read_text()
    result = check(checker_module, parcial)
    assert result.points == pytest.approx(100.0 * checker_module.PUNTAJE_PARCIAL)
    assert entries["parcial.txt"].score == result.points


def test_the_partial_submission_is_not_declared_as_the_checker_test(template: Path) -> None:
    """``role: checker-test`` means "the checker must reject this".

    The partial submission is *accepted* with a fraction, so mislabelling it would
    make check 5 read it as a missing rejection.
    """
    _, resolved = meta_mod.load(template)
    entries = {entry.source.name: entry for entry in verify.load_manifest(template, resolved)}
    assert entries["parcial.txt"].role is None
    assert entries["malformado.txt"].role == "checker-test"


def test_the_wrong_submission_is_well_formed_not_malformed(template: Path) -> None:
    """``no-representa.txt`` has the right shape and the wrong object.

    A malformed file would make its WA a statement about the parser's robustness
    rather than about the problem; the teaching point here is that the score
    measures the construction, so the file must parse perfectly and still score 0.
    """
    text = (template / "submissions" / "no-representa.txt").read_text()
    tokens = text.split()
    assert int(tokens[0]) == len(tokens) - 1  # the declared count agrees with the body
    assert all(int(token) in set(_fibonacci_hasta(OBJETIVO)) for token in tokens[1:])
    assert sum(int(token) for token in tokens[1:]) != OBJETIVO


def test_the_malformed_submission_stays_inside_the_cheap_deterministic_branch(
    checker_module, template: Path
) -> None:
    """``role: checker-test`` must produce a *rejection*, and check 5 reads that as
    exactly ``WA``.  Partial credit comes back as AC, so the malformed file must
    fail the first line rather than the body."""
    result = check(checker_module, (template / "submissions" / "malformado.txt").read_text())
    assert result.passed is False
    assert result.points == 0.0
    assert "no es un entero" in (result.feedback or "")


def test_the_manifest_declares_no_subject_for_the_checks_this_model_cannot_run(
    template: Path,
) -> None:
    """``role: brute`` and ``verdict: TLE`` name a *program* in every other model;
    here every submission is a ``.txt``, so declaring either would be an
    expectation the model can never satisfy."""
    _, resolved = meta_mod.load(template)
    entries = verify.load_manifest(template, resolved)
    assert {entry.role for entry in entries} == {"model", None, "checker-test"}
    assert {entry.verdict for entry in entries} == {"AC", "WA"}


def test_verify_six_checks_own_the_checker_and_skip_what_this_model_cannot_supply(
    template: Path,
) -> None:
    """Having a checker changes which checks have a subject.

    Compared with ``output-only``: check 5 now has one (the model ships a
    ``role: checker-test`` entry and ``init.yml`` declares a checker), while 3 and
    4 still skip with a reason because no ``TXT`` submission can be a program.
    """
    _, resolved = meta_mod.load(template)
    entries = verify.load_manifest(template, resolved)
    reports = [
        verify.Report(entry=entry, cases=[], batches=[], compile_error=None) for entry in entries
    ]
    checks = {check.number: check for check in verify.run_checks(reports, resolved, "checker.py")}

    # 3 and 4 are the ones this model cannot supply a subject for.
    assert checks[3].status == verify.SKIP and "TLE" in checks[3].detail
    assert checks[4].status == verify.SKIP and "brute" in checks[4].detail
    # 5 has a subject, so with nothing graded it fails -- the synthetic report's
    # doing, and the proof that it is being evaluated rather than skipped.
    assert checks[5].status != verify.SKIP


def test_check_five_skips_when_init_yml_has_no_checker(template: Path) -> None:
    """``verify`` asks ``init.yml``, not ``meta.yml``, or a stale build would be
    read as a checker that is not in force."""
    _, resolved = meta_mod.load(template)
    entries = verify.load_manifest(template, resolved)
    reports = [
        verify.Report(entry=entry, cases=[], batches=[], compile_error=None) for entry in entries
    ]
    checks = {check.number: check for check in verify.run_checks(reports, resolved, None)}
    assert checks[5].status == verify.SKIP
    assert "Regenerate init.yml" in checks[5].detail


# ---------------------------------------------------------------------------
# Scaffolding into the real checkout (the pool only sees problems under it)
# ---------------------------------------------------------------------------


def test_scaffold_ignores_build_artifacts(tmp_path, monkeypatch) -> None:
    problem = scaffold(tmp_path, monkeypatch)
    assert not (problem / cases_mod.INIT_FILENAME).exists()
    assert not (problem / "cases").exists()
    assert not (problem / "__pycache__").exists()


def test_scaffolding_one_text_model_never_yields_the_other(tmp_path, monkeypatch) -> None:
    """The user-facing distinction Q11 requires, checked at the CLI."""
    a = scaffold(tmp_path, monkeypatch, "solo-texto")
    assert run(["new", "--model", "output-only", "solo-plano"], monkeypatch, tmp_path) == 0
    b = tmp_path / "solo-plano"
    _, resolved_a = meta_mod.load(a)
    _, resolved_b = meta_mod.load(b)
    assert resolved_a.model == MODEL and resolved_b.model == "output-only"
    assert resolved_a.uses_checker and not resolved_b.uses_checker
    assert (a / cases_mod.CHECKER_FILENAME).is_file()
    assert not (b / cases_mod.CHECKER_FILENAME).exists()
    # And the checker that came along is the one that can actually load.
    assert "CheckerResult" in (a / cases_mod.CHECKER_FILENAME).read_text()


def test_no_test_run_writes_into_the_template() -> None:
    """Author files are shipped package data: a stray bytecode copy would ship too."""
    template = templates.template_dir(MODEL)
    strays = [
        path.name
        for path in template.iterdir()
        if path.name
        not in {
            "checker.py",
            "generator.py",
            "meta.yml",
            "solution.txt",
            "submissions.yml",
            "media",
            "submissions",
        }
    ]
    assert strays == []
    assert not (template / "__pycache__").exists()

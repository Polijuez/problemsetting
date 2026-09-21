"""The ``output-only`` template is a complete, buildable problem.

The model's whole point is that the submission is a ``.txt`` file: DMOJ runs it
with the ``TEXT`` executor (``cat``), compares it against the shipped expected
output, and awards nothing but full marks.  So these tests defend three things
that a plain `standard` template cannot even express:

* the model resolves to ``submission: text`` → ``TEXT`` → ``.txt`` (and the
  toolkit's ``.txt`` → executor mapping exists at all -- it is what makes the
  submission gradeable);
* ``cases`` emits cases with only ``out:`` and never writes an input file, and
  the generator's ``write_file`` is never reached;
* ``outputs`` produces the expected outputs by *copying* the model solution, with
  no compiler and no program run anywhere on that path.

The last one is tested by making every code path that could run something raise:
if ``outputs`` still succeeds, the copy is the only thing that happened.
"""

from __future__ import annotations

import support
from pathlib import Path

import pytest
import yaml

from problemsetting import cases as cases_mod
from problemsetting import cli
from problemsetting import meta as meta_mod
from problemsetting import outputs as outputs_mod
from problemsetting import templates
from problemsetting import verify

MODEL = "output-only"
#: The answer the template ships: the last 5 digits of F(10^12).
ANSWER = "46875"


@pytest.fixture(scope="module")
def template() -> Path:
    return templates.template_dir(MODEL)


@pytest.fixture(scope="module")
def generator_module(template: Path):
    # Via support.load_module, not importlib: a template is shipped package data,
    # and importlib's file loader would leave __pycache__ inside it.
    return support.load_module(template / "generator.py", "_output_only_generator")


def run(argv: list[str], monkeypatch, cwd: Path) -> int:
    monkeypatch.chdir(cwd)
    return cli.main(argv)


def scaffold(tmp_path: Path, monkeypatch, name: str = "fib") -> Path:
    """``problemsetting new --model output-only <name>`` into a scratch directory."""
    assert run(["new", "--model", MODEL, name], monkeypatch, tmp_path) == 0
    return tmp_path / name


# ---------------------------------------------------------------------------
# The template is a complete problem
# ---------------------------------------------------------------------------


def test_template_ships_the_whole_problem(template: Path) -> None:
    for name in (
        "meta.yml",
        "generator.py",
        "solution.txt",
        "submissions.yml",
        "media/statement.md",
        "submissions/incorrecto.txt",
    ):
        assert (template / name).is_file(), name


def test_template_meta_yml_resolves_to_the_text_submission_model() -> None:
    authoring, resolved = meta_mod.load(templates.template_dir(MODEL))
    assert authoring["model"] == MODEL
    assert authoring["solutionlang"] == ".txt"
    assert resolved.executor == "TEXT"
    assert resolved.is_output_only
    assert not resolved.is_batched and not resolved.uses_checker and not resolved.uses_signature


def test_template_comment_header_matches_the_generator_of_meta_yml(template: Path) -> None:
    """The template's header is the one users see, so it tracks ``meta.HEADER``."""
    assert (template / "meta.yml").read_text().startswith(meta_mod.HEADER), (
        "the output-only template's meta.yml comment block has drifted from "
        "problemsetting.meta.HEADER"
    )


# ---------------------------------------------------------------------------
# The `.txt` → TEXT executor mapping: without it the submission cannot be graded
# ---------------------------------------------------------------------------


def test_txt_maps_to_the_text_executor_and_is_the_only_extension_allowed() -> None:
    """`.txt` is what makes a text submission gradeable at all.

    The prior toolkit's ``LANG_BY_EXT`` had no ``.txt`` entry, so an output-only
    submission could not be graded in any language; this asserts the mapping (and
    the model's extension restriction) exist.
    """
    assert meta_mod.EXECUTOR_BY_EXT[".txt"] == "TEXT"
    assert meta_mod.FAMILY_BY_EXT[".txt"] == "text"
    assert meta_mod.allowed_extensions(meta_mod.MODELS[MODEL]) == (".txt",)
    assert meta_mod.EXECUTOR_FAMILY["TEXT"] == "text"


def test_verify_infers_text_for_a_txt_submission(template: Path) -> None:
    """The manifest entry is resolved to the executor the judge will actually use."""
    _, resolved = meta_mod.load(template)
    entries = verify.load_manifest(template, resolved)
    assert all(entry.source.suffix == ".txt" for entry in entries)
    assert [entry.executor for entry in entries] == ["TEXT", "TEXT"]


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


def test_case_check_rejects_an_answer_that_is_not_the_declared_one(generator_module) -> None:
    case = generator_module.TestCase(ANSWER)  # the declared answer is fine
    assert case.answer == ANSWER
    with pytest.raises(AssertionError):
        generator_module.TestCase("46874")


def test_get_subtasks_yields_a_single_all_or_nothing_batch(generator_module) -> None:
    subtasks = generator_module.Generator().get_subtasks()
    assert len(subtasks) == 1
    points, check = subtasks[0]
    assert points == 100
    assert check(generator_module.TestCase(ANSWER))


def test_the_generator_has_no_stress_hook(generator_module) -> None:
    """``stress`` needs two programs; a text submission gives it none.

    ``gen_small`` is optional by design, so a template without one is correct.
    For this model the hook would also be pointless: ``stress`` compares the
    model solution against a brute-force *submission*, and both would have to be
    ``.txt`` files holding an already-computed answer.
    """
    assert not hasattr(generator_module.Generator(), "gen_small")


def test_stress_cuts_this_model_off_with_the_reason_not_the_missing_hook(
    tmp_path, monkeypatch, capsys
) -> None:
    """Which skip ``stress`` reports for this model, observed rather than assumed.

    ``run_stress`` returns on ``is_output_only`` *before* it looks for
    ``gen_small``, so the reason a reader of the generator might expect -- "no
    tiny-case hook" -- is not the one this model gets.
    """
    scaffold(tmp_path, monkeypatch)
    assert run(["stress", "fib"], monkeypatch, tmp_path) == 0
    out = capsys.readouterr().out
    assert "grades a text file rather than a program" in out
    assert "gen_small" not in out


# ---------------------------------------------------------------------------
# The shipped answer: last 5 digits of Fibonacci(10^12)
# ---------------------------------------------------------------------------


def _fibonacci_mod_fast_doubling(n: int, mod: int) -> int:
    """F(n) mod `mod` via fast doubling -- a *different* algorithm from the
    generator's matrix power, so the two agreeing is evidence and not a tautology."""

    def pair(k: int) -> tuple[int, int]:
        if k == 0:
            return 0, 1
        a, b = pair(k >> 1)
        c = (a * ((2 * b - a) % mod)) % mod
        d = (a * a + b * b) % mod
        return (d, (c + d) % mod) if k & 1 else (c, d)

    return pair(n)[0]


def test_the_answer_is_the_last_five_digits_of_fibonacci_10_to_the_12th(generator_module) -> None:
    assert generator_module.RESPUESTA == ANSWER
    assert _fibonacci_mod_fast_doubling(10**12, 10**5) == int(ANSWER)
    # And the modulo matters: a linear recurrence that stops one step short gets a
    # different number, so this is not an identity that any five digits satisfy.
    assert _fibonacci_mod_fast_doubling(10**12 - 1, 10**5) == 90626


def test_solution_txt_is_the_generators_answer(template: Path, generator_module) -> None:
    """``outputs`` copies the file without checking it, so the two must agree.

    This is the drift the toolkit cannot detect on its own, which is exactly why
    the template's test does.
    """
    assert (template / "solution.txt").read_text().strip() == generator_module.RESPUESTA


# ---------------------------------------------------------------------------
# cases: only `out:`, never an input file
# ---------------------------------------------------------------------------


def test_cases_emits_out_only_cases_and_writes_no_input(tmp_path, monkeypatch, capsys) -> None:
    problem = scaffold(tmp_path, monkeypatch)
    assert run(["cases", "fib"], monkeypatch, tmp_path) == 0

    assert not list(problem.glob("cases/*.in"))
    document = yaml.safe_load((problem / cases_mod.INIT_FILENAME).read_text())
    entries = [entry for batch in document["test_cases"] for entry in batch["batched"]]
    assert entries == [{"out": "cases/0.out"}]
    assert all("in" not in entry for entry in entries)
    # `output-only` is one batch, all or nothing.
    assert [batch["points"] for batch in document["test_cases"]] == [100]
    assert "checker:" not in (problem / cases_mod.INIT_FILENAME).read_text()
    assert "signature_grader:" not in (problem / cases_mod.INIT_FILENAME).read_text()
    assert "0 input files" in capsys.readouterr().out


def test_a_dot_prefixed_name_is_refused_so_a_problem_can_never_be_unreachable(
    tmp_path, monkeypatch, capsys
) -> None:
    """The pool discovers problems with ``glob``, which skips leading-dot paths.

    A problem under ``.scratch/`` is therefore invisible: every submission fails
    with ``unknown problem``.  ``new`` cannot let that happen by accident, because
    a directory name is the problem id and ``validate_name`` refuses one that
    would not survive a glob -- ``.fib``, and ``.`` / ``..`` with it.
    """
    for name in (".fib", ".", ".."):
        assert run(["new", "--model", MODEL, name], monkeypatch, tmp_path) == 1
        assert capsys.readouterr().err.startswith("error: ")
    assert not list(tmp_path.iterdir())


# ---------------------------------------------------------------------------
# outputs: a file copy, with no compiler and no program run
# ---------------------------------------------------------------------------


def test_outputs_copies_the_text_instead_of_running_anything(
    tmp_path, monkeypatch, capsys
) -> None:
    """The decisive test: nothing that could run or build is reachable.

    ``resolve_tools`` (host toolchain resolution), ``run_tool`` (compile) and
    ``run_case`` (run the model solution over a case) are all made to raise.  If
    ``outputs`` succeeds anyway and every ``.out`` is the ``.txt`` byte for byte,
    the copy is the only path that ran.
    """
    problem = scaffold(tmp_path, monkeypatch)

    def explode(*args, **kwargs):  # pragma: no cover - only reached on a regression
        raise AssertionError("output-only must not compile or run anything")

    monkeypatch.setattr(outputs_mod, "resolve_tools", explode)
    monkeypatch.setattr(outputs_mod, "run_tool", explode)
    monkeypatch.setattr(outputs_mod, "run_case", explode)

    assert run(["cases", "fib"], monkeypatch, tmp_path) == 0
    assert run(["outputs", "fib"], monkeypatch, tmp_path) == 0
    assert "copying the model solution" in capsys.readouterr().out

    assert (problem / "cases" / "0.out").read_bytes() == (problem / "solution.txt").read_bytes()
    assert (problem / "cases" / "0.out").read_text() == ANSWER + "\n"
    # No build artifacts: nothing was compiled.
    assert not list(problem.glob("__meta__/solution*"))


def test_a_re_edited_solution_is_re_copied(tmp_path, monkeypatch) -> None:
    """The copy must never go stale, because the judge would grade it as the answer."""
    problem = scaffold(tmp_path, monkeypatch)
    assert run(["cases", "fib"], monkeypatch, tmp_path) == 0
    assert run(["outputs", "fib"], monkeypatch, tmp_path) == 0
    assert (problem / "cases" / "0.out").read_text() == ANSWER + "\n"

    (problem / "solution.txt").write_text("00001\n")
    assert run(["outputs", "fib"], monkeypatch, tmp_path) == 0
    assert (problem / "cases" / "0.out").read_text() == "00001\n"


# ---------------------------------------------------------------------------
# Build and archive: the whole pipeline under a non-dot directory
# ---------------------------------------------------------------------------


def test_build_produces_the_case_and_the_archive(tmp_path, monkeypatch) -> None:
    problem = scaffold(tmp_path, monkeypatch)
    assert run(["build", "fib"], monkeypatch, tmp_path) == 0
    assert (problem / "cases" / "0.out").read_text() == ANSWER + "\n"
    assert (problem / "fib.zip").is_file()
    assert (problem / cases_mod.INIT_FILENAME).is_file()


# ---------------------------------------------------------------------------
# The manifest
# ---------------------------------------------------------------------------


def test_the_template_manifest_matches_the_schema_verify_reads(template: Path) -> None:
    _, resolved = meta_mod.load(template)
    entries = verify.load_manifest(template, resolved)
    assert [entry.source.as_posix() for entry in entries] == [
        "solution.txt",
        "submissions/incorrecto.txt",
    ]
    assert [entry.role for entry in entries] == ["model", None]
    assert [(entry.verdict, entry.score) for entry in entries] == [("AC", 100.0), ("WA", 0.0)]
    assert all(entry.declares_expectation for entry in entries)


def test_the_wrong_submission_is_a_plausible_answer_not_a_malformed_file(template: Path) -> None:
    """The wrong `.txt` has the right shape and the wrong value.

    A malformed file would make this template's WA a statement about the
    comparison's robustness rather than about the problem; the teaching point
    here is that only the exact number is accepted.
    """
    text = (template / "submissions" / "incorrecto.txt").read_text()
    assert text.strip().isdigit() and len(text.strip()) == 5
    assert text.strip() != ANSWER


def test_verify_six_checks_skip_what_this_model_cannot_supply(template: Path) -> None:
    """The checks this model legitimately cannot run skip *with a reason*.

    No ``role: brute`` and no ``verdict: TLE`` entry exist (and cannot: both would
    have to be programs), and there is no checker.  ``verify`` must say so rather
    than reporting a pass it did not earn.
    """
    _, resolved = meta_mod.load(template)
    entries = verify.load_manifest(template, resolved)
    reports = [
        verify.Report(entry=entry, cases=[], batches=[], compile_error=None)
        for entry in entries
    ]
    checks = {check.number: check for check in verify.run_checks(reports, resolved, None)}

    # Check 2 has a subject (the `verdict: WA` entry), so it runs rather than
    # skipping; with nothing graded it fails, which is the synthetic report's
    # doing and not a claim about the template.
    assert checks[2].status != verify.SKIP

    # 3, 4 and 5 are the ones this model cannot supply a subject for, and each
    # must say why instead of reporting a pass.
    assert checks[3].status == verify.SKIP
    assert "TLE" in checks[3].detail
    assert checks[4].status == verify.SKIP
    assert "brute" in checks[4].detail
    assert checks[5].status == verify.SKIP
    assert "checker" in checks[5].detail


def test_the_manifest_declares_no_subject_for_the_checks_this_model_cannot_run(
    template: Path,
) -> None:
    """Nothing in ``submissions.yml`` pretends a program exists.

    ``role: brute`` and ``verdict: TLE`` both name *a program* in every other
    model; here every submission is a ``.txt``, so declaring either would be an
    expectation the model can never satisfy.
    """
    _, resolved = meta_mod.load(template)
    entries = verify.load_manifest(template, resolved)
    assert {entry.role for entry in entries} == {"model", None}
    assert {entry.verdict for entry in entries} == {"AC", "WA"}


# ---------------------------------------------------------------------------
# Scaffolding into the real checkout (the pool only sees problems under it)
# ---------------------------------------------------------------------------


def test_scaffold_ignores_build_artifacts(tmp_path, monkeypatch) -> None:
    problem = scaffold(tmp_path, monkeypatch)
    assert not (problem / cases_mod.INIT_FILENAME).exists()
    assert not (problem / "cases").exists()
    assert not (problem / "__pycache__").exists()

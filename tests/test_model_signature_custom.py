"""The ``signature-batched-custom`` template: signature interface + quality checker.

This model is the three toolkit mechanisms at once, and the file defends the one
thing that changes when they meet: **the contestant does not print anything**.  In
an I/O problem the submission writes its construction to stdout and the checker
reads it from ``process_output``; here the submission implements a function that
*writes into an array the evaluator passes it* and returns how many positions it
wrote, and the evaluator is what turns that pair into the two lines the checker
reads.

What is asserted here, and why it is this model's contract rather than
``batched-custom``'s repeated:

* the header declares a function that takes an output array -- the interface
  carries a *memory* obligation (write at most ``n`` positions) that the firm of
  the type alone cannot express, so it is checked, not assumed;
* the checker is the same object-validation the other custom models use, and the
  malformed-output path is reached through the *return value* rather than through
  garbage text;
* the evaluator's output format is the checker's input format -- the two files
  are checked against each other rather than each against a restatement;
* the composition matches the judge's, with the real compilers, in both C and C++.

The end-to-end numbers live in the template's ``submissions.yml`` and were
measured against a real judge container; the comment there records the run.
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
from problemsetting import outputs as outputs_mod
from problemsetting import templates
from problemsetting import verify as verify_mod

MODEL = "signature-batched-custom"

#: The function the header declares.  Named once: the header, the evaluator, both
#: model solutions and both violating submissions have to agree on it, so a test
#: that greps for it is really asking "are these files still one interface?".
FUNCTION = "iluminar"


@pytest.fixture(scope="module")
def template() -> Path:
    return templates.template_dir(MODEL)


@pytest.fixture(scope="module")
def generator_module(template: Path):
    # Via support.load_module, not importlib: a template is shipped package data,
    # and importlib's file loader would leave __pycache__ inside it.
    return support.load_module(template / "generator.py", "_sig_custom_generator")


@pytest.fixture(scope="module")
def checker_module(template: Path):
    """The checker, loaded with a stub ``dmoj`` -- the host has no judge installed.

    The stub is only enough of ``dmoj`` for the module to import; it is not a mock
    of the checker's behaviour, so the code under test is the template's own.
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

    return support.load_module(template / "checker.py", "_sig_custom_checker")


#: The checker's own signature, as DMOJ calls it (``dmoj/graders/standard.py:57``).
#: ``point_value`` is the *batch's* points, not the problem's.
def check(checker_module, output: str, *, n: int, model_out: str, point_value: float = 100.0):
    return checker_module.check(
        process_output=output.encode(),
        judge_output=model_out.encode(),
        judge_input=f"{n}\n".encode(),
        point_value=point_value,
        submission_source=b"",
    )


#: The model solution's answer for ``n``, as the ``.out`` files hold it: the
#: evaluator prints ``ceil(n/5)`` and then the lamps at 3, 8, 13, ...
def model_output(n: int) -> str:
    lamps = [((2 + 5 * j) % n) + 1 for j in range(-(-n // 5))]
    return f"{len(lamps)}\n" + " ".join(str(lamp) for lamp in lamps) + "\n"


def run(argv: list[str], monkeypatch, cwd: Path) -> int:
    monkeypatch.chdir(cwd)
    return cli.main(argv)


# ---------------------------------------------------------------------------
# The template is a complete problem
# ---------------------------------------------------------------------------


def test_template_ships_the_whole_problem(template: Path) -> None:
    for name in (
        "meta.yml",
        "generator.py",
        "checker.py",
        "signature.hpp",
        "evaluator.cpp",
        "solution.c",
        "solution.cpp",
        "submissions.yml",
        "media/statement.md",
    ):
        assert (template / name).is_file(), name
    assert sorted(path.name for path in (template / "submissions").iterdir()) == [
        "firma-incorrecta.c",
        "firma-incorrecta.cpp",
        "hasta-2000.cpp",
        "invalido.cpp",
        "malformado.cpp",
        "solo-chicos.cpp",
    ]


def test_template_meta_yml_declares_the_signature_batched_custom_model(template: Path) -> None:
    authoring, resolved = meta_mod.load(template)
    assert authoring["model"] == MODEL
    assert resolved.uses_signature, "the template must resolve to the signature grader"
    assert resolved.uses_checker, "and to the custom checker"
    assert resolved.is_batched, "and to the subtasks axis"
    assert resolved.executor == "CPP17", "the declared solutionlang is the default"


def test_template_meta_yml_header_matches_meta_HEADER(template: Path) -> None:
    """The template's header is the one users see, so it tracks ``meta.HEADER``."""
    assert (template / "meta.yml").read_text(encoding="utf-8").startswith(meta_mod.HEADER)


def test_the_meta_declares_limits_for_both_languages(template: Path) -> None:
    """C is a language choice, so its limits must be declared, not inherited.

    A submission's limits come from ``limits[<its own extension>]``: an entry in
    ``.c`` graded against the 2 s default while the ``.cpp`` entries get 1 s would
    grade the same algorithm under two different limits, which is exactly the kind
    of drift the manifest's measured scores would hide.
    """
    _, resolved = meta_mod.load(template)
    assert resolved.limits[".c"] == meta_mod.Limits(1.0, 262144)
    assert resolved.limits[".cpp"] == meta_mod.Limits(1.0, 262144)


# ---------------------------------------------------------------------------
# The interface: header, evaluator, model solutions
# ---------------------------------------------------------------------------


def test_the_header_declares_the_output_array_function(template: Path) -> None:
    """The interface is a function that *fills* an array and returns its length.

    This is the model's whole difference from an I/O problem: there is no ``cout``
    for a contestant to write to, so the answer travels as a return value plus a
    caller-provided buffer.
    """
    header = (template / "signature.hpp").read_text(encoding="utf-8")
    assert f"int {FUNCTION}(int n, int *faros);" in header
    assert "main" not in _code(header), "the header must not define or declare main"


def test_the_header_states_the_memory_obligation(template: Path) -> None:
    """A type cannot say "write at most ``n`` positions", so the header must.

    Unlike every other obligation in the signature, violating this one is not a
    wrong answer: it is out-of-bounds memory.  It is stated for the contestant
    because it is not deducible from the declaration.
    """
    header = (template / "signature.hpp").read_text(encoding="utf-8")
    assert "capacidad `n`" in header
    assert "corrompe memoria" in header


def test_the_header_has_an_include_guard(template: Path) -> None:
    """The judge's prefix includes the header, and the submission may include it too."""
    header = (template / "signature.hpp").read_text(encoding="utf-8")
    assert "#ifndef" in header and "#define" in header and "#endif" in header


def test_the_header_is_a_c_interface_usable_from_cpp(template: Path) -> None:
    """No ``std::`` in the declaration, and the C++ side gets ``extern "C"``.

    Both halves are load-bearing and neither is decoration: the evaluator is
    compiled as C when the executor is ``C11``, so a ``std::string`` here would
    make the C variant impossible; and without the ``extern "C"`` guards a
    definition written in C would get a different symbol than the call site in a
    C++-compiled evaluator, so the two halves would not link.
    """
    header = (template / "signature.hpp").read_text(encoding="utf-8")
    assert "std::" not in _code(header)
    assert 'extern "C"' in _code(header)
    # The `extern "C"` must wrap the *declaration*, not sit there unused: the
    # declaration has to fall between the opening and closing guard.
    opening = _code(header).index('extern "C" {')
    assert _code(header).index(f"int {FUNCTION}(") > opening


def test_the_evaluator_is_the_program_that_calls_the_function(template: Path) -> None:
    """``evaluator.cpp`` owns ``main``, the input, the buffer and the output."""
    entry = _code((template / "evaluator.cpp").read_text(encoding="utf-8"))
    assert "int main(" in entry, entry
    assert f"{FUNCTION}(n, faros)" in entry
    assert "malloc" in entry, "the buffer the function writes into is the evaluator's"
    # It is the evaluator, not the submission, that prints the checker's format.
    assert "printf" in entry


def test_the_evaluator_stays_in_the_common_subset_of_c_and_cpp(template: Path) -> None:
    """The evaluator is compiled as C when the executor is ``C11``.

    Its file name says ``.cpp``, but ``CLikeExecutor`` stages it as
    ``<problem>c.c`` for a C run and the compiler dispatches on that suffix -- so
    anything C++-only here would break the C variant of the model, which is the
    language choice this template exists to offer.
    """
    entry = _code((template / "evaluator.cpp").read_text(encoding="utf-8"))
    for cxx_only in ("std::", "#include <iostream>", "new ", "vector"):
        assert cxx_only not in entry, cxx_only


def test_the_model_solutions_are_functions_not_programs(template: Path) -> None:
    """Both model solutions obey the contract a contestant does -- no ``main``."""
    for name in ("solution.cpp", "solution.c"):
        source = _code((template / name).read_text(encoding="utf-8"))
        assert f"int {FUNCTION}(int n, int *faros)" in source, name
        assert "int main(" not in source, name


def test_the_two_model_solutions_are_the_same_solution(template: Path) -> None:
    """C and C++ are a language choice, not two problems: the answers must agree.

    The two files are compared through their *outputs* elsewhere (the composition
    tests run both); here the shared structure is what is checked, so that a change
    to one algorithm cannot quietly leave the other behind.
    """
    cpp = _code((template / "solution.cpp").read_text(encoding="utf-8"))
    c = _code((template / "solution.c").read_text(encoding="utf-8"))
    marker = "(n + 4) / 5"
    assert marker in cpp and marker in c, "both must use the same ceil(n/5)"
    pattern = "(2 + 5 * j) % n + 1"
    assert pattern in cpp and pattern in c, "both must place the lamps identically"


def _code(source: str) -> str:
    """``source`` with its comments removed.

    The template's comments *discuss* ``main``, ``std::`` and the other words these
    tests search for -- that is their job -- so a plain substring search would
    report the explanation as a violation.  A block comment becomes nothing and a
    line comment vanishes with its newline, which is all these assertions need;
    this is deliberately not a C++ lexer.
    """
    out = []
    index = 0
    while index < len(source):
        if source.startswith("//", index):
            index = source.find("\n", index)
            if index == -1:
                break
            continue
        if source.startswith("/*", index):
            end = source.find("*/", index + 2)
            index = len(source) if end == -1 else end + 2
            continue
        out.append(source[index])
        index += 1
    return "".join(out)


# ---------------------------------------------------------------------------
# Generator protocol
# ---------------------------------------------------------------------------


def test_get_cases_returns_ordered_cases_with_the_required_methods(generator_module) -> None:
    cases = generator_module.Generator().get_cases()
    assert cases
    for case in cases:
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


def test_get_subtasks_yields_points_and_callable_classifiers(generator_module) -> None:
    subtasks = generator_module.Generator().get_subtasks()
    total = 0
    for entry in subtasks:
        assert 2 <= len(entry) <= 3, "entries are (points, check) or (points, check, deps)"
        value, check = entry[0], entry[1]
        assert isinstance(value, (int, float)) and value > 0
        assert callable(check)
        total += value
    assert total == 100
    assert len(subtasks) == 4


def test_the_ladder_is_the_batched_custom_templates_ladder(generator_module) -> None:
    """Same points and same dependency as `batched-custom`: only the interface moved.

    That is what makes the two templates comparable, and what makes the measured
    scores (7 and 21) the same in both: the scoring system did not change, only how
    the contestant hands the answer over.
    """
    ladder = generator_module.Generator().get_subtasks()
    assert [entry[0] for entry in ladder] == [10, 20, 30, 40]
    assert ladder[2][2] == [2], "ST3 must keep its dependency on ST2"


def test_the_last_subtask_accepts_every_case(generator_module) -> None:
    cases = generator_module.Generator().get_cases()
    assert all(generator_module.check_st4(case) for case in cases)


def test_gen_small_returns_cases_a_suboptimal_construction_can_use(generator_module) -> None:
    """Tiny cases stay in the range where ``optimo + 1`` lamps exist."""
    rand = random.Random(1234)
    for _ in range(50):
        cases = generator_module.Generator().gen_small(rand)
        assert cases
        for case in cases:
            assert 6 <= case.n <= 60


def test_the_input_is_the_same_one_the_other_custom_templates_use(generator_module) -> None:
    """``n`` alone on a line: the evaluator reads it, and the checker re-reads it."""
    cases = generator_module.Generator().get_cases()
    buffer = io.StringIO()
    cases[0].write_file(buffer)
    assert buffer.getvalue() == f"{cases[0].n}\n"


# ---------------------------------------------------------------------------
# The checker: the same object-validation, reached through a return value
# ---------------------------------------------------------------------------


def test_optimal_output_earns_full_marks_in_its_batch(checker_module) -> None:
    result = check(checker_module, model_output(6), n=6, model_out=model_output(6))
    assert result.passed and result.points == 100.0


def test_valid_but_suboptimal_output_earns_partial_credit(checker_module) -> None:
    result = check(checker_module, "3\n3 1 2\n", n=6, model_out=model_output(6))
    assert result.passed is True
    assert result.points == pytest.approx(0.7 * 100.0)


def test_a_valid_but_very_inefficient_output_earns_the_lower_band(checker_module) -> None:
    # Every position lit individually: valid, and far past `FACTOR_POBRE` times the
    # optimum (15 lamps where ceil(15/5) = 3).
    everything = " ".join(str(position) for position in range(1, 16))
    result = check(checker_module, f"15\n{everything}\n", n=15, model_out=model_output(15))
    assert result.passed is True
    assert result.points == pytest.approx(0.4 * 100.0)


def test_the_partial_fraction_composes_with_the_batchs_point_value(checker_module) -> None:
    """``point_value`` is the case's *batch*, whose points are 10/20/30/40 here."""
    for batch_points in (10, 20, 30, 40):
        result = check(
            checker_module,
            "3\n3 1 2\n",
            n=6,
            model_out=model_output(6),
            point_value=batch_points,
        )
        assert result.points == pytest.approx(0.7 * batch_points), batch_points


def test_a_rejection_short_circuits_where_a_fraction_does_not(checker_module) -> None:
    """The distinction the batching depends on: ``passed`` is the flag, not points."""
    partial = check(checker_module, "3\n3 1 2\n", n=6, model_out=model_output(6), point_value=20)
    rejected = check(checker_module, "1\n1\n", n=6, model_out=model_output(6), point_value=20)
    assert partial.passed is True and partial.points == pytest.approx(14.0)
    assert rejected.passed is False and rejected.points == 0.0


def test_an_invalid_construction_earns_zero_despite_a_well_formed_output(checker_module) -> None:
    result = check(checker_module, "1\n1\n", n=6, model_out=model_output(6))
    assert result.passed is False and result.points == 0.0


def test_a_claimed_count_that_does_not_match_the_object_is_not_rewarded(checker_module) -> None:
    """Lying about how many positions were written is not a way to earn marks.

    This is the check that a signature submission *can* trip and an I/O one cannot
    trip the same way: the number is the function's return value, so it can
    disagree with what the function wrote.
    """
    result = check(checker_module, "2\n3\n", n=6, model_out=model_output(6))
    assert result.passed is False and result.points == 0.0
    assert "declara" in (result.feedback or "")


def test_repeated_positions_do_not_count_towards_the_score(checker_module) -> None:
    result = check(checker_module, "2\n3 3\n", n=6, model_out=model_output(6))
    assert result.passed is False and result.points == 0.0
    assert "repetidas" in (result.feedback or "")


def test_positions_outside_the_round_are_refused(checker_module) -> None:
    result = check(checker_module, "2\n1 99\n", n=6, model_out=model_output(6))
    assert result.passed is False and result.points == 0.0
    assert "fuera de 1..6" in (result.feedback or "")


def test_a_negative_count_is_refused(checker_module) -> None:
    """The path the template's ``malformado.cpp`` takes.

    In a signature problem the contestant prints nothing, so the malformed output
    has to come from an invalid *return value*: the evaluator prints it verbatim as
    the first line, and the checker's range test rejects it before touching any
    positions.
    """
    result = check(checker_module, "-1\n", n=6, model_out=model_output(6))
    assert result.passed is False and result.points == 0.0
    assert "fuera de rango" in (result.feedback or "")


def test_a_first_line_that_is_not_a_number_is_rejected(checker_module) -> None:
    result = check(checker_module, "tantos\n", n=6, model_out=model_output(6))
    assert result.passed is False and result.points == 0.0


def test_an_empty_output_is_rejected_without_a_crash(checker_module) -> None:
    result = check(checker_module, "", n=6, model_out=model_output(6))
    assert result.passed is False and result.points == 0.0


@pytest.mark.parametrize(
    "output",
    ["", "-1\n", "tantos\n", "0\n\n", "99\n1 2\n", "2\n3\n", "\n\n", "3\n3 3 3\n", "2\n-1 3\n"],
)
def test_malformed_output_never_raises(checker_module, output: str) -> None:
    """A checker that raises is graded as an internal error: a broken problem."""
    result = check(checker_module, output, n=6, model_out=model_output(6))
    assert result.passed in (True, False)
    assert 0.0 <= result.points <= 100.0


def test_malformed_input_data_is_an_error_not_a_partial_score(checker_module) -> None:
    """The asymmetry: the *problem's* input is ours, so a bad one is a real error."""
    with pytest.raises(ValueError):
        check(checker_module, "2\n3 6\n", n=0, model_out=model_output(6))


def test_a_non_optimal_model_output_is_an_error_not_a_partial_score(checker_module) -> None:
    """Our ``.out`` is generated from the model solution, so it must be optimal."""
    with pytest.raises(ValueError, match="óptimo"):
        check(checker_module, "2\n3 2\n", n=6, model_out="1\n1\n")


def test_the_checker_recomputes_coverage_from_the_positions_it_received(checker_module) -> None:
    """The object is what was sent, not what the first line claims."""
    result = check(checker_module, "3\n1 2 3\n", n=100, model_out=model_output(100))
    assert result.passed is False


def test_the_optimum_is_the_circles_covering_number(checker_module) -> None:
    """``ceil(n/5)``: a lamp covers five positions, so nothing smaller can work."""
    assert [checker_module.optimo(n) for n in (1, 5, 6, 11)] == [1, 1, 2, 3]


# ---------------------------------------------------------------------------
# The composition, with the real compilers, in both languages
# ---------------------------------------------------------------------------


def _tool(name: str) -> str:
    found = shutil.which(name)
    if found is None:
        pytest.skip(f"{name} is not on PATH")
    return found


def _compose(problem_id: str, source: Path, template: Path, extension: str, destination: Path) -> list[str]:
    """Stage the three translation units exactly as ``outputs`` (and the judge) do.

    Reusing the toolkit's own staging is the point: the test then proves the
    *template* composes, not that a test-local imitation of the judge does.
    """
    layout = outputs_mod.signature_layout(
        problem_id, extension, "evaluator.cpp", "signature.hpp"
    )
    outputs_mod._stage_signature(
        source, template / "signature.hpp", template / "evaluator.cpp", False, layout, destination
    )
    return [str(destination / name) for name in layout.names]


def _compile(sources: list[str], output: Path, extension: str) -> subprocess.CompletedProcess:
    if extension == ".c":
        argv = [_tool("gcc"), "-Wall", *sources, "-DONLINE_JUDGE", "-DSIGNATURE_GRADER",
                "-O2", "-lm", "-std=c11", "-o", str(output)]
    else:
        argv = [_tool("g++"), "-Wall", *sources, "-DONLINE_JUDGE", "-DSIGNATURE_GRADER",
                "-O2", "-lm", "-std=c++17", "-o", str(output)]
    return subprocess.run(argv, capture_output=True, text=True)


@pytest.mark.parametrize("extension", [".cpp", ".c"])
def test_the_model_solution_composes_and_compiles(template: Path, tmp_path: Path, extension: str) -> None:
    """The shipped solution compiles against the shipped header and evaluator.

    Both languages are run because the model offers both: the C++ pass proves the
    interface, and the C pass proves the *same* interface still works when the
    evaluator is the file ``gcc`` compiles -- which is the part of "C is a language
    choice" that a C++-only test would leave unverified.
    """
    sources = _compose(
        f"sig{extension.lstrip('.')}",
        template / f"solution{extension}",
        template,
        extension,
        tmp_path / "staged",
    )
    result = _compile(sources, tmp_path / "solution", extension)
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("extension", [".cpp", ".c"])
def test_the_composed_solution_illuminates_every_round_it_is_given(
    template: Path, tmp_path: Path, extension: str, checker_module
) -> None:
    """End to end: the composed program's construction really covers the circle.

    The reference is the checker's own ``cubre`` -- a recomputation from the
    positions, not a comparison against the model solution -- so this is not the
    template compared against itself.
    """
    sources = _compose(
        f"sig{extension.lstrip('.')}",
        template / f"solution{extension}",
        template,
        extension,
        tmp_path / "staged",
    )
    binary = tmp_path / "solution"
    result = _compile(sources, binary, extension)
    assert result.returncode == 0, result.stderr

    rand = random.Random(20250922)
    for _ in range(60):
        n = rand.randint(1, 400)
        got = subprocess.run(
            [str(binary)], input=f"{n}\n", capture_output=True, text=True, check=True
        ).stdout.split()
        k, positions = int(got[0]), [int(token) for token in got[1:]]
        assert len(positions) == k, (n, got)
        assert len(set(positions)) == k, (n, got)
        assert all(1 <= position <= n for position in positions), (n, got)
        assert checker_module.cubre(positions, n), (n, got)
        assert k == checker_module.optimo(n), f"n={n}: {k} lamps, optimum is {checker_module.optimo(n)}"


def test_the_two_languages_produce_the_same_answers(template: Path, tmp_path: Path) -> None:
    """The same problem in two languages, so the same construction must come out."""
    answers = {}
    for extension in (".cpp", ".c"):
        sources = _compose(
            f"sig{extension.lstrip('.')}",
            template / f"solution{extension}",
            template,
            extension,
            tmp_path / f"staged{extension.lstrip('.')}",
        )
        binary = tmp_path / f"solution{extension.lstrip('.')}"
        result = _compile(sources, binary, extension)
        assert result.returncode == 0, result.stderr
        answers[extension] = [
            subprocess.run(
                [str(binary)], input=f"{n}\n", capture_output=True, text=True, check=True
            ).stdout
            for n in (6, 9, 51, 2000, 50000)
        ]
    assert answers[".c"] == answers[".cpp"]


def test_a_stray_main_in_a_conforming_submission_is_renamed_away(
    template: Path, tmp_path: Path
) -> None:
    """The ``#define main main_<uuid>`` the header's comment promises, exercised."""
    conforming = (
        (template / "solution.cpp").read_text(encoding="utf-8")
        + "\nint main() { return 0; }\n"
    )
    submission = tmp_path / "solution.cpp"
    submission.write_text(conforming, encoding="utf-8")

    sources = _compose("sig", submission, template, ".cpp", tmp_path / "staged")
    result = _compile(sources, tmp_path / "stray", ".cpp")
    assert result.returncode == 0, result.stderr
    got = subprocess.run(
        [str(tmp_path / "stray")], input="6\n", capture_output=True, text=True, check=True
    ).stdout
    assert got.split()[0] == "2"


@pytest.mark.parametrize(
    ("name", "extension"),
    [("firma-incorrecta.cpp", ".cpp"), ("firma-incorrecta.c", ".c")],
)
def test_a_submission_that_violates_the_header_contract_does_not_compile(
    template: Path, tmp_path: Path, name: str, extension: str
) -> None:
    """The declared ``verdict: CE`` is a property of the interface, not of a run.

    Both languages are exercised because the interface is claimed to serve both:
    a header that rejected a C++ mismatch but accepted a C one would make the
    model's language choice a half-truth.
    """
    sources = _compose(
        f"sig{extension.lstrip('.')}",
        template / "submissions" / name,
        template,
        extension,
        tmp_path / "staged",
    )
    result = _compile(sources, tmp_path / "violating", extension)
    assert result.returncode != 0, "a mismatched signature must not compile"
    assert FUNCTION in result.stderr


def test_the_declared_ce_submissions_are_the_only_ones_with_a_wrong_signature(
    template: Path,
) -> None:
    """The contrast that makes the CE meaningful: everything else conforms."""
    conforming = [
        template / "solution.cpp",
        template / "solution.c",
        template / "submissions" / "solo-chicos.cpp",
        template / "submissions" / "hasta-2000.cpp",
        template / "submissions" / "invalido.cpp",
        template / "submissions" / "malformado.cpp",
    ]
    for path in conforming:
        assert f"int {FUNCTION}(int n, int *faros)" in _code(path.read_text(encoding="utf-8")), path.name
    assert f"int {FUNCTION}(int n, const int *faros)" in (
        template / "submissions" / "firma-incorrecta.cpp"
    ).read_text(encoding="utf-8")
    assert f"long long {FUNCTION}(int n, int *faros)" in (
        template / "submissions" / "firma-incorrecta.c"
    ).read_text(encoding="utf-8")


def test_no_test_run_writes_into_the_template() -> None:
    """The template directory is package data; nothing here may write into it."""
    directory = templates.template_dir(MODEL)
    strays = sorted(
        path.name
        for path in directory.iterdir()
        if path.name
        not in {
            "checker.py",
            "evaluator.cpp",
            "generator.py",
            "media",
            "meta.yml",
            "signature.hpp",
            "solution.c",
            "solution.cpp",
            "submissions",
            "submissions.yml",
        }
    )
    assert strays == []


# ---------------------------------------------------------------------------
# init.yml: the judge is told to build the signature composition AND the checker
# ---------------------------------------------------------------------------


def test_cases_emits_both_the_checker_and_the_signature_grader(
    tmp_path: Path, monkeypatch
) -> None:
    """The two keys are independent, and each names the file it will load.

    ``dmoj/problem.py`` picks ``SignatureGrader`` from ``signature_grader`` and
    takes the checker from ``checker``; a template that emitted only one would
    grade this as a different model while looking correct.
    """
    assert run(["new", "--model", MODEL, "sigcustom"], monkeypatch, tmp_path) == 0
    assert run(["cases", "sigcustom"], monkeypatch, tmp_path) == 0

    document = cases_mod.load_init(tmp_path / "sigcustom")
    assert document["checker"] == cases_mod.CHECKER_FILENAME
    assert document["signature_grader"] == {
        "entry": cases_mod.SIGNATURE_ENTRY,
        "header": cases_mod.SIGNATURE_HEADER,
    }
    batches = [entry for entry in document["test_cases"] if "batched" in entry]
    assert [entry["points"] for entry in batches] == [10, 20, 30, 40]
    assert batches[2]["dependencies"] == [2]


def test_init_yml_declares_the_dependency_only_where_the_generator_does(
    tmp_path: Path, monkeypatch
) -> None:
    assert run(["new", "--model", MODEL, "sigcustom"], monkeypatch, tmp_path) == 0
    assert run(["cases", "sigcustom"], monkeypatch, tmp_path) == 0
    document = cases_mod.load_init(tmp_path / "sigcustom")
    assert [entry.get("dependencies", []) for entry in document["test_cases"]] == [[], [], [2], []]


# ---------------------------------------------------------------------------
# The CLI scaffolds it
# ---------------------------------------------------------------------------


def test_new_scaffolds_a_signature_batched_custom_problem(tmp_path: Path, monkeypatch) -> None:
    assert run(["new", "--model", MODEL, "sigcustom"], monkeypatch, tmp_path) == 0
    problem = tmp_path / "sigcustom"
    for name in ("signature.hpp", "evaluator.cpp", "checker.py", "solution.cpp", "solution.c"):
        assert (problem / name).is_file(), name
    _, resolved = meta_mod.load(problem)
    assert resolved.uses_signature and resolved.uses_checker and resolved.is_batched


def test_the_scaffold_defaults_to_the_templates_declared_language(
    tmp_path: Path, monkeypatch
) -> None:
    """``.cpp``, not ``.c``, even though ``solution.c`` sorts first.

    The template ships two model solutions and declares which one it demonstrates
    in its own ``meta.yml``; with two files present, "the first in sorted order" is
    not that statement, so the default follows the declaration.
    """
    assert run(["new", "--model", MODEL, "sigcustom"], monkeypatch, tmp_path) == 0
    _, resolved = meta_mod.load(tmp_path / "sigcustom")
    assert resolved.solutionlang == ".cpp"
    assert resolved.executor == "CPP17"


def test_the_scaffold_can_still_choose_the_other_language(tmp_path: Path, monkeypatch) -> None:
    assert run(["new", "--model", MODEL, "-s", ".c", "sigcustom"], monkeypatch, tmp_path) == 0
    _, resolved = meta_mod.load(tmp_path / "sigcustom")
    assert resolved.solutionlang == ".c"
    assert resolved.executor == "C11"


def test_signature_batched_custom_is_shipped() -> None:
    assert MODEL in templates.shipped()


def test_build_produces_expected_outputs_for_the_composed_solution(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    """``build`` runs the real composition over the real cases.

    Only the small cases are cross-checked -- ST1's are at most 50 positions, so a
    reference cover check is affordable -- and every larger batch's ``.out`` is the
    same composed program's answer anyway.  What this proves is that the *shipped*
    template, not a fixture, builds and answers correctly through the toolkit.
    """
    assert run(["new", "--model", MODEL, "sigcustom"], monkeypatch, tmp_path) == 0
    assert run(["build", "sigcustom"], monkeypatch, tmp_path) == 0

    problem = tmp_path / "sigcustom"
    # The output order is ST4 first, so the 9 small cases are the last 9 files.
    total = len(list((problem / "cases").glob("*.in")))
    for index in range(total - 9, total):
        tokens = (problem / "cases" / f"{index}.out").read_text().split()
        n = int((problem / "cases" / f"{index}.in").read_text())
        k, positions = int(tokens[0]), [int(token) for token in tokens[1:]]
        assert k == -(-n // 5), f"case {index}: n={n}"
        assert len(positions) == k
        assert sorted(positions) == sorted({*positions}), positions


# ---------------------------------------------------------------------------
# The manifest verify reads
# ---------------------------------------------------------------------------


def test_the_template_manifest_matches_the_schema_verify_reads(template: Path) -> None:
    """The manifest the template ships must parse, and every entry must resolve."""
    _, resolved = meta_mod.load(template)
    entries = verify_mod.load_manifest(template, resolved)
    assert entries
    assert all(entry.declares_expectation for entry in entries)
    assert all(entry.limits == resolved.limits[entry.limits_key] for entry in entries)


def test_the_manifest_declares_the_subjects_the_ticket_requires(template: Path) -> None:
    """Full marks, a fraction, a zero, and a header violation in both languages."""
    _, resolved = meta_mod.load(template)
    entries = {entry.source.name: entry for entry in verify_mod.load_manifest(template, resolved)}
    assert entries["solution.cpp"].verdict == "AC"
    assert entries["solution.cpp"].score == 100
    assert entries["solution.cpp"].role == "model"
    assert entries["solution.c"].verdict == "AC"
    assert entries["solution.c"].score == 100
    assert 0 < entries["solo-chicos.cpp"].score < 100
    assert entries["invalido.cpp"].score == 0
    assert entries["malformado.cpp"].role == "checker-test"
    assert entries["firma-incorrecta.cpp"].verdict == "CE"
    assert entries["firma-incorrecta.c"].verdict == "CE"


def test_the_ce_entries_declare_no_score(template: Path) -> None:
    """A submission the judge never ran has no score to compare against."""
    _, resolved = meta_mod.load(template)
    entries = {entry.source.name: entry for entry in verify_mod.load_manifest(template, resolved)}
    for name in ("firma-incorrecta.cpp", "firma-incorrecta.c"):
        assert entries[name].score is None, name


def test_the_two_language_solutions_are_graded_in_their_own_languages(template: Path) -> None:
    """A ``.c`` entry must go to ``C11``, and a ``.cpp`` one to ``CPP17``.

    Grading the C solution through the C++ executor would still pass -- the code
    compiles as both -- and would therefore prove nothing about the language
    choice, which is what these two entries exist to measure.
    """
    _, resolved = meta_mod.load(template)
    entries = {entry.source.name: entry for entry in verify_mod.load_manifest(template, resolved)}
    assert entries["solution.c"].executor == "C11"
    assert entries["solution.cpp"].executor == "CPP17"
    assert entries["solution.c"].limits_key == ".c"
    assert entries["solution.cpp"].limits_key == ".cpp"


def test_the_partial_submissions_declare_real_fractions_not_full_marks(template: Path) -> None:
    """The fractions come from a run and only pass if the reader measures them."""
    _, resolved = meta_mod.load(template)
    entries = {entry.source.name: entry for entry in verify_mod.load_manifest(template, resolved)}
    for name in ("solo-chicos.cpp", "hasta-2000.cpp"):
        assert entries[name].verdict == "WA", name
        assert 0 < entries[name].score < 100, name


def test_the_manifest_explains_where_the_partial_scores_come_from(template: Path) -> None:
    """The numbers come from a run, and the file has to say so."""
    text = (template / "submissions.yml").read_text(encoding="utf-8")
    assert "verify" in text
    assert "puntaje parcial" in text


def test_the_manifest_explains_the_absent_brute_force(template: Path) -> None:
    """The ticket allows an absence that is explained rather than demonstrated."""
    text = (template / "submissions.yml").read_text(encoding="utf-8")
    assert "exponencial" in text or "subconjuntos" in text


# ---------------------------------------------------------------------------
# The problem is buildable (the real generator, no CLI)
# ---------------------------------------------------------------------------


def _generator_for(problem: Path):
    """The template's generator, loaded the way the toolkit loads it."""
    return cases_mod.load_generator(problem)


def _subtasks(generator):
    """The generator's declared ladder, as the toolkit's own ``Subtask`` values."""
    return [
        cases_mod.Subtask(
            number=number,
            points=entry[0],
            check=entry[1],
            dependencies=tuple(entry[2]) if len(entry) > 2 else (),
        )
        for number, entry in enumerate(generator.get_subtasks(), start=1)
    ]


def test_the_shipped_template_renders_init_yml_with_both_keys(tmp_path: Path) -> None:
    """The real emission against the real template: both keys, and the ladder.

    Run without the CLI so the emitted text is asserted directly: the checker and
    the signature grader are independent decisions (``dmoj/problem.py`` reads each
    key on its own), so a template that lost one would still emit valid YAML.
    """
    destination = tmp_path / MODEL
    shutil.copytree(templates.template_dir(MODEL), destination)
    _, resolved = meta_mod.load(destination)

    generator = _generator_for(destination)
    case_list = generator.get_cases()
    subtasks = _subtasks(generator)
    files = [cases_mod.CaseFile(index=index, has_input=True) for index in range(len(case_list))]
    membership = cases_mod.classify(subtasks, case_list, cases_mod.GENERATOR_FILENAME)

    init = cases_mod.render_init(destination.name, resolved, subtasks, membership, files)
    assert "checker: checker.py" in init
    assert "signature_grader: {entry: evaluator.cpp, header: signature.hpp}" in init
    assert "custom_judge" not in init
    assert init.count("- points:") == 4
    assert init.count("dependencies:") == 1
    assert "dependencies: [2]" in init


def test_the_rendered_ladder_declares_the_dependency_only_where_the_generator_does(
    tmp_path: Path,
) -> None:
    destination = tmp_path / MODEL
    shutil.copytree(templates.template_dir(MODEL), destination)
    _, resolved = meta_mod.load(destination)
    generator = _generator_for(destination)
    case_list = generator.get_cases()
    subtasks = _subtasks(generator)
    files = [cases_mod.CaseFile(index=index, has_input=True) for index in range(len(case_list))]
    membership = cases_mod.classify(subtasks, case_list, cases_mod.GENERATOR_FILENAME)

    document = yaml.safe_load(
        cases_mod.render_init(destination.name, resolved, subtasks, membership, files)
    )
    assert [entry.get("dependencies", []) for entry in document["test_cases"]] == [[], [], [2], []]

"""The ``signature-batched`` template is a complete, buildable signature problem.

The template is the toolkit's only fixture for this model, so what is checked
here is the *contract* ``cases``/``outputs``/``verify`` rely on: the header the
contestant implements, the evaluator the judge compiles against it, the subtask
ladder, the classifiers, and a manifest the schema ``verify`` reads accepts.

What is specific to this model -- and therefore what this file defends that
``test_model_batched.py`` cannot -- is the **composition**.  In a signature
problem the submission is not a program: the judge prefixes it with
``#include "<header>"`` and ``#define main main_<uuid>`` and compiles it together
with the evaluator as one translation unit.  Two consequences are exercised here
with the real ``g++``:

* the shipped model solution, composed the way ``outputs`` composes it, is
  correct by the statement's definition; and
* a submission that violates the header's contract does not compile, which is
  exactly what makes the declared ``verdict: CE`` an assertion about this model
  rather than about a compiler.
"""

from __future__ import annotations

import random
import shutil
import subprocess
from pathlib import Path

import pytest

from problemsetting import cases as cases_mod
from problemsetting import cli
from problemsetting import meta as meta_mod
from problemsetting import outputs as outputs_mod
from problemsetting import templates
from problemsetting import verify as verify_mod

import support

MODEL = "signature-batched"

#: The function the header declares.  Named once: the header, the evaluator, the
#: model solution and the violating submission all have to agree on it, so a test
#: that greps for it is really asking "are these four files still one interface?".
FUNCTION = "subpalindromo"


@pytest.fixture(scope="module")
def template() -> Path:
    return templates.template_dir(MODEL)


@pytest.fixture(scope="module")
def generator_module(template: Path):
    return support.load_module(template / "generator.py", "signature_batched_generator")


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
        "signature.hpp",
        "evaluator.cpp",
        "solution.cpp",
        "submissions.yml",
        "media/statement.md",
        "submissions/cuadratico.cpp",
        "submissions/firma-incorrecta.cpp",
    ):
        assert (template / name).is_file(), name


def test_template_meta_yml_declares_the_signature_batched_model(template: Path) -> None:
    authoring, resolved = meta_mod.load(template)
    assert authoring["model"] == MODEL
    assert resolved.uses_signature, "the template must resolve to the signature grader"
    assert resolved.is_batched, "and to the subtasks axis"
    assert not resolved.uses_checker
    assert resolved.executor == "CPP17"


def test_template_meta_yml_header_matches_meta_HEADER(template: Path) -> None:
    """The template's header is the one users see, so it tracks ``meta.HEADER``."""
    assert (template / "meta.yml").read_text(encoding="utf-8").startswith(meta_mod.HEADER)


# ---------------------------------------------------------------------------
# The interface: header, evaluator, model solution
# ---------------------------------------------------------------------------


def test_the_header_declares_the_function_without_defining_main(template: Path) -> None:
    """The header is the interface, so it declares and nothing else.

    ``signature.py`` renames the *submission's* ``main``, not the header's, and the
    evaluator supplies the only ``main`` the translation unit may contain -- so a
    header that defined one would collide with the evaluator it is compiled
    against.
    """
    header = (template / "signature.hpp").read_text(encoding="utf-8")
    assert f"int {FUNCTION}(const std::string&" in header
    assert "main" not in _code(header), "the header must not define or declare main"


def test_the_header_has_an_include_guard(template: Path) -> None:
    """The judge's prefix includes the header, and the submission may include it too."""
    header = (template / "signature.hpp").read_text(encoding="utf-8")
    assert "#ifndef" in header and "#define" in header and "#endif" in header


def test_the_evaluator_is_the_program_that_calls_the_function(template: Path) -> None:
    """``evaluator.cpp`` owns ``main`` and the I/O; the submission owns the answer."""
    entry = (template / "evaluator.cpp").read_text(encoding="utf-8")
    assert "int main(" in _code(entry), entry
    assert f"{FUNCTION}(" in _code(entry)
    assert "std::cin" in entry and "std::cout" in entry


def test_the_model_solution_is_a_function_not_a_program(template: Path) -> None:
    """The model solution obeys the same contract a contestant does -- no ``main``.

    A model solution with its own ``main`` would prove nothing about the interface
    the problem publishes, and (composed naively) would not even link.
    """
    solution = (template / "solution.cpp").read_text(encoding="utf-8")
    assert f"int {FUNCTION}(const std::string& s)" in solution
    assert "int main(" not in _code(solution), "the model solution must not define main"


def _code(source: str) -> str:
    """``source`` with its comments removed.

    The template's comments *discuss* ``main`` at length -- that is their job -- so
    a plain substring search would report the explanation as a violation.  A block
    comment becomes nothing and a line comment vanishes with its newline, which is
    all these assertions need; this is deliberately not a C++ lexer.
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
    assert [c.s for c in first] == [c.s for c in second]


def test_case_write_file_emits_the_declared_input_format(generator_module) -> None:
    import io

    buffer = io.StringIO()
    generator_module.TestCase("ababa").write_file(buffer)
    assert buffer.getvalue() == "ababa\n"


def test_get_subtasks_yields_points_and_callable_classifiers(generator_module) -> None:
    subtasks = generator_module.Generator().get_subtasks()
    points = 0
    for entry in subtasks:
        assert 2 <= len(entry) <= 3, "entries are (points, check) or (points, check, deps)"
        value, check = entry[0], entry[1]
        assert isinstance(value, (int, float)) and value > 0
        assert callable(check)
        points += value
    assert points == 100
    assert len(subtasks) == 4


def test_the_ladder_is_the_batched_templates_ladder(generator_module) -> None:
    """The two templates are meant to be comparable, so the ladder must match.

    Same points, and ST3 still depends on the batch before it: a reader comparing
    ``signature-batched`` with ``batched`` should find only the interface changed.
    """
    ladder = generator_module.Generator().get_subtasks()
    assert [entry[0] for entry in ladder] == [20, 25, 25, 30]
    assert ladder[2][2] == [2], "ST3 must keep its dependency on ST2"


def test_the_last_subtask_accepts_every_case(generator_module) -> None:
    cases = generator_module.Generator().get_cases()
    assert all(generator_module.check_st4(case) for case in cases)


def test_gen_small_returns_small_cases(generator_module) -> None:
    rand = random.Random(1234)
    cases = generator_module.Generator().gen_small(rand)
    assert cases
    for case in cases:
        assert 1 <= len(case.s) <= 14


# ---------------------------------------------------------------------------
# The composition, with the real compiler
# ---------------------------------------------------------------------------


def _cxx() -> str:
    compiler = shutil.which("g++")
    if compiler is None:
        pytest.skip("g++ is not on PATH")
    return compiler


def _compose(problem_id: str, source: Path, header: Path, entry: Path, destination: Path) -> list[str]:
    """Stage the three translation units exactly as ``outputs`` (and the judge) do.

    Reusing the toolkit's own staging is the point: the test then proves the
    *template* composes, not that a test-local imitation of the judge does.
    """
    layout = outputs_mod.signature_layout(problem_id, ".cpp", entry.name, header.name)
    outputs_mod._stage_signature(source, header, entry, False, layout, destination)
    return [str(destination / name) for name in layout.names]


def _compile(sources: list[str], output: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [_cxx(), "-Wall", *sources, "-DONLINE_JUDGE", "-DSIGNATURE_GRADER", "-O2", "-lm",
         "-std=c++17", "-o", str(output)],
        capture_output=True,
        text=True,
    )


def test_the_model_solution_composes_and_compiles(template: Path, tmp_path: Path) -> None:
    """The shipped solution compiles against the shipped header and evaluator.

    This is the contract failing loudly at author time rather than at grading time:
    if the solution's signature drifts from the header's, the toolkit's own
    ``outputs`` step produces a build error instead of expected outputs.
    """
    sources = _compose(
        "sigdemo",
        template / "solution.cpp",
        template / "signature.hpp",
        template / "evaluator.cpp",
        tmp_path / "staged",
    )
    result = _compile(sources, tmp_path / "solution")
    assert result.returncode == 0, result.stderr


def test_a_stray_main_in_a_conforming_submission_is_renamed_away(
    template: Path, tmp_path: Path
) -> None:
    """The ``#define main main_<uuid>`` the header's comment promises, exercised.

    A contestant who tested the function locally submits a file with its own
    ``main``.  In the judge's composition that ``main`` is renamed by the prefix
    ``signature.py`` adds, so the translation unit keeps exactly one ``main`` --
    the evaluator's -- and the submission still compiles and answers correctly.

    Without the rename the two ``main`` definitions would collide and the
    submission would be a compile error, which is why this is checked rather than
    asserted in prose.  Verified against the real judge as well: this same file
    graded ``AC 76/76`` through a pool container.
    """
    conforming = (
        (template / "solution.cpp").read_text(encoding="utf-8")
        + "\nint main() { return 0; }\n"
    )
    submission = tmp_path / "solution.cpp"
    submission.write_text(conforming, encoding="utf-8")

    sources = _compose(
        "sigdemo",
        submission,
        template / "signature.hpp",
        template / "evaluator.cpp",
        tmp_path / "staged",
    )
    result = _compile(sources, tmp_path / "stray")
    assert result.returncode == 0, result.stderr

    binary = tmp_path / "stray"
    got = subprocess.run(
        [str(binary)], input="ababa\n", capture_output=True, text=True, check=True
    ).stdout
    assert got.strip() == "5"

    # And the rename is what made it work, not luck.  The composed text carries
    # the define, and the same sources compiled *without* the prefix fail: the two
    # ``main`` definitions collide.  The naive copy lives beside the staged header
    # so the only difference from the real build is the prefix itself -- otherwise
    # the include would not resolve and the check would pass for the wrong reason.
    staged_text = (tmp_path / "staged" / "sigdemo_submission.cpp").read_text()
    assert staged_text.startswith('#include "signature.hpp"\n#define main main_')
    prefix = staged_text[: staged_text.index('#define main')]
    naive_submission = tmp_path / "staged" / "naive_submission.cpp"
    naive_submission.write_text(prefix + (template / "solution.cpp").read_text() + "\nint main() { return 0; }\n")
    naive = _compile(
        [
            str(naive_submission),
            str(tmp_path / "staged" / "signature.hpp"),
            str(tmp_path / "staged" / "sigdemocpp.cpp"),
        ],
        tmp_path / "naive",
    )
    assert naive.returncode != 0, "a second main must be rejected without the rename"
    assert "main" in naive.stderr


def test_the_composed_solution_answers_by_the_statements_definition(
    template: Path, tmp_path: Path
) -> None:
    """End to end: the composed program's output is the answer the statement asks for.

    The reference is the definition -- every substring, checked for being a
    palindrome -- so this is not the model solution compared against itself.
    """
    sources = _compose(
        "sigdemo",
        template / "solution.cpp",
        template / "signature.hpp",
        template / "evaluator.cpp",
        tmp_path / "staged",
    )
    binary = tmp_path / "solution"
    result = _compile(sources, binary)
    assert result.returncode == 0, result.stderr

    rand = random.Random(20240920)
    for _ in range(200):
        s = "".join(rand.choice("ab") for _ in range(rand.randint(1, 40)))
        got = subprocess.run(
            [str(binary)], input=s + "\n", capture_output=True, text=True, check=True
        ).stdout
        assert got.strip() == str(_longest_palindrome(s)), f"{s!r}: got {got.strip()}"


def test_a_submission_that_violates_the_header_contract_does_not_compile(
    template: Path, tmp_path: Path
) -> None:
    """The declared ``verdict: CE`` is a property of the interface, not of a run.

    ``firma-incorrecta.cpp`` defines ``subpalindromo`` with the right name and the
    right algorithm but takes its argument by value, so it never defines the
    function the evaluator calls.  Composed the way the judge composes it, the
    translation unit has a declaration with no definition and ``g++`` refuses --
    which is what ``signature.py`` reports as a compile error.
    """
    sources = _compose(
        "sigdemo",
        template / "submissions" / "firma-incorrecta.cpp",
        template / "signature.hpp",
        template / "evaluator.cpp",
        tmp_path / "staged",
    )
    result = _compile(sources, tmp_path / "violating")
    assert result.returncode != 0, "a mismatched signature must not compile"
    assert FUNCTION in result.stderr


def test_the_declared_ce_submission_is_the_only_one_with_a_wrong_signature(
    template: Path,
) -> None:
    """The contrast that makes the CE meaningful.

    ``cuadratico.cpp`` is slow but *conforming*: same signature as the header, so
    it compiles and fails only on time.  The two submissions differ in exactly one
    dimension each, which is why the manifest can declare TLE for one and CE for
    the other.
    """
    conforming = (template / "submissions" / "cuadratico.cpp").read_text(encoding="utf-8")
    violating = (template / "submissions" / "firma-incorrecta.cpp").read_text(encoding="utf-8")
    assert f"int {FUNCTION}(const std::string& s)" in conforming
    assert f"int {FUNCTION}(std::string s)" in violating


def test_no_test_run_writes_into_the_template() -> None:
    """The template directory is package data; nothing here may write into it.

    Two mistakes this guards.  Compiling a template source beside itself would
    leave a binary in the shipped package (and dirty the repository).  Loading an
    author file through ``importlib`` instead of compiling it from source -- which
    ``cases.load_generator`` is explicit about avoiding -- would leave a
    ``__pycache__`` directory there.
    """
    template = templates.template_dir(MODEL)
    strays = sorted(
        path.name
        for path in template.iterdir()
        if path.name
        not in {
            "evaluator.cpp",
            "generator.py",
            "media",
            "meta.yml",
            "signature.hpp",
            "solution.cpp",
            "submissions",
            "submissions.yml",
        }
    )
    assert strays == []


def _longest_palindrome(s: str) -> int:
    """The statement's answer, by the definition -- the reference for the above."""
    best = 0
    for i in range(len(s)):
        for j in range(i, len(s)):
            t = s[i : j + 1]
            if t == t[::-1] and len(t) > best:
                best = len(t)
    return best


# ---------------------------------------------------------------------------
# init.yml: the judge is told to build the signature composition
# ---------------------------------------------------------------------------


def test_cases_emits_the_signature_grader(tmp_path: Path, monkeypatch, capsys) -> None:
    """The emitted ``init.yml`` names the entry and the header, and nothing else.

    ``dmoj/problem.py`` picks ``SignatureGrader`` from the ``signature_grader``
    key alone, so a missing key would silently grade the evaluator as a normal
    program -- the submission would never be compiled.
    """
    assert run(["new", "--model", MODEL, "sig"], monkeypatch, tmp_path) == 0
    assert run(["cases", "sig"], monkeypatch, tmp_path) == 0

    document = cases_mod.load_init(tmp_path / "sig")
    assert document["signature_grader"] == {
        "entry": cases_mod.SIGNATURE_ENTRY,
        "header": cases_mod.SIGNATURE_HEADER,
    }
    assert "checker" not in document
    batches = [entry for entry in document["test_cases"] if "batched" in entry]
    assert [entry["points"] for entry in batches] == [20, 25, 25, 30]
    assert batches[2]["dependencies"] == [2]


# ---------------------------------------------------------------------------
# The CLI scaffolds it (acceptance criterion 1)
# ---------------------------------------------------------------------------


def test_new_scaffolds_a_signature_problem(tmp_path: Path, monkeypatch, capsys) -> None:
    assert run(["new", "--model", MODEL, "sig"], monkeypatch, tmp_path) == 0
    problem = tmp_path / "sig"
    assert (problem / "signature.hpp").is_file()
    assert (problem / "evaluator.cpp").is_file()
    _, resolved = meta_mod.load(problem)
    assert resolved.uses_signature and resolved.is_batched


def test_signature_batched_is_shipped() -> None:
    assert MODEL in templates.shipped()


def test_build_produces_expected_outputs_for_the_composed_solution(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    """``build`` runs the real composition over the real cases.

    Only the small cases are cross-checked: ST1's are at most 50 characters, so the
    definition is affordable, and every larger batch's ``.out`` is the same
    composed program's answer anyway.  What this proves is that the *shipped*
    template, not a fixture, builds and answers correctly through the toolkit.
    """
    assert run(["new", "--model", MODEL, "sig"], monkeypatch, tmp_path) == 0
    assert run(["build", "sig"], monkeypatch, tmp_path) == 0

    problem = tmp_path / "sig"
    expected = {
        index: (problem / "cases" / f"{index}.out").read_text().strip()
        for index in range(10)
    }
    for index, value in expected.items():
        source = (problem / "cases" / f"{index}.in").read_text().strip()
        assert value == str(_longest_palindrome(source)), f"case {index}: {source!r}"


# ---------------------------------------------------------------------------
# The manifest verify reads
# ---------------------------------------------------------------------------


def test_the_template_manifest_matches_the_schema_verify_reads(template: Path) -> None:
    """The manifest the template ships must parse, and every entry must resolve."""
    _, resolved = meta_mod.load(template)
    entries = verify_mod.load_manifest(template, resolved)
    assert entries
    assert all(entry.declares_expectation for entry in entries)
    assert {entry.role for entry in entries} == {"model", None}


def test_the_manifest_declares_a_conforming_solution_and_a_ce_submission(
    template: Path,
) -> None:
    """The two subjects the ticket requires: full marks, and a broken interface."""
    _, resolved = meta_mod.load(template)
    entries = {entry.source.name: entry for entry in verify_mod.load_manifest(template, resolved)}
    assert entries["solution.cpp"].verdict == "AC"
    assert entries["solution.cpp"].score == 100
    assert entries["solution.cpp"].role == "model"
    assert entries["firma-incorrecta.cpp"].verdict == "CE"


def test_the_ce_entry_declares_no_score(template: Path) -> None:
    """A submission the judge never ran has no score to compare against.

    ``verify`` treats any declared ``score`` on an ungraded run as a mismatch --
    ``score: 0`` included, because "earned nothing" is not the same as "never
    graded" -- so the verdict is the whole assertion.
    """
    _, resolved = meta_mod.load(template)
    entries = {entry.source.name: entry for entry in verify_mod.load_manifest(template, resolved)}
    assert entries["firma-incorrecta.cpp"].score is None

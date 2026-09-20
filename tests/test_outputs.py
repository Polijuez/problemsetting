"""``outputs``: compiling and running the model solution to produce ``cases/*.out``.

These tests run the *real* toolchains.  They are the toolkit's own proof that the
commands it issues are the judge's commands, so mocking a compiler would defeat
the point -- the previous toolkit's bug (composing a signature submission the
judge never builds) is exactly the kind that a fake compiler cannot catch.

They are therefore skipped when the toolchain is absent: the C/C++/Haskell/Python
tests need ``gcc``/``g++``/``ghc``/``python3``, and the Java test needs ``javac``
(either on PATH or in ``$JAVA_HOME/bin``).
"""

from __future__ import annotations


import os
import shutil
import textwrap
from pathlib import Path

import pytest
import yaml

from problemsetting import cases as cases_mod
from problemsetting import cli
from problemsetting import meta as meta_mod
from problemsetting import outputs as outputs_mod
from problemsetting.errors import OutputError

#: Every fixture's model solution is the correct A+B: a test that only checks
#: whether a file appeared is still better off with a right answer, because the
#: same fixture then defends the value as well as the plumbing.
SOLUTIONS = {
    ".cpp": (
        "#include <iostream>\nint main(){long long a,b;std::cin>>a>>b;"
        "std::cout<<a+b<<'\\n';}\n"
    ),
    ".c": (
        '#include <stdio.h>\nint main(void){long long a,b;'
        'scanf("%lld %lld",&a,&b);printf("%lld\\n",a+b);return 0;}\n'
    ),
    ".py": "import sys\na, b = map(int, sys.stdin.read().split())\nprint(a + b)\n",
    ".hs": (
        "main :: IO ()\nmain = do\n"
        "    [a, b] <- (map read . words) <$> getContents\n"
        "    print (a + b :: Integer)\n"
    ),
    ".java": (
        "import java.util.Scanner;\npublic class Solution {\n"
        "  public static void main(String[] args) {\n"
        "    Scanner s = new Scanner(System.in);\n"
        "    System.out.println(s.nextLong() + s.nextLong());\n  }\n}\n"
    ),
    ".txt": "the answer\n",
}


GENERATOR = """
    class TestCase:
        def __init__(self, a, b):
            self.a = a
            self.b = b

        def check(self):
            pass

        def write_file(self, file):
            file.write(f"{self.a} {self.b}\\n")

    class Generator:
        def __init__(self, seed=1):
            pass

        def get_cases(self):
            return [TestCase(2, 3), TestCase(10**9, 10**9)]

        def get_subtasks(self):
            return [(100, lambda case: True)]
"""


def run(argv: list[str], monkeypatch, cwd: Path) -> int:
    monkeypatch.chdir(cwd)
    return cli.main(argv)


def write_problem(root: Path, name: str, *, solutionlang: str, extra: dict[str, str] | None = None,
                  overrides: dict[str, str] | None = None, model: str = "standard") -> Path:
    problem = root / name
    problem.mkdir(parents=True)
    authoring = {"model": model, "solutionlang": solutionlang}
    authoring.update(overrides or {})
    meta_mod.write(problem, meta_mod.normalize(authoring, f"{name}/meta.yml"))
    (problem / cases_mod.GENERATOR_FILENAME).write_text(textwrap.dedent(GENERATOR))
    (problem / f"solution{solutionlang}").write_text(SOLUTIONS[solutionlang])

    for filename, content in (extra or {}).items():
        (problem / filename).write_text(content)
    return problem


def have(*commands: str) -> bool:
    """Whether every command is runnable, on PATH or in ``$JAVA_HOME/bin``."""
    home = os.environ.get("JAVA_HOME")
    for command in commands:
        if shutil.which(command) is not None:
            continue
        if home is not None and shutil.which(command, path=str(Path(home) / "bin")) is not None:
            continue
        return False
    return True


# ---------------------------------------------------------------------------
# Every language the toolkit claims to run
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("solutionlang", "commands"),
    [
        (".cpp", ("g++",)),
        (".c", ("gcc",)),
        (".py", ("python3",)),
        (".hs", ("ghc",)),
        (".java", ("javac", "java")),
    ],
)
def test_outputs_work_for_every_language(
    tmp_path, monkeypatch, capsys, solutionlang: str, commands: tuple[str, ...]
) -> None:
    """The acceptance criterion, in one test: C, C++, Java, Python and Haskell each
    compile and run, and each produces the *correct* answer -- including 2·10⁹,
    which is the case that catches a 32-bit `int` in any of the five."""
    if not have(*commands):
        pytest.skip(f"needs {', '.join(commands)}")
    problem = write_problem(tmp_path, "demo", solutionlang=solutionlang)

    assert run(["cases", "demo"], monkeypatch, tmp_path) == 0
    assert run(["outputs", "demo"], monkeypatch, tmp_path) == 0

    assert sorted(path.name for path in problem.glob("cases/*.out")) == ["0.out", "1.out"]
    assert (problem / "cases" / "0.out").read_text() == "5\n"
    assert (problem / "cases" / "1.out").read_text() == "2000000000\n"


# ---------------------------------------------------------------------------
# A failure must never leave a gradeable artifact (the dangerous one)
# ---------------------------------------------------------------------------


def test_a_compile_failure_deletes_the_expected_outputs(tmp_path, monkeypatch, capsys) -> None:
    """The worst silent-correctness bug: a stale `.out` graded as the answer.

    The sequence is the dangerous one -- build once, then break the solution --
    because that is when a careless implementation leaves the *previous* expected
    output in place and the judge happily grades it.
    """
    if not have("g++"):
        pytest.skip("needs g++")
    problem = write_problem(tmp_path, "demo", solutionlang=".cpp")
    (problem / "solution.cpp").write_text(
        "#include <iostream>\nint main(){long long a,b;std::cin>>a>>b;std::cout<<a+b<<'\\n';}\n"
    )
    assert run(["cases", "demo"], monkeypatch, tmp_path) == 0
    assert run(["outputs", "demo"], monkeypatch, tmp_path) == 0
    assert (problem / "cases" / "0.out").read_text() == "5\n"
    capsys.readouterr()

    (problem / "solution.cpp").write_text("int main() { this is not C++ }\n")
    assert run(["outputs", "demo"], monkeypatch, tmp_path) == 1

    out, err = capsys.readouterr()
    # The compiler's own diagnostics are shown, not swallowed.
    assert "error:" in err
    assert "not C++" in err or "expected" in err
    # Nothing is left that the judge could grade as an answer.
    assert not list(problem.glob("cases/*.out"))
    assert not list(problem.glob("cases/*.part"))
    # And `archive` refuses rather than bundling an incomplete problem.
    assert run(["archive", "demo"], monkeypatch, tmp_path) == 1
    assert not (problem / "demo.zip").exists()
    # `outputs` itself reported only what it managed.
    assert "0 of 2" in err


def test_a_failure_discards_the_previous_archive(tmp_path, monkeypatch, capsys) -> None:
    """The zip is what the site deploys, so it cannot outlive the answers it holds.

    This is the subtler half of the stale-output bug: deleting `cases/*.out` is not
    enough, because ``ProblemDataManager`` reads each case's answer out of the
    archive when one is declared.  A zip left behind by the last successful build
    would therefore ship exactly the answers a failed rebuild just refused.

    Two triggers are exercised, because they take different paths through the
    cleanup: breaking the solution (loose outputs still exist, so they are
    invalidated here) and retuning the generator first (``cases`` deletes the
    stale outputs itself, so ``outputs`` finds nothing to invalidate -- the case a
    guard on "did we delete anything" would have missed).
    """
    if not have("g++"):
        pytest.skip("needs g++")
    problem = write_problem(tmp_path, "demo", solutionlang=".cpp")
    assert run(["build", "demo"], monkeypatch, tmp_path) == 0
    archive = problem / "demo.zip"
    assert archive.is_file()
    capsys.readouterr()

    (problem / "solution.cpp").write_text("int main() { this is not C++ }\n")
    assert run(["outputs", "demo"], monkeypatch, tmp_path) == 1
    assert "archive was discarded" in capsys.readouterr().err
    assert not archive.exists(), "a stale zip would deploy the rejected answers"


def test_a_retuned_generator_still_discards_the_archive(tmp_path, monkeypatch, capsys) -> None:
    """Every case's input changing must not let the old zip survive.

    `cases` unlinks a case's `.out` when its input changed, so by the time
    `outputs` fails there is nothing left for it to invalidate -- and a cleanup
    conditioned on having removed something would leave the previous archive on
    disk, shipping answers that do not match the cases the judge now reads.
    """
    if not have("g++"):
        pytest.skip("needs g++")
    problem = write_problem(tmp_path, "demo", solutionlang=".cpp")
    assert run(["build", "demo"], monkeypatch, tmp_path) == 0
    archive = problem / "demo.zip"
    assert archive.is_file()
    capsys.readouterr()

    # Retune the generator so every input changes, and break the solution.
    (problem / cases_mod.GENERATOR_FILENAME).write_text(
        textwrap.dedent(GENERATOR).replace("TestCase(2, 3)", "TestCase(1000, 0)")
        .replace("TestCase(10**9, 10**9)", "TestCase(2000, 0)")
    )
    (problem / "solution.cpp").write_text("int main() { this is not C++ }\n")
    capsys.readouterr()

    assert run(["build", "demo"], monkeypatch, tmp_path) == 1
    assert not archive.exists(), "a stale zip would deploy the rejected answers"
    assert not list(problem.glob("cases/*.out"))


def test_a_failure_after_a_successful_build_discards_everything_stale(
    tmp_path, monkeypatch, capsys
) -> None:
    """The dangerous sequence, for a language whose product is a *directory*.

    Java and the signature staging write into a directory (`javac -d`, the staged
    translation units), so a cleanup that assumed a file product raised
    `IsADirectoryError` on exactly this sequence -- leaving both the stale
    expected outputs and a gradeable archive behind.  Both compilers are covered
    because both node kinds have directory products.
    """
    if not have("g++"):
        pytest.skip("needs g++")
    problem = write_problem(tmp_path, "demo", solutionlang=".cpp")
    assert run(["build", "demo"], monkeypatch, tmp_path) == 0
    capsys.readouterr()

    # Break it after a successful build, so every artifact already exists.
    (problem / "solution.cpp").write_text("int main() { this is not C++ }\n")
    assert run(["outputs", "demo"], monkeypatch, tmp_path) == 1

    err = capsys.readouterr().err
    # The compiler's own diagnostics, not a traceback from the cleanup path.
    assert "error:" in err and "Traceback" not in err
    assert not list(problem.glob("cases/*.out"))
    assert not (problem / "demo.zip").exists()


def test_a_java_compile_failure_is_reported_and_discarded(tmp_path, monkeypatch, capsys) -> None:
    """`javac`'s product is a directory; the failure path must still clean up."""
    if not have("javac", "java"):
        pytest.skip("needs javac, java")
    problem = write_problem(tmp_path, "demo", solutionlang=".java")
    assert run(["build", "demo"], monkeypatch, tmp_path) == 0
    assert (problem / "cases" / "0.out").read_text() == "5\n"
    capsys.readouterr()

    (problem / "solution.java").write_text("public class Solution { syntax error here }\n")
    assert run(["outputs", "demo"], monkeypatch, tmp_path) == 1

    err = capsys.readouterr().err
    assert "error:" in err and "Traceback" not in err
    assert "javac" in err
    assert not list(problem.glob("cases/*.out"))
    assert not (problem / "demo.zip").exists()


def test_a_runtime_failure_keeps_the_outputs_that_are_still_valid(
    tmp_path, monkeypatch, capsys
) -> None:
    """A case that crashes must not delete the answers of the cases that passed."""
    if not have("g++"):
        pytest.skip("needs g++")
    problem = write_problem(tmp_path, "demo", solutionlang=".cpp")
    # Fails only on the second case (10^9 10^9).
    (problem / "solution.cpp").write_text(
        "#include <iostream>\nint main(){long long a,b;std::cin>>a>>b;"
        "if(a==1000000000){return 3;}std::cout<<a+b<<'\\n';}\n"
    )
    assert run(["cases", "demo"], monkeypatch, tmp_path) == 0
    assert run(["outputs", "demo"], monkeypatch, tmp_path) == 1

    err = capsys.readouterr().err
    assert "status 3" in err and "1.out" in err
    # The case that succeeded keeps its (correct) answer; the failing one has none.
    assert (problem / "cases" / "0.out").read_text() == "5\n"
    assert not (problem / "cases" / "1.out").exists()


# ---------------------------------------------------------------------------
# Incrementality
# ---------------------------------------------------------------------------


def test_a_second_run_rebuilds_nothing(tmp_path, monkeypatch, capsys) -> None:
    """Unchanged solution + unchanged cases: no recompile, no rerun."""
    if not have("g++"):
        pytest.skip("needs g++")
    problem = write_problem(tmp_path, "demo", solutionlang=".cpp")
    assert run(["cases", "demo"], monkeypatch, tmp_path) == 0
    assert run(["outputs", "demo"], monkeypatch, tmp_path) == 0
    outputs = sorted(problem.glob("cases/*.out"))
    stamps = {path: path.stat().st_mtime_ns for path in outputs}
    capsys.readouterr()

    assert run(["outputs", "demo"], monkeypatch, tmp_path) == 0
    out = capsys.readouterr().out
    assert "already up to date" in out
    # The strong form: neither the outputs nor the binary were touched at all.
    assert {path: path.stat().st_mtime_ns for path in outputs} == stamps



def test_editing_one_case_only_reruns_that_case(tmp_path, monkeypatch, capsys) -> None:
    if not have("g++"):
        pytest.skip("needs g++")
    problem = write_problem(tmp_path, "demo", solutionlang=".cpp")
    assert run(["cases", "demo"], monkeypatch, tmp_path) == 0
    assert run(["outputs", "demo"], monkeypatch, tmp_path) == 0
    untouched = (problem / "cases" / "1.out").stat().st_mtime_ns
    capsys.readouterr()

    (problem / "cases" / "0.in").write_text("7 8\n")
    assert run(["outputs", "demo"], monkeypatch, tmp_path) == 0
    out = capsys.readouterr().out
    assert "1 of 2" in out
    assert (problem / "cases" / "0.out").read_text() == "15\n"
    # The case whose input did not change was not rerun.
    assert (problem / "cases" / "1.out").stat().st_mtime_ns == untouched


def test_editing_the_solution_reruns_every_case(tmp_path, monkeypatch, capsys) -> None:
    if not have("g++"):
        pytest.skip("needs g++")
    problem = write_problem(tmp_path, "demo", solutionlang=".cpp")
    assert run(["cases", "demo"], monkeypatch, tmp_path) == 0
    assert run(["outputs", "demo"], monkeypatch, tmp_path) == 0
    capsys.readouterr()

    (problem / "solution.cpp").write_text(SOLUTIONS[".cpp"] + "\n// changed\n")
    assert run(["outputs", "demo"], monkeypatch, tmp_path) == 0
    assert "2 expected output(s)" in capsys.readouterr().out


def test_the_cache_is_a_gitignored_build_artifact(tmp_path, monkeypatch) -> None:
    if not have("g++"):
        pytest.skip("needs g++")
    problem = write_problem(tmp_path, "demo", solutionlang=".cpp")
    assert run(["cases", "demo"], monkeypatch, tmp_path) == 0
    assert run(["outputs", "demo"], monkeypatch, tmp_path) == 0
    cache = problem / outputs_mod.ARTIFACTS_ROOT / outputs_mod.CACHE_FILENAME
    assert cache.is_file()
    # `__meta__` is what `.gitignore` covers, so nothing here is ever committed.
    root = Path(__file__).resolve().parent.parent
    assert "__meta__" in (root / ".gitignore").read_text()


# ---------------------------------------------------------------------------
# Signature composition: the judge builds a specific program, not a close one
# ---------------------------------------------------------------------------


SIGNATURE_GENERATOR = """
    class TestCase:
        def __init__(self, value):
            self.value = value

        def check(self):
            pass

        def write_file(self, file):
            file.write(f"{self.value}\\n")

    class Generator:
        def __init__(self, seed=1):
            pass

        def get_cases(self):
            return [TestCase(2), TestCase(5)]

        def get_subtasks(self):
            return [(100, lambda case: True)]
"""


@pytest.mark.parametrize(
    ("extension", "commands"),
    [(".cpp", ("g++",)), (".c", ("gcc",))],
)
def test_signature_composition_matches_the_judge(
    tmp_path, monkeypatch, capsys, extension: str, commands: tuple[str, ...]
) -> None:
    """The composed program is the judge's, which is *not* `gcc solution eval`.

    The fixture is built so the two compositions disagree observably:

    * the model solution defines its own ``main``, which DMOJ's
      ``#define main main_<uuid>`` renames away and a naive build leaves as a
      second definition;
    * it omits the header include, relying on the prefix DMOJ adds;
    * and its body branches on ``SIGNATURE_GRADER``, the define DMOJ passes.

    So a naive composition either fails to build or answers differently, while
    the composed one must produce the true answers.
    """
    if not have(*commands):
        pytest.skip(f"needs {', '.join(commands)}")
    problem = write_problem(
        tmp_path,
        "demo",
        solutionlang=extension,
        model="signature-batched",
        overrides={"batch": "subtasks", "grader": "signature"},
        extra={
            cases_mod.GENERATOR_FILENAME: textwrap.dedent(SIGNATURE_GENERATOR),
            "signature.hpp": "#pragma once\n\nint scale(int n);\n",
            "evaluator.cpp": (
                '#include "signature.hpp"\n#include <stdio.h>\n'
                'int main(void){int n;if(scanf("%d",&n)!=1)return 1;'
                'printf("%d\\n",scale(n));return 0;}\n'
            ),
        },
    )
    (problem / f"solution{extension}").write_text(
        "#ifdef SIGNATURE_GRADER\n"
        "int scale(int n) { return n * 10; }\n"
        "#else\n"
        "int scale(int n) { return n * 11; }\n"
        "#endif\n"
        "int main(void) { return 0; }\n"
    )

    assert run(["cases", "demo"], monkeypatch, tmp_path) == 0
    assert run(["outputs", "demo"], monkeypatch, tmp_path) == 0

    # The judge's answer: 2*10 and 5*10.  A naive build gives 22 and 55.
    assert (problem / "cases" / "0.out").read_text() == "20\n"
    assert (problem / "cases" / "1.out").read_text() == "50\n"


def test_signature_staged_names_are_the_judges() -> None:
    """The staged file names come from ``CLikeExecutor``, not from intuition.

    Verified against the judge itself (``C11`` reports
    ``myproblem_submission.c``, ``signature.hpp``, ``myproblemc.c``): the entry is
    renamed after the problem id with a **dotless** executor extension, and the
    header keeps its own name.  Those suffixes decide each file's language.
    """
    layout = outputs_mod.signature_layout("myproblem", ".c", "evaluator.cpp", "signature.hpp")
    assert layout.names == ("myproblem_submission.c", "signature.hpp", "myproblemc.c")
    assert layout.include == '#include "signature.hpp"'

    layout = outputs_mod.signature_layout("p", ".cpp", "ev.cpp", "sig.hpp")
    assert layout.names == ("p_submission.cpp", "sig.hpp", "pcpp.cpp")


def test_signature_prefix_is_the_graders(tmp_path) -> None:
    """The composed text is the include, the rename, then the submission.

    That is ``signature.py:20-24`` exactly, and the staged names are the ones
    ``CLikeExecutor`` reports (checked against the judge itself).
    """
    layout = outputs_mod.signature_layout("demo", ".cpp", "evaluator.cpp", "signature.hpp")
    source = "int f() { return 1; }\n"
    header_text = "int f();\n"
    entry_text = "int main() { return 0; }\n"
    (tmp_path / "solution.cpp").write_text(source)
    (tmp_path / "signature.hpp").write_text(header_text)
    (tmp_path / "evaluator.cpp").write_text(entry_text)

    outputs_mod._stage_signature(
        tmp_path / "solution.cpp",
        tmp_path / "signature.hpp",
        tmp_path / "evaluator.cpp",
        False,
        layout,
        tmp_path / "staged",
    )

    composed = (tmp_path / "staged" / "demo_submission.cpp").read_text()
    assert composed.startswith('#include "signature.hpp"\n#define main main_')
    assert composed.endswith(source)
    # The header and the entry are staged verbatim, under the judge's names.
    assert (tmp_path / "staged" / "signature.hpp").read_text() == header_text
    assert (tmp_path / "staged" / "democpp.cpp").read_text() == entry_text


def test_allow_main_skips_the_rename(tmp_path) -> None:
    """`signature_grader.allow_main` is honoured: the judge only renames when it is absent."""
    layout = outputs_mod.signature_layout("demo", ".cpp", "evaluator.cpp", "signature.hpp")
    (tmp_path / "solution.cpp").write_text("int main() { return 0; }\n")
    (tmp_path / "signature.hpp").write_text("int f();\n")
    (tmp_path / "evaluator.cpp").write_text("int main() { return 0; }\n")

    outputs_mod._stage_signature(
        tmp_path / "solution.cpp",
        tmp_path / "signature.hpp",
        tmp_path / "evaluator.cpp",
        True,
        layout,
        tmp_path / "staged",
    )

    composed = (tmp_path / "staged" / "demo_submission.cpp").read_text()
    assert composed == '#include "signature.hpp"\nint main() { return 0; }\n'


# ---------------------------------------------------------------------------
# Output-only models: the answer is copied, never compiled
# ---------------------------------------------------------------------------

#: Output-only cases have no input at all, so `write_file` must never be called
#: (``dmoj/problem.py:489-493`` supplies empty stdin).  The generator asserts that
#: rather than writing, so a toolkit that tried to render an input fails loudly.
NO_INPUT_GENERATOR = """
    class TestCase:
        def __init__(self, value):
            self.value = value

        def check(self):
            pass

        def write_file(self, file):
            raise AssertionError("output-only cases have no input to write")

    class Generator:
        def __init__(self, seed=1):
            pass

        def get_cases(self):
            return [TestCase(1), TestCase(2)]

        def get_subtasks(self):
            return [(100, lambda case: True)]
"""


def write_output_only(tmp_path: Path, name: str = "demo") -> Path:
    problem = write_problem(
        tmp_path,
        name,
        solutionlang=".txt",
        model="output-only",
        extra={cases_mod.GENERATOR_FILENAME: textwrap.dedent(NO_INPUT_GENERATOR)},
    )
    return problem


def test_output_only_copies_the_solution_instead_of_running_it(
    tmp_path, monkeypatch, capsys
) -> None:
    """The expected output is the model solution's text, byte for byte."""
    problem = write_output_only(tmp_path)
    (problem / "solution.txt").write_text("the answer\n")

    assert run(["cases", "demo"], monkeypatch, tmp_path) == 0
    assert run(["outputs", "demo"], monkeypatch, tmp_path) == 0
    assert "copying the model solution" in capsys.readouterr().out

    assert (problem / "cases" / "0.out").read_text() == "the answer\n"
    assert (problem / "cases" / "1.out").read_text() == "the answer\n"
    # `init.yml` declares no inputs, and none were written.
    assert not list(problem.glob("cases/*.in"))
    document = yaml.safe_load((problem / cases_mod.INIT_FILENAME).read_text())
    for entry in document["test_cases"][0]["batched"]:
        assert "in" not in entry


def test_an_output_only_problem_cannot_run_out_of_date(tmp_path, monkeypatch) -> None:
    """Re-editing the text re-copies it: the copy must never be stale either."""
    problem = write_output_only(tmp_path)
    (problem / "solution.txt").write_text("first\n")
    assert run(["cases", "demo"], monkeypatch, tmp_path) == 0
    assert run(["outputs", "demo"], monkeypatch, tmp_path) == 0
    assert (problem / "cases" / "0.out").read_text() == "first\n"

    (problem / "solution.txt").write_text("second\n")
    assert run(["outputs", "demo"], monkeypatch, tmp_path) == 0
    assert (problem / "cases" / "0.out").read_text() == "second\n"
    assert (problem / "cases" / "1.out").read_text() == "second\n"



# ---------------------------------------------------------------------------
# Executor → host toolchain resolution
# ---------------------------------------------------------------------------


def test_std_flags_follow_the_executor_axis() -> None:
    """`.cpp` is CPP17 and `.c` is C11 (Q19); an override changes the standard."""
    default = meta_mod.resolve({"model": "standard", "solutionlang": ".cpp"})
    assert default.executor == "CPP17"
    assert outputs_mod.TOOLSPECS[default.executor].std == "c++17"

    c = meta_mod.resolve({"model": "standard", "solutionlang": ".c"})
    assert c.executor == "C11"
    assert outputs_mod.TOOLSPECS[c.executor].std == "c11"

    overridden = meta_mod.resolve(
        {"model": "standard", "solutionlang": ".cpp", "executor": "CPP23"}
    )
    assert overridden.executor == "CPP23"
    assert outputs_mod.TOOLSPECS[overridden.executor].std == "c++23"


def test_every_executor_a_model_solution_can_use_has_a_host_toolchain() -> None:
    """A missing row would be a hole in the executor table, not a runtime surprise."""
    for extension, executor in meta_mod.EXECUTOR_BY_EXT.items():
        if executor == "TEXT":
            continue  # output-only: copied, never compiled, so no toolchain at all
        assert executor in outputs_mod.TOOLSPECS, executor
    assert meta_mod.FAMILY_BY_EXT.keys() >= {".c", ".cpp", ".hs", ".java", ".py"}


def test_a_java_solution_without_a_public_class_is_an_authoring_error(tmp_path) -> None:
    """`javac` compiles by class name, so guessing one would compile the wrong file."""
    source = tmp_path / "Bad.java"
    source.write_text("class NotPublic { }\n")
    with pytest.raises(OutputError, match="no public class"):
        outputs_mod.java_class_name(source)


def test_java_class_name_is_read_out_of_comments_correctly(tmp_path) -> None:
    """`public class` inside a comment or a string must not fool the search.

    The judge strips comments and literals before searching
    (``java_executor.py:find_class``); a toolkit that did not would compile a file
    named after a class that does not exist.
    """
    source = tmp_path / "S.java"
    source.write_text(
        "// public class NotThis { }\n"
        "/* public class NorThis { } */\n"
        'String s = "public class AlsoNotThis";\n'
        "public class Real { }\n"
    )
    assert outputs_mod.java_class_name(source) == "Real"


def test_a_packaged_java_solution_is_rejected(tmp_path) -> None:
    source = tmp_path / "P.java"
    source.write_text("package foo.bar;\npublic class P { }\n")
    with pytest.raises(OutputError, match="package"):
        outputs_mod.java_class_name(source)


# ---------------------------------------------------------------------------
# The graph itself
# ---------------------------------------------------------------------------


def test_case_pairs_are_deduplicated_by_output() -> None:
    """A case selected by two subtasks is one expected output, not two runs."""
    document = {
        "test_cases": [
            {"points": 30, "batched": [{"in": "cases/0.in", "out": "cases/0.out"}]},
            {
                "points": 70,
                "batched": [
                    {"in": "cases/0.in", "out": "cases/0.out"},
                    {"in": "cases/1.in", "out": "cases/1.out"},
                ],
            },
        ]
    }
    assert cases_mod.case_pairs(document, "init.yml") == [
        ("cases/0.in", "cases/0.out"),
        ("cases/1.in", "cases/1.out"),
    ]


def test_a_fingerprint_changes_with_its_dependencies() -> None:
    """The cache's whole contract: same inputs, same fingerprint; else different."""
    first = outputs_mod.Node(key="a", product=None, recipe="recipe")
    second = outputs_mod.Node(key="b", product=None, recipe="recipe", deps=(first,))
    assert second.fingerprint() == outputs_mod.Node(
        key="b", product=None, recipe="recipe", deps=(first,)
    ).fingerprint()
    assert second.fingerprint() != outputs_mod.Node(
        key="b",
        product=None,
        recipe="recipe",
        deps=(outputs_mod.Node(key="a", product=None, recipe="other"),),
    ).fingerprint()
    assert second.fingerprint() != outputs_mod.Node(
        key="b", product=None, recipe="other", deps=(first,)
    ).fingerprint()


def test_a_corrupt_cache_is_ignored_rather_than_trusted(tmp_path) -> None:
    """The cache is a build artifact: unreadable means rebuild, never misread."""
    cache = tmp_path / "cache.json"
    assert outputs_mod.read_cache(cache) == {}
    cache.write_text("not json at all")
    assert outputs_mod.read_cache(cache) == {}
    cache.write_text('{"version": 999, "targets": {"a": "b"}}')
    assert outputs_mod.read_cache(cache) == {}
    outputs_mod.write_cache(cache, {"cases/0.out": "abc"})
    assert outputs_mod.read_cache(cache) == {"cases/0.out": "abc"}


def test_resolve_tools_reports_a_missing_toolchain_actionably(monkeypatch) -> None:
    """A missing compiler names the language and the executor, not a bare OSError."""
    resolved = meta_mod.resolve({"model": "standard", "solutionlang": ".cpp"})
    monkeypatch.setattr(shutil, "which", lambda *args, **kwargs: None)
    with pytest.raises(OutputError, match="no compiler for a .cpp model solution"):
        outputs_mod.resolve_tools(resolved)

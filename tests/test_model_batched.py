"""The ``batched`` template is a complete, buildable problem with subtasks.

The template is the toolkit's only fixture for this model, so what it is checked
for here is the *contract* ``cases``/``verify`` rely on: the subtask ladder with
its points and dependency, the all-accepting last batch, the case classifiers,
and a manifest that the schema ``verify`` reads accepts.
"""

from __future__ import annotations

import io
import random
import shutil
import subprocess
import tempfile
import types
from pathlib import Path

import pytest

from problemsetting import meta as meta_mod
from problemsetting import templates

MODEL = "batched"


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
    return load_module("batched_generator", template / "generator.py")


def test_template_ships_the_whole_problem(template: Path) -> None:
    for name in (
        "meta.yml",
        "generator.py",
        "solution.cpp",
        "submissions.yml",
        "media/statement.md",
    ):
        assert (template / name).is_file(), name
    assert list((template / "submissions").glob("*.py"))


def test_template_meta_yml_declares_the_batched_model(template: Path) -> None:
    authoring, resolved = meta_mod.load(template)
    assert authoring["model"] == MODEL
    assert resolved.is_batched, "the batched template must resolve to the subtasks axis"
    assert not resolved.uses_checker and not resolved.uses_signature
    assert resolved.executor == "CPP17"


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
    buffer = io.StringIO()
    generator_module.TestCase("ababa").write_file(buffer)
    assert buffer.getvalue() == "ababa\n"


def test_case_check_rejects_invalid_cases(generator_module) -> None:
    limit = generator_module.LIM_ST4
    with pytest.raises(AssertionError):
        generator_module.TestCase("")
    with pytest.raises(AssertionError):
        generator_module.TestCase("a" * (limit + 1))
    with pytest.raises(AssertionError):
        generator_module.TestCase("abcz")  # outside the statement's alphabet
    generator_module.TestCase("a" * limit)  # boundary is fine


def test_get_subtasks_yields_points_and_callable_classifiers(generator_module) -> None:
    subtasks = generator_module.Generator().get_subtasks()
    assert subtasks, "a problem with no subtasks has nothing to grade"
    points = 0
    for entry in subtasks:
        assert 2 <= len(entry) <= 3, "entries are (points, check) or (points, check, deps)"
        value, check = entry[0], entry[1]
        assert isinstance(value, (int, float)) and value > 0
        assert callable(check)
        points += value
        if len(entry) == 3:
            assert all(isinstance(dep, int) and dep > 0 for dep in entry[2])
    # Subtask points sum to 100: the problem's total, so `score` in
    # submissions.yml is a plain percentage.
    assert points == 100
    assert len(subtasks) == 4


def test_the_ladder_is_ordered_by_constraints_on_n(generator_module) -> None:
    """Each bound is a superset of the previous one: cases accumulate upward."""
    assert (
        generator_module.LIM_ST1
        < generator_module.LIM_ST2
        < generator_module.LIM_ST3
        < generator_module.LIM_ST4
    )


def test_the_last_subtask_accepts_every_case(generator_module) -> None:
    """The convention init.yml emission relies on: the last check is all-accepting.

    Without it the largest cases would fall outside every batch and be dropped.
    """
    cases = generator_module.Generator().get_cases()
    assert all(generator_module.check_st4(case) for case in cases)


def test_subtask_classifiers_partition_the_cases(generator_module) -> None:
    cases = generator_module.Generator().get_cases()
    sizes = [
        sum(1 for case in cases if generator_module.check_st1(case)),
        sum(1 for case in cases if generator_module.check_st2(case)),
        sum(1 for case in cases if generator_module.check_st3(case)),
        sum(1 for case in cases if generator_module.check_st4(case)),
    ]
    assert sizes == sorted(sizes) and all(size > 0 for size in sizes), sizes
    # Every batch must select at least one *exclusive* case; otherwise a batch
    # would be a duplicate of its predecessor and could never fail alone.
    assert sizes[0] < sizes[1] < sizes[2] < sizes[3]


def test_at_least_one_subtask_declares_a_dependency(generator_module) -> None:
    """The `dependencies` mechanism is exercised by a real template, not just documented."""
    subtasks = generator_module.Generator().get_subtasks()
    declared = [index for index, entry in enumerate(subtasks, 1) if len(entry) == 3]
    assert declared, "no subtask declares dependencies"
    for number in declared:
        entry = subtasks[number - 1]
        assert all(dep < number for dep in entry[2]), "a batch may only depend on earlier batches"


def test_gen_small_returns_small_cases(generator_module) -> None:
    rand = random.Random(1234)
    cases = generator_module.Generator().gen_small(rand)
    assert cases
    for case in cases:
        assert 1 <= len(case.s) <= 14


# ---------------------------------------------------------------------------
# The model solution
# ---------------------------------------------------------------------------


def test_model_solution_agrees_with_a_reference_on_small_inputs(template: Path) -> None:
    """Compile ``solution.cpp`` and check it against brute force on random small cases.

    The pairing that matters is solution-vs-statement: a model solution that is
    wrong would produce wrong ``.out`` files, which is the failure that silently
    poisons every submission.  Small random inputs are enough to catch it, and
    they run in milliseconds.
    """
    binary = compile_solution(template / "solution.cpp")
    rand = random.Random(99)
    for _ in range(200):
        n = rand.randint(1, 40)
        s = "".join(rand.choice("ab") for _ in range(n))
        expected = longest_palindrome(s)
        got = subprocess.run([binary], input=s + "\n", capture_output=True, text=True).stdout
        assert got.strip() == str(expected), f"{s!r}: expected {expected}, got {got.strip()}"


def compile_solution(source: Path) -> str:
    """Compile the model solution into a temp directory, never beside its source."""
    compiler = shutil.which("g++")
    if compiler is None:
        pytest.skip("g++ is not on PATH")
    binary = Path(tempfile.mkdtemp()) / "solution"
    subprocess.run(
        [compiler, "-O2", "-std=c++17", "-o", str(binary), str(source)],
        check=True,
        capture_output=True,
    )
    return str(binary)


def longest_palindrome(s: str) -> int:
    """The statement's answer, by the definition -- the reference for the above."""
    best = 0
    for i in range(len(s)):
        for j in range(i, len(s)):
            t = s[i : j + 1]
            if t == t[::-1] and len(t) > best:
                best = len(t)
    return best


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
        if path.name
        not in {"generator.py", "media", "meta.yml", "solution.cpp", "submissions.yml", "submissions"}
    )
    assert strays == []


# ---------------------------------------------------------------------------
# The manifest verify reads
# ---------------------------------------------------------------------------


def test_the_template_manifest_matches_the_schema_verify_reads(template: Path) -> None:
    """The template ships the manifest users start from, so it must parse."""
    from problemsetting import verify

    _, resolved = meta_mod.load(template)
    entries = verify.load_manifest(template, resolved)
    assert [entry.source.as_posix() for entry in entries] == [
        "solution.cpp",
        "submissions/naive.py",
        "submissions/cuadratico.py",
    ]
    assert [entry.role for entry in entries] == ["model", None, None]
    assert all(entry.declares_expectation for entry in entries)


def test_the_manifest_uses_the_declared_limits(template: Path) -> None:
    """Each entry is graded with the limits of its own language, from meta.yml."""
    from problemsetting import verify

    _, resolved = meta_mod.load(template)
    entries = verify.load_manifest(template, resolved)
    for entry in entries:
        assert entry.limits == resolved.limits[entry.limits_key]

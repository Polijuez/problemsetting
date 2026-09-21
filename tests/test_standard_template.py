"""The ``standard`` template is a complete, buildable problem."""

from __future__ import annotations

import support
import random
from pathlib import Path

import pytest

from problemsetting import meta as meta_mod
from problemsetting import templates

MODEL = "standard"


@pytest.fixture(scope="module")
def template() -> Path:
    return templates.template_dir(MODEL)


@pytest.fixture(scope="module")
def generator_module(template: Path):
    # Via support.load_module, not importlib: a template is shipped package data,
    # and importlib's file loader would leave __pycache__ inside it.
    return support.load_module(template / "generator.py", "standard_generator")


def test_template_ships_the_whole_problem(template: Path) -> None:
    for name in (
        "meta.yml",
        "generator.py",
        "solution.cpp",
        "submissions.yml",
        "media/statement.md",
    ):
        assert (template / name).is_file(), name
    assert list((template / "submissions").glob("*.cpp"))


def test_template_meta_yml_is_a_valid_standard_problem() -> None:
    authoring, resolved = meta_mod.load(templates.template_dir(MODEL))
    assert authoring["model"] == "standard"
    assert resolved.executor == "CPP17"
    assert resolved.solution_limits == meta_mod.Limits(1.0, 262144)
    assert not resolved.is_batched and not resolved.uses_checker


def test_template_comment_header_matches_the_generator_of_meta_yml(template: Path) -> None:
    """The template's header is the one users see, so it tracks ``meta.HEADER``."""
    text = (template / "meta.yml").read_text()
    assert text.startswith(meta_mod.HEADER), (
        "the standard template's meta.yml comment block has drifted from "
        "problemsetting.meta.HEADER"
    )


# ---------------------------------------------------------------------------
# Generator protocol
# ---------------------------------------------------------------------------


def test_get_cases_returns_ordered_cases_with_the_required_methods(generator_module) -> None:
    cases = generator_module.Generator().get_cases()
    assert len(cases) >= 10
    for case in cases:
        assert callable(case.check)
        assert callable(case.write_file)


def test_generator_is_deterministic_per_seed(generator_module) -> None:
    first = generator_module.Generator().get_cases()
    second = generator_module.Generator().get_cases()
    assert [(c.a, c.b) for c in first] == [(c.a, c.b) for c in second]


def test_case_write_file_emits_the_declared_input_format(generator_module) -> None:
    import io

    case = generator_module.TestCase(2, 3)
    buffer = io.StringIO()
    case.write_file(buffer)
    assert buffer.getvalue() == "2 3\n"


def test_case_check_rejects_out_of_range_values(generator_module) -> None:
    limit = generator_module.LIM_ST2
    with pytest.raises(AssertionError):
        generator_module.TestCase(limit + 1, 0)
    with pytest.raises(AssertionError):
        generator_module.TestCase(0, -limit - 1)
    generator_module.TestCase(limit, -limit)  # boundary is fine


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
    # `standard` pays everything in one batch.
    assert len(subtasks) == 1
    assert points == 100


def test_subtask_classifiers_partition_the_cases(generator_module) -> None:
    cases = generator_module.Generator().get_cases()
    small = [c for c in cases if generator_module.check_st1(c)]
    # The final subtask accepts everything: cases accumulate upward, which is the
    # convention init.yml emission relies on.
    assert all(generator_module.check_st2(c) for c in cases)
    assert 0 < len(small) < len(cases)
    assert any(not generator_module.check_st1(c) for c in cases)


def test_gen_small_returns_small_cases(generator_module) -> None:
    rand = random.Random(1234)
    cases = generator_module.Generator().gen_small(rand)
    assert cases
    for case in cases:
        assert abs(case.a) <= 1000 and abs(case.b) <= 1000


def test_model_solution_reads_what_the_generator_writes(generator_module) -> None:
    """The pairing the toolkit depends on: solution.cpp parses case input."""
    import io

    case = generator_module.TestCase(-4, 7)
    buffer = io.StringIO()
    case.write_file(buffer)
    values = buffer.getvalue().split()
    assert len(values) == 2
    assert int(values[0]) + int(values[1]) == 3


def test_the_template_manifest_matches_the_schema_verify_reads(template: Path) -> None:
    """The template ships the manifest users start from, so it must parse.

    Read through ``verify.load_manifest`` rather than by loading the YAML here:
    the point is that the file the template ships is accepted by the code that
    consumes it, which is the drift this guards against.
    """
    from problemsetting import verify

    _, resolved = meta_mod.load(template)
    entries = verify.load_manifest(template, resolved)
    assert [entry.source.as_posix() for entry in entries] == [
        "solution.cpp",
        "submissions/incorrecto.cpp",
        "submissions/fuerza-bruta.cpp",
    ]
    assert [entry.role for entry in entries] == ["model", None, "brute"]
    assert all(entry.declares_expectation for entry in entries)

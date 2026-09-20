"""``cases``, ``archive`` and ``build``: generator → init.yml → zip.

The generator fixtures below are real problem directories written into
``tmp_path``: the generator is author code, so the tests exercise it the way the
CLI does -- by loading a file, not by importing a module.
"""

from __future__ import annotations

import textwrap
import zipfile
from pathlib import Path

import pytest
import yaml

from problemsetting import cases as cases_mod
from problemsetting import cli
from problemsetting import meta as meta_mod
from problemsetting import templates

STANDARD_MODEL = "standard"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def write_problem(
    root: Path,
    name: str,
    *,
    model: str = STANDARD_MODEL,
    solutionlang: str = ".cpp",
    generator: str,
    extra: dict[str, str] | None = None,
    overrides: dict[str, str] | None = None,
) -> Path:
    """Create a minimal problem directory whose generator is ``generator``."""
    problem = root / name
    problem.mkdir(parents=True)
    authoring = {"model": model, "solutionlang": solutionlang}
    authoring.update(overrides or {})
    meta_mod.write(problem, meta_mod.normalize(authoring, f"{name}/meta.yml"))
    (problem / cases_mod.GENERATOR_FILENAME).write_text(textwrap.dedent(generator))
    for filename, content in (extra or {}).items():
        (problem / filename).write_text(content)
    return problem


#: One case generator, reused wherever the *generator* is not the thing under
#: test: three cases, two subtasks, an all-accepting second one.
TWO_SUBTASKS = """
    class TestCase:
        def __init__(self, value):
            self.value = value

        def check(self):
            assert 0 <= self.value <= 100

        def write_file(self, file):
            file.write(f"{self.value}\\n")

    class Generator:
        def __init__(self, seed=1):
            self.seed = seed

        def get_cases(self):
            return [TestCase(1), TestCase(50), TestCase(100)]

        def get_subtasks(self):
            return [(30, lambda case: case.value <= 50), (70, lambda case: True)]
"""

SINGLE_SUBTASK = """
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
            return [TestCase(1), TestCase(2)]

        def get_subtasks(self):
            return [(100, lambda case: True)]
"""


def run(argv: list[str], monkeypatch, cwd: Path) -> int:
    monkeypatch.chdir(cwd)
    return cli.main(argv)


def load_init(problem: Path) -> dict:
    return yaml.safe_load((problem / cases_mod.INIT_FILENAME).read_text())


def batches(document: dict) -> list[dict]:
    return [entry for entry in document["test_cases"] if "batched" in entry]


def case_names(batch: dict) -> list[str]:
    return [entry["out"] for entry in batch["batched"]]


# ---------------------------------------------------------------------------
# The scaffolded standard template end to end (acceptance criterion 1)
# ---------------------------------------------------------------------------


def test_cases_on_the_scaffolded_standard_template(tmp_path, monkeypatch, capsys) -> None:
    assert run(["new", "--model", STANDARD_MODEL, "demo-ab"], monkeypatch, tmp_path) == 0
    capsys.readouterr()
    problem = tmp_path / "demo-ab"

    assert run(["cases", "demo-ab"], monkeypatch, tmp_path) == 0
    out = capsys.readouterr().out
    assert "21 cases" in out and "100 pts" in out

    document = load_init(problem)
    assert document["archive"] == "demo-ab.zip"
    assert "checker" not in document and "signature_grader" not in document
    (batch,) = batches(document)
    assert batch["points"] == 100
    assert "dependencies" not in batch
    # Every case of a `standard` problem lands in its single all-or-nothing batch.
    assert len(batch["batched"]) == 21
    assert all(entry["in"].startswith("cases/") for entry in batch["batched"])

    inputs = sorted(problem.glob("cases/*.in"))
    assert len(inputs) == 21
    assert (problem / "cases" / "0.in").read_text() == "2 3\n"


def test_cases_reprunes_stale_case_files(tmp_path, monkeypatch) -> None:
    """A leftover case file from a bigger previous run must not survive."""
    write_problem(tmp_path, "demo", generator=SINGLE_SUBTASK)
    problem = tmp_path / "demo"
    (problem / "cases").mkdir()
    stale_in = problem / "cases" / "9.in"
    stale_out = problem / "cases" / "9.out"
    stale_in.write_text("stale")
    stale_out.write_text("stale")

    assert run(["cases", "demo"], monkeypatch, tmp_path) == 0
    assert not stale_in.exists() and not stale_out.exists()
    assert (problem / "cases" / "1.in").is_file()


def test_a_changed_input_discards_its_stale_expected_output(
    tmp_path, monkeypatch, capsys
) -> None:
    """A stale .out is graded as the expected answer -- it must not survive."""
    write_problem(
        tmp_path,
        "demo",
        generator="""
            VALUE = 1

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
                    return [TestCase(VALUE), TestCase(100)]

                def get_subtasks(self):
                    return [(100, lambda case: True)]
        """,
    )
    problem = tmp_path / "demo"
    assert run(["cases", "demo"], monkeypatch, tmp_path) == 0
    for index in range(2):
        (problem / "cases" / f"{index}.out").write_text("stale\n")

    # Unchanged inputs: the outputs survive, so a plain re-run is cheap.
    assert run(["cases", "demo"], monkeypatch, tmp_path) == 0
    assert (problem / "cases" / "0.out").read_text() == "stale\n"
    assert (problem / "cases" / "1.out").read_text() == "stale\n"

    # Change the generator: only the affected case's output is discarded.
    generator = problem / cases_mod.GENERATOR_FILENAME
    generator.write_text(generator.read_text().replace("VALUE = 1", "VALUE = 2"))
    assert run(["cases", "demo"], monkeypatch, tmp_path) == 0
    assert "discarded 1 stale expected output" in capsys.readouterr().out
    assert not (problem / "cases" / "0.out").exists()
    assert (problem / "cases" / "1.out").read_text() == "stale\n"
    assert (problem / "cases" / "0.in").read_text() == "2\n"


def test_fractional_points_survive_the_yaml_round_trip(tmp_path, monkeypatch) -> None:
    """`:g` would round 100/3 and write `1e+21`, which YAML reads back as a string."""
    write_problem(
        tmp_path,
        "demo",
        overrides={"batch": "subtasks"},
        generator="""
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
                    return [TestCase(1)]

                def get_subtasks(self):
                    return [(100 / 3, lambda case: True), (1e21, lambda case: True)]
        """,
    )
    assert run(["cases", "demo"], monkeypatch, tmp_path) == 0
    first, second = batches(load_init(tmp_path / "demo"))
    assert first["points"] == 100 / 3
    assert second["points"] == 1e21


def test_generator_is_deterministic_per_seed(tmp_path, monkeypatch) -> None:
    write_problem(
        tmp_path,
        "demo",
        generator="""
            import random

            class TestCase:
                def __init__(self, value):
                    self.value = value

                def check(self):
                    pass

                def write_file(self, file):
                    file.write(f"{self.value}\\n")

            class Generator:
                def __init__(self, seed=7):
                    self.random = random.Random(seed)

                def get_cases(self):
                    return [TestCase(self.random.randint(0, 1000))]

                def get_subtasks(self):
                    return [(100, lambda case: True)]
        """,
    )
    problem = tmp_path / "demo"
    assert run(["cases", "demo", "--seed", "1234"], monkeypatch, tmp_path) == 0
    first = (problem / "cases" / "0.in").read_text()
    assert run(["cases", "demo", "--seed", "1234"], monkeypatch, tmp_path) == 0
    assert (problem / "cases" / "0.in").read_text() == first


# ---------------------------------------------------------------------------
# Batches, inclusion, dependencies (acceptance criteria 2 and 3)
# ---------------------------------------------------------------------------


def test_a_case_in_several_subtasks_appears_in_each(tmp_path, monkeypatch, capsys) -> None:
    """The inclusion convention: the final all-accepting batch absorbs everything."""
    write_problem(
        tmp_path,
        "demo",
        model="batched",
        overrides={"batch": "subtasks"},
        generator=TWO_SUBTASKS,
    )
    problem = tmp_path / "demo"
    assert run(["cases", "demo"], monkeypatch, tmp_path) == 0

    document = load_init(problem)
    first, second = batches(document)
    assert first["points"] == 30 and second["points"] == 70
    assert case_names(first) == ["cases/0.out", "cases/1.out"]
    assert case_names(second) == ["cases/0.out", "cases/1.out", "cases/2.out"]
    # The shared cases are literally the same files in both batches.
    assert set(case_names(first)) <= set(case_names(second))


def test_dependencies_emit_when_requested(tmp_path, monkeypatch) -> None:
    write_problem(
        tmp_path,
        "demo",
        overrides={"batch": "subtasks"},
        generator="""
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
                    return [TestCase(1)]

                def get_subtasks(self):
                    return [
                        (30, lambda case: True),
                        (30, lambda case: True),
                        (40, lambda case: True, [1, 2]),
                    ]
        """,
    )
    problem = tmp_path / "demo"
    assert run(["cases", "demo"], monkeypatch, tmp_path) == 0

    first, second, third = batches(load_init(problem))
    assert "dependencies" not in first and "dependencies" not in second
    assert third["dependencies"] == [1, 2]


def test_dependencies_are_absent_when_not_requested(tmp_path, monkeypatch) -> None:
    write_problem(tmp_path, "demo", generator=SINGLE_SUBTASK)
    problem = tmp_path / "demo"
    assert run(["cases", "demo"], monkeypatch, tmp_path) == 0
    text = (problem / cases_mod.INIT_FILENAME).read_text()
    assert "dependencies" not in text


def test_dependencies_are_deduplicated_and_sorted(tmp_path, monkeypatch) -> None:
    write_problem(
        tmp_path,
        "demo",
        overrides={"batch": "subtasks"},
        generator="""
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
                    return [TestCase(1)]

                def get_subtasks(self):
                    return [
                        (30, lambda case: True),
                        (30, lambda case: True),
                        (40, lambda case: True, [2, 1, 2]),
                    ]
        """,
    )
    problem = tmp_path / "demo"
    assert run(["cases", "demo"], monkeypatch, tmp_path) == 0
    assert batches(load_init(problem))[2]["dependencies"] == [1, 2]


def test_two_element_subtask_tuples_keep_working(tmp_path, monkeypatch) -> None:
    """Decision Q22: the third element is optional, so old generators are unchanged."""
    write_problem(
        tmp_path,
        "demo",
        overrides={"batch": "subtasks"},
        generator=TWO_SUBTASKS,
    )
    problem = tmp_path / "demo"
    assert run(["cases", "demo"], monkeypatch, tmp_path) == 0
    first, second = batches(load_init(problem))
    assert first["points"] == 30 and "dependencies" not in first
    assert second["points"] == 70 and "dependencies" not in second


# ---------------------------------------------------------------------------
# All 8 models (acceptance criterion: init.yml correct for every model)
# ---------------------------------------------------------------------------


EXTRA_FILES = {
    cases_mod.CHECKER_FILENAME: "def check(process_output, judge_output, **kwargs):\n    return True\n",
    cases_mod.SIGNATURE_HEADER: "int solve(int a, int b);\n",
    cases_mod.SIGNATURE_ENTRY: "#include \"signature.hpp\"\nint main() { return 0; }\n",
}


@pytest.mark.parametrize("model", sorted(meta_mod.MODELS))
def test_init_yml_is_correct_for_every_model(tmp_path, monkeypatch, model: str) -> None:
    axes = meta_mod.MODELS[model]
    solutionlang = ".txt" if axes["submission"] == "text" else ".cpp"
    generator = TWO_SUBTASKS if axes["batch"] == "subtasks" else SINGLE_SUBTASK
    write_problem(
        tmp_path,
        "demo",
        model=model,
        solutionlang=solutionlang,
        generator=generator,
        extra={k: v for k, v in EXTRA_FILES.items()},
    )
    problem = tmp_path / "demo"
    assert run(["cases", "demo"], monkeypatch, tmp_path) == 0
    document = load_init(problem)

    assert document["archive"] == "demo.zip"
    assert ("checker" in document) == (axes["checker"] == "custom")
    assert ("signature_grader" in document) == (axes["grader"] == "signature")
    if axes["grader"] == "signature":
        assert document["signature_grader"] == {
            "entry": cases_mod.SIGNATURE_ENTRY,
            "header": cases_mod.SIGNATURE_HEADER,
        }

    emitted = batches(document)
    assert len(emitted) == (2 if axes["batch"] == "subtasks" else 1)
    for batch in emitted:
        for entry in batch["batched"]:
            # Output-only submissions are text files with no input: the judge
            # supplies empty stdin (`dmoj/problem.py:489-493`).
            assert ("in" in entry) is (axes["submission"] != "text")
            assert entry["out"].startswith("cases/")

    expected_cases = 3 if axes["batch"] == "subtasks" else 2
    inputs = list((problem / "cases").glob("*.in"))
    assert len(inputs) == (0 if axes["submission"] == "text" else expected_cases)


def test_a_model_requiring_a_checker_without_one_is_an_authoring_error(
    tmp_path, monkeypatch, capsys
) -> None:
    write_problem(tmp_path, "demo", model="custom", generator=SINGLE_SUBTASK)
    assert run(["cases", "demo"], monkeypatch, tmp_path) == 1
    err = capsys.readouterr().err
    assert err.startswith("error: ")
    assert "checker.py" in err and "'custom'" in err


def test_a_signature_model_without_the_evaluator_is_an_authoring_error(
    tmp_path, monkeypatch, capsys
) -> None:
    write_problem(
        tmp_path,
        "demo",
        model="signature-batched",
        solutionlang=".cpp",
        generator=TWO_SUBTASKS,
        extra={cases_mod.SIGNATURE_HEADER: "int solve(int a, int b);\n"},
    )
    assert run(["cases", "demo"], monkeypatch, tmp_path) == 1
    err = capsys.readouterr().err
    assert "evaluator.cpp" in err and "signature" in err


# ---------------------------------------------------------------------------
# Invalid authoring is reported, never emitted (acceptance criterion 4)
# ---------------------------------------------------------------------------


def _generator_with_subtasks(entries: str) -> str:
    return f"""
        class TestCase:
            def __init__(self, value):
                self.value = value

            def check(self):
                pass

            def write_file(self, file):
                file.write(f"{{self.value}}\\n")

        class Generator:
            def __init__(self, seed=1):
                pass

            def get_cases(self):
                return [TestCase(1)]

            def get_subtasks(self):
                return {entries}
    """


def test_nested_subtasks_are_rejected(tmp_path, monkeypatch, capsys) -> None:
    write_problem(
        tmp_path,
        "demo",
        overrides={"batch": "subtasks"},
        generator=_generator_with_subtasks("[(50, [(25, lambda c: True), (25, lambda c: True)])]"),
    )
    assert run(["cases", "demo"], monkeypatch, tmp_path) == 1
    err = capsys.readouterr().err
    assert "nested" in err and "nested batches" in err
    # Nothing invalid was written.
    assert not (tmp_path / "demo" / cases_mod.INIT_FILENAME).exists()


@pytest.mark.parametrize(
    ("entries", "fragment"),
    [
        ("[(30, lambda c: True), (70, lambda c: True, [3])]", "not an earlier batch"),
        ("[(30, lambda c: True), (70, lambda c: True, [2])]", "not an earlier batch"),
        ("[(30, lambda c: True), (70, lambda c: True, [0])]", "positive integers"),
        ("[(30, lambda c: True), (70, lambda c: True, [-2])]", "positive integers"),
        ("[(30, lambda c: True), (70, lambda c: True, [1.5])]", "positive integers"),
        ("[(30, lambda c: True), (70, lambda c: True, '1')]", "list of 1-based batch numbers"),
    ],
)
def test_bad_dependencies_are_rejected(tmp_path, monkeypatch, capsys, entries, fragment) -> None:
    write_problem(
        tmp_path,
        "demo",
        overrides={"batch": "subtasks"},
        generator=_generator_with_subtasks(entries),
    )
    assert run(["cases", "demo"], monkeypatch, tmp_path) == 1
    err = capsys.readouterr().err
    assert fragment in err, err
    assert not (tmp_path / "demo" / cases_mod.INIT_FILENAME).exists()


def test_a_dependency_on_the_batch_itself_is_rejected(tmp_path, monkeypatch, capsys) -> None:
    write_problem(
        tmp_path,
        "demo",
        overrides={"batch": "subtasks"},
        generator=_generator_with_subtasks("[(100, lambda c: True, [1])]"),
    )
    assert run(["cases", "demo"], monkeypatch, tmp_path) == 1
    assert "not an earlier batch" in capsys.readouterr().err


def test_subtasks_from_a_single_batch_model_are_rejected(tmp_path, monkeypatch, capsys) -> None:
    """Silently turning all-or-nothing scoring into partial scoring is the bug."""
    write_problem(tmp_path, "demo", generator=TWO_SUBTASKS)  # model: standard
    assert run(["cases", "demo"], monkeypatch, tmp_path) == 1
    err = capsys.readouterr().err
    assert "'standard'" in err and "single batch" in err and "'batched'" in err


def test_a_generator_that_raises_is_reported_with_its_file(tmp_path, monkeypatch, capsys) -> None:
    write_problem(
        tmp_path,
        "demo",
        generator="""
            class Generator:
                def __init__(self, seed=1):
                    raise ValueError("nope")

                def get_cases(self):
                    return []

                def get_subtasks(self):
                    return []
        """,
    )
    assert run(["cases", "demo"], monkeypatch, tmp_path) == 1
    err = capsys.readouterr().err
    assert "generator.py" in err and "nope" in err


def test_missing_generator_is_reported(tmp_path, monkeypatch, capsys) -> None:
    problem = tmp_path / "demo"
    problem.mkdir()
    meta_mod.write(problem, meta_mod.normalize({"model": "standard", "solutionlang": ".cpp"}))
    assert run(["cases", "demo"], monkeypatch, tmp_path) == 1
    assert "generator.py not found" in capsys.readouterr().err


def test_a_cases_directory_without_meta_yml_is_reported(tmp_path, monkeypatch, capsys) -> None:
    (tmp_path / "demo").mkdir()
    assert run(["cases", "demo"], monkeypatch, tmp_path) == 1
    assert "meta.yml" in capsys.readouterr().err


def test_a_classifier_that_raises_is_reported_with_the_case(tmp_path, monkeypatch, capsys) -> None:
    write_problem(
        tmp_path,
        "demo",
        generator="""
            class TestCase:
                def __init__(self, value):
                    self.value = value

                def check(self):
                    pass

                def write_file(self, file):
                    file.write("x")

            class Generator:
                def __init__(self, seed=1):
                    pass

                def get_cases(self):
                    return [TestCase(1), TestCase(2)]

                def get_subtasks(self):
                    def check(case):
                        raise KeyError("boom")

                    return [(100, check)]
        """,
    )
    assert run(["cases", "demo"], monkeypatch, tmp_path) == 1
    err = capsys.readouterr().err
    assert "batch 1" in err and "case 0" in err and "boom" in err
    assert not (tmp_path / "demo" / cases_mod.INIT_FILENAME).exists()


def test_a_batch_that_selects_no_case_is_rejected(tmp_path, monkeypatch, capsys) -> None:
    """An empty `batched:` key is YAML null, which the judge iterates and dies on."""
    write_problem(
        tmp_path,
        "demo",
        overrides={"batch": "subtasks"},
        generator=_generator_with_subtasks("[(50, lambda c: False), (50, lambda c: True)]"),
    )
    assert run(["cases", "demo"], monkeypatch, tmp_path) == 1
    err = capsys.readouterr().err
    assert "batch 1" in err and "selects none" in err
    assert not (tmp_path / "demo" / cases_mod.INIT_FILENAME).exists()


def test_a_write_file_that_raises_is_reported_with_the_case(
    tmp_path, monkeypatch, capsys
) -> None:
    write_problem(
        tmp_path,
        "demo",
        generator="""
            class TestCase:
                def __init__(self, value):
                    self.value = value

                def check(self):
                    pass

                def write_file(self, file):
                    raise RuntimeError("cannot serialise")

            class Generator:
                def __init__(self, seed=1):
                    pass

                def get_cases(self):
                    return [TestCase(1)]

                def get_subtasks(self):
                    return [(100, lambda case: True)]
        """,
    )
    assert run(["cases", "demo"], monkeypatch, tmp_path) == 1
    err = capsys.readouterr().err
    assert "write_file() failed for case 0" in err and "cannot serialise" in err


# ---------------------------------------------------------------------------
# archive (acceptance criterion 5)
# ---------------------------------------------------------------------------


def test_archive_members_are_exactly_the_files_init_yml_references(
    tmp_path, monkeypatch, capsys
) -> None:
    write_problem(
        tmp_path,
        "demo",
        overrides={"batch": "subtasks"},
        generator=TWO_SUBTASKS,
    )
    problem = tmp_path / "demo"
    assert run(["cases", "demo"], monkeypatch, tmp_path) == 0
    for index in range(3):
        (problem / "cases" / f"{index}.out").write_text("0\n")
    # A decoy the init.yml does not reference, to prove the membership rule.
    (problem / "cases" / "stray.txt").write_text("not a case")

    assert run(["archive", "demo"], monkeypatch, tmp_path) == 0
    archive_path = problem / "demo.zip"
    with zipfile.ZipFile(archive_path) as archive:
        names = sorted(archive.namelist())

    document = load_init(problem)
    referenced = cases_mod.referenced_cases(document, str(problem / cases_mod.INIT_FILENAME))
    assert names == sorted(referenced)
    assert names == [
        "cases/0.in", "cases/0.out", "cases/1.in", "cases/1.out",
        "cases/2.in", "cases/2.out",
    ], names
    assert "cases/stray.txt" not in names


def test_archive_refuses_when_expected_outputs_are_missing(tmp_path, monkeypatch, capsys) -> None:
    write_problem(tmp_path, "demo", generator=SINGLE_SUBTASK)
    assert run(["cases", "demo"], monkeypatch, tmp_path) == 0
    assert run(["archive", "demo"], monkeypatch, tmp_path) == 1
    err = capsys.readouterr().err
    assert "cases/0.out" in err and "outputs" in err
    assert not (tmp_path / "demo" / "demo.zip").exists()


def test_archive_refuses_without_init_yml(tmp_path, monkeypatch, capsys) -> None:
    write_problem(tmp_path, "demo", generator=SINGLE_SUBTASK)
    assert run(["archive", "demo"], monkeypatch, tmp_path) == 1
    assert "init.yml" in capsys.readouterr().err


# ---------------------------------------------------------------------------
# build
# ---------------------------------------------------------------------------


def test_build_runs_cases_then_fails_honestly_on_the_missing_outputs_step(
    tmp_path, monkeypatch, capsys
) -> None:
    """Until ticket 03 lands, `build` must stop and say why -- not skip outputs."""
    assert run(["new", "--model", STANDARD_MODEL, "demo-ab"], monkeypatch, tmp_path) == 0
    capsys.readouterr()
    problem = tmp_path / "demo-ab"

    assert run(["build", "demo-ab"], monkeypatch, tmp_path) == 1
    out, err = capsys.readouterr()
    assert "==> cases demo-ab" in out
    assert "==> outputs demo-ab" in out
    assert "no `outputs` step yet" in err
    # The cases step really ran, and nothing was archived from a partial build.
    assert (problem / cases_mod.INIT_FILENAME).is_file()
    assert len(list(problem.glob("cases/*.in"))) == 21
    assert not (problem / "demo-ab.zip").exists()


def test_build_reports_a_cases_failure_before_the_rest(tmp_path, monkeypatch, capsys) -> None:
    write_problem(tmp_path, "demo", generator=TWO_SUBTASKS)  # standard model, 2 subtasks
    assert run(["build", "demo"], monkeypatch, tmp_path) == 1
    out, err = capsys.readouterr()
    assert "single batch" in err
    assert "==> outputs demo" not in out


# ---------------------------------------------------------------------------
# The shipped template is itself buildable (integration)
# ---------------------------------------------------------------------------


def test_the_shipped_standard_template_renders_init_yml(tmp_path) -> None:
    """Runs the real emission against the shipped template, no CLI needed."""
    template = templates.template_dir(STANDARD_MODEL)
    authoring, resolved = meta_mod.load(template)
    generator = cases_mod.load_generator(template)
    source = str(template / cases_mod.GENERATOR_FILENAME)
    cases = cases_mod.read_cases(generator, source)
    subtasks = cases_mod.read_subtasks(generator, source)
    membership = cases_mod.classify(subtasks, cases, source)

    assert len(subtasks) == 1 and subtasks[0].points == 100
    files = [cases_mod.CaseFile(index, True) for index in range(len(cases))]
    init = cases_mod.render_init("demo-ab", resolved, subtasks, membership, files)
    assert init.startswith(cases_mod.INIT_HEADER + "\n")
    assert yaml.safe_load(init)["archive"] == "demo-ab.zip"

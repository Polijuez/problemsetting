"""The cheap CI contract: every shipped model scaffolds, builds and archives.

This is the local half of ``.github/workflows/ci.yml``, which scaffolds and
builds every model through the console script and validates each emitted
``init.yml`` with :func:`validate_init` below.  The suite itself is run by the
workflow's final ``pytest`` step; this file is where the cheap-pipeline contract
is stated, so a broken template breaks both.

What the job deliberately does **not** do: build ``localhost/dmoj/judge-tier3``,
start judge containers, or run ``verify``/``stress``.  Those exercise the real
judge and cost a multi-GB image build, so they are opt-in and run locally or on
demand (decision Q29), never per push.

Structural, not authoritative
-----------------------------

``init.yml`` is checked *structurally* here.  The authoritative check is DMOJ's
own loader, and it cannot run on this host: ``dmoj/problem.py:33`` imports
``MemoryIO`` from ``dmoj.cptbox.utils``, which imports ``dmoj.cptbox._cptbox``
(``dmoj/cptbox/utils.py:8``) -- the compiled C++ sandbox extension present only
inside the judge image.  So :func:`validate_init` re-states, from the document
alone, exactly the rules DMOJ decides at load time:

* the keys are the ones ``cases.render_init`` emits;
* every batch holds at least one case -- a bare ``batched:`` is YAML null and
  ``dmoj/problem.py:227`` tests ``'batched' in raw_config``, so the judge
  recurses into ``None`` and dies;
* ``dependencies`` are positive integers naming an earlier batch
  (``dmoj/problem.py:334-337``);
* no batch contains another batch (``dmoj/problem.py:331-332``).
"""

from __future__ import annotations

import os
import zipfile
from pathlib import Path
from typing import Any

import pytest
import yaml

from problemsetting import cases as cases_mod
from problemsetting import cli
from problemsetting import meta as meta_mod
from problemsetting import templates

# ---------------------------------------------------------------------------
# Structural validation of init.yml
# ---------------------------------------------------------------------------

#: Top-level keys ``cases.render_init`` emits; anything else is a key the judge
#: silently ignores or rejects, so it fails here instead.
TOP_LEVEL_KEYS = frozenset({"archive", "checker", "signature_grader", "test_cases"})


def _validate_dependencies(present: bool, raw: Any, batch_no: int, where: str) -> list[str]:
    """``dependencies:`` is optional, but when present it must be a usable list.

    ``present`` matters as much as ``raw``: a bare ``dependencies:`` is YAML null,
    and ``dmoj/config.py:112-113`` falls back to the parent node only for a
    *missing* key -- an explicit null stays ``None``, which ``BatchedTestCase``
    then iterates (``dmoj/problem.py:334``) and dies on.  That is the same
    null-shaped trap as a bare ``batched:``.
    """
    if not present:
        return []
    if not isinstance(raw, list) or not raw:
        return [f"{where}: `dependencies:` must be a non-empty list of batch numbers"]
    errors: list[str] = []
    for value in raw:
        if isinstance(value, bool) or not isinstance(value, int):
            errors.append(f"{where}: dependency {value!r} is not an integer")
        elif value < 1:
            errors.append(f"{where}: dependency {value} is not a positive integer")
        elif value >= batch_no:
            errors.append(f"{where}: dependency {value} is not an earlier batch")
    return errors


def validate_init(document: Any, source: str) -> list[str]:
    """Every structural problem in the parsed ``init.yml``, or ``[]`` when it is clean."""
    if not isinstance(document, dict):
        return [f"{source}: init.yml must be a mapping, got {type(document).__name__}"]

    errors: list[str] = []
    for key in sorted(set(document) - TOP_LEVEL_KEYS):
        errors.append(f"{source}: unexpected key {key!r}; `cases` emits {sorted(TOP_LEVEL_KEYS)}")
    if not isinstance(document.get("archive"), str) or not document["archive"]:
        errors.append(f"{source}: no `archive:` filename declared")

    entries = document.get("test_cases")
    if not isinstance(entries, list) or not entries:
        errors.append(f"{source}: `test_cases:` must be a non-empty list")
        return errors

    # DMOJ numbers batches by counting the entries carrying a `batched:` key, in
    # order (`dmoj/problem.py:224-240`), which is how a dependency is resolved.
    batch_no = 0
    for index, entry in enumerate(entries, start=1):
        where = f"{source}: test_cases[{index}]"
        if not isinstance(entry, dict):
            errors.append(f"{where}: must be a mapping")
            continue

        if "batched" in entry:
            batch_no += 1
            where = f"{source}: batch {batch_no}"
            children = entry.get("batched")
            if not isinstance(children, list) or not children:
                errors.append(f"{where}: `batched:` holds no case")
                continue
            errors.extend(
                _validate_dependencies(
                    "dependencies" in entry, entry.get("dependencies"), batch_no, where
                )
            )
        else:
            if "dependencies" in entry:
                errors.append(f"{where}: `dependencies:` on a case that is not a batch")
            children = [entry]

        for position, child in enumerate(children, start=1):
            if not isinstance(child, dict):
                errors.append(f"{where}: case {position} must be a mapping")
                continue
            if "batched" in child:
                errors.append(
                    f"{where}: case {position} nests another batch; "
                    f"DMOJ rejects 'nested batches'"
                )
            if not any(isinstance(child.get(name), str) for name in ("in", "out")):
                errors.append(f"{where}: case {position} names no input or output file")
    return errors


def load_init(problem: Path) -> Any:
    return yaml.safe_load((problem / cases_mod.INIT_FILENAME).read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# The pipeline under test
# ---------------------------------------------------------------------------

#: Problem names for the scaffold loop.  Explicit rather than derived: the site
#: caps ids at 20 characters (``problems.NAME_RE``), and the model names are too
#: long to use directly, so a name that collides or overflows must be a visible
#: edit here rather than a silent truncation.
CI_PROBLEM_NAMES = {
    "standard": "ci-standard",
    "batched": "ci-batched",
    "custom": "ci-custom",
    "batched-custom": "ci-bcustom",
    "output-only": "ci-oonly",
    "output-only-custom": "ci-oocustom",
    "signature-batched": "ci-sig",
    "signature-batched-custom": "ci-sigcustom",
}


@pytest.fixture(scope="module")
def pipeline(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Path]:
    """Scaffold, build and archive every model once; return ``model -> problem dir``.

    Module-scoped because ``outputs`` compiles the model solution: running the
    four commands once per model and sharing the result over three tests keeps
    this file at a couple of seconds.
    """
    root = tmp_path_factory.mktemp("ci")
    previous = Path.cwd()
    os.chdir(root)
    try:
        built: dict[str, Path] = {}
        for model in sorted(meta_mod.MODELS):
            name = CI_PROBLEM_NAMES[model]
            for argv in (["new", "--model", model, name], ["cases", name],
                         ["outputs", name], ["archive", name]):
                assert cli.main(argv) == 0, f"{model}: `problemsetting {' '.join(argv)}` failed"
            built[model] = root / name
        return built
    finally:
        os.chdir(previous)


def test_every_model_has_a_ci_problem_name() -> None:
    """A new model must get a name here, or the pipeline silently skips it."""
    assert sorted(CI_PROBLEM_NAMES) == sorted(meta_mod.MODELS)


def test_every_model_template_is_shipped() -> None:
    """The templates are the toolkit's integration test; all 8 must ship.

    ``templates.shipped()`` discovers by directory presence, so a model declared
    in ``meta.MODELS`` without its template directory would scaffold nowhere and
    this test -- not a user -- is where that is noticed.
    """
    shipped = set(templates.shipped())
    assert shipped == set(meta_mod.MODELS), (
        f"models without a shipped template: {sorted(set(meta_mod.MODELS) - shipped)}; "
        f"templates with no model: {sorted(shipped - set(meta_mod.MODELS))}"
    )


@pytest.mark.parametrize("model", sorted(meta_mod.MODELS))
def test_the_pipeline_builds_every_model(model: str, pipeline: dict[str, Path]) -> None:
    """Scaffold + ``cases`` + ``outputs`` + ``archive`` left a gradeable problem."""
    problem = pipeline[model]

    assert (problem / cases_mod.GENERATOR_FILENAME).is_file()
    assert (problem / cases_mod.INIT_FILENAME).is_file()

    document = load_init(problem)
    assert validate_init(document, str(problem / cases_mod.INIT_FILENAME)) == []

    # The archive exists, is named by the init.yml, and holds exactly the files
    # init.yml references -- the two cannot drift apart.
    archive_path = problem / document["archive"]
    assert archive_path.is_file()
    references = cases_mod.referenced_cases(document, str(problem / cases_mod.INIT_FILENAME))
    with zipfile.ZipFile(archive_path) as archive:
        assert sorted(archive.namelist()) == sorted(references)

    assert all((problem / name).is_file() for name in references)


@pytest.mark.parametrize("model", sorted(meta_mod.MODELS))
def test_the_built_init_yml_matches_the_model(model: str, pipeline: dict[str, Path]) -> None:
    """The keys ``cases`` emits follow the resolved axes, not the model name."""
    document = load_init(pipeline[model])
    _, resolved = meta_mod.load(pipeline[model])
    assert ("checker" in document) == resolved.uses_checker
    assert ("signature_grader" in document) == resolved.uses_signature


# ---------------------------------------------------------------------------
# The structural validator itself
# ---------------------------------------------------------------------------


def test_a_bare_batched_key_is_rejected() -> None:
    """``batched:`` with nothing under it is YAML null, which the judge iterates."""
    document = {"archive": "p.zip", "test_cases": [{"points": 1, "batched": None}]}
    assert any("holds no case" in error for error in validate_init(document, "p/init.yml"))


def test_a_nested_batch_is_rejected() -> None:
    document = {
        "archive": "p.zip",
        "test_cases": [{"batched": [{"batched": [{"out": "cases/0.out"}]}]}],
    }
    assert any("nested batches" in error for error in validate_init(document, "p/init.yml"))


@pytest.mark.parametrize(
    "dependencies, fragment",
    [
        ([0], "positive integer"),
        ([2], "earlier batch"),
        (["1"], "not an integer"),
        (1, "must be a non-empty list"),
        ([], "must be a non-empty list"),
    ],
)
def test_bad_dependencies_are_rejected(dependencies: Any, fragment: str) -> None:
    document = {
        "archive": "p.zip",
        "test_cases": [
            {"batched": [{"out": "cases/0.out"}]},
            {"batched": [{"out": "cases/1.out"}], "dependencies": dependencies},
        ],
    }
    assert any(fragment in error for error in validate_init(document, "p/init.yml"))


def test_a_bare_dependencies_key_is_rejected() -> None:
    """An explicit ``dependencies:`` is YAML null; a *missing* key is the only default.

    ``dmoj/config.py:112-113`` falls back to the parent node for a missing key,
    not for an explicit null, so ``None`` reaches ``BatchedTestCase`` and is
    iterated (``dmoj/problem.py:334``).
    """
    document = {
        "archive": "p.zip",
        "test_cases": [
            {"batched": [{"out": "cases/0.out"}]},
            {"batched": [{"out": "cases/1.out"}], "dependencies": None},
        ],
    }
    assert any("non-empty list" in error for error in validate_init(document, "p/init.yml"))


def test_a_dependency_on_the_batch_itself_is_rejected() -> None:
    document = {
        "archive": "p.zip",
        "test_cases": [
            {"batched": [{"out": "cases/0.out"}]},
            {"batched": [{"out": "cases/1.out"}], "dependencies": [2]},
        ],
    }
    assert any("earlier batch" in error for error in validate_init(document, "p/init.yml"))


def test_unknown_top_level_keys_are_rejected() -> None:
    document = {"archive": "p.zip", "points": 100, "test_cases": [{"out": "cases/0.out"}]}
    assert any("unexpected key 'points'" in error for error in validate_init(document, "p/init.yml"))


def test_a_missing_archive_is_rejected() -> None:
    document = {"test_cases": [{"out": "cases/0.out"}]}
    assert any("archive" in error for error in validate_init(document, "p/init.yml"))


def test_an_empty_test_cases_list_is_rejected() -> None:
    assert validate_init({"archive": "p.zip", "test_cases": []}, "p/init.yml")


def test_a_well_formed_document_has_no_errors() -> None:
    """The positive case, so the checks above cannot pass by rejecting everything."""
    document = {
        "archive": "p.zip",
        "checker": "checker.py",
        "test_cases": [
            {"points": 20, "batched": [{"in": "cases/0.in", "out": "cases/0.out"}]},
            {
                "points": 80,
                "batched": [{"in": "cases/1.in", "out": "cases/1.out"}],
                "dependencies": [1],
            },
        ],
    }
    assert validate_init(document, "p/init.yml") == []

"""CLI surface and ``problemsetting new``."""

from __future__ import annotations

from pathlib import Path

import pytest

from problemsetting import cli
from problemsetting import meta as meta_mod
from problemsetting.errors import ProblemsettingError
from problemsetting.problems import validate_name


def run(argv: list[str], monkeypatch, cwd: Path) -> int:
    monkeypatch.chdir(cwd)
    return cli.main(argv)


def assert_fails(argv: list[str], monkeypatch, cwd: Path, capsys) -> str:
    """Run a command expected to fail; return its stderr message."""
    assert run(argv, monkeypatch, cwd) == 1
    err = capsys.readouterr().err
    assert err.startswith("error: "), err
    return err


# ---------------------------------------------------------------------------
# Parser surface
# ---------------------------------------------------------------------------


def test_help_lists_the_registered_subcommands(capsys) -> None:
    with pytest.raises(SystemExit) as excinfo:
        cli.build_parser().parse_args(["--help"])
    assert excinfo.value.code == 0
    assert "new" in capsys.readouterr().out


def test_missing_subcommand_is_an_error() -> None:
    with pytest.raises(SystemExit) as excinfo:
        cli.build_parser().parse_args([])
    assert excinfo.value.code != 0


def test_version_is_reported(capsys) -> None:
    from problemsetting import __version__

    with pytest.raises(SystemExit) as excinfo:
        cli.build_parser().parse_args(["--version"])
    assert excinfo.value.code == 0
    assert __version__ in capsys.readouterr().out


# ---------------------------------------------------------------------------
# new: the happy path
# ---------------------------------------------------------------------------


def test_new_scaffolds_a_complete_problem(tmp_path, monkeypatch, capsys) -> None:
    assert run(["new", "--model", "standard", "demo-ab"], monkeypatch, tmp_path) == 0
    problem = tmp_path / "demo-ab"
    for name in (
        "meta.yml",
        "generator.py",
        "solution.cpp",
        "submissions.yml",
        "media/statement.md",
    ):
        assert (problem / name).is_file(), name

    authoring, resolved = meta_mod.load(problem)
    assert authoring["model"] == "standard"
    assert authoring["solutionlang"] == ".cpp"
    assert resolved.executor == "CPP17"
    assert resolved.solution_limits == meta_mod.Limits(1.0, 262144)
    # The expansion is never written back into meta.yml.
    text = (problem / "meta.yml").read_text()
    assert "grader:" not in text and "batch:" not in text
    assert "created" in capsys.readouterr().out


def test_new_defaults_to_the_standard_model(tmp_path, monkeypatch) -> None:
    assert run(["new", "demo-ab"], monkeypatch, tmp_path) == 0
    assert meta_mod.load(tmp_path / "demo-ab")[1].model == "standard"


def test_new_does_not_copy_build_artifacts(tmp_path, monkeypatch) -> None:
    assert run(["new", "demo-ab"], monkeypatch, tmp_path) == 0
    problem = tmp_path / "demo-ab"
    assert not (problem / "init.yml").exists()
    assert not (problem / "cases").exists()
    assert not (problem / "__pycache__").exists()


def test_new_accepts_a_language_without_the_leading_dot(tmp_path, monkeypatch) -> None:
    assert run(["new", "-s", "cpp", "demo-ab"], monkeypatch, tmp_path) == 0
    assert meta_mod.load(tmp_path / "demo-ab")[1].solutionlang == ".cpp"


def test_force_refuses_to_delete_a_file(tmp_path, monkeypatch, capsys) -> None:
    (tmp_path / "demo").write_text("not a problem")
    err = assert_fails(["new", "--force", "demo"], monkeypatch, tmp_path, capsys)
    assert "is not a directory" in err
    assert (tmp_path / "demo").read_text() == "not a problem"


# ---------------------------------------------------------------------------
# new: the error cases the ticket calls out
# ---------------------------------------------------------------------------


def test_new_refuses_to_overwrite(tmp_path, monkeypatch, capsys) -> None:
    assert run(["new", "demo-ab"], monkeypatch, tmp_path) == 0
    capsys.readouterr()
    marker = tmp_path / "demo-ab" / "keep-me"
    marker.write_text("mine")

    err = assert_fails(["new", "demo-ab"], monkeypatch, tmp_path, capsys)
    assert "already exists" in err
    assert marker.read_text() == "mine", "the refusal must not touch the directory"


def test_new_force_replaces(tmp_path, monkeypatch) -> None:
    assert run(["new", "demo-ab"], monkeypatch, tmp_path) == 0
    (tmp_path / "demo-ab" / "stale.txt").write_text("old")
    assert run(["new", "--force", "demo-ab"], monkeypatch, tmp_path) == 0
    assert not (tmp_path / "demo-ab" / "stale.txt").exists()


@pytest.mark.parametrize("name", ["Bad Name", "demo/ab", "A_BC", "áccent"])
def test_new_rejects_unusable_names(name: str, tmp_path, monkeypatch, capsys) -> None:
    assert "invalid problem name" in assert_fails(["new", name], monkeypatch, tmp_path, capsys)


def test_new_rejects_a_name_the_site_would_truncate(tmp_path, monkeypatch, capsys) -> None:
    err = assert_fails(["new", "a" * 21], monkeypatch, tmp_path, capsys)
    assert "at most 20" in err


@pytest.mark.parametrize("name", ["--", "-leading", "demo\n", "demo\nx"])
def test_name_validation_rejects_argument_like_and_multi_line_names(name: str) -> None:
    # argparse would swallow the argument-like names before the subcommand sees
    # them, so the rule is asserted on the validator the subcommand uses.  The
    # `\n` cases are why NAME_RE anchors with \Z rather than $.
    with pytest.raises(ProblemsettingError, match="invalid problem name"):
        validate_name(name)


def test_new_rejects_an_unknown_model(tmp_path, monkeypatch, capsys) -> None:
    err = assert_fails(["new", "--model", "wat", "demo"], monkeypatch, tmp_path, capsys)
    assert "'wat'" in err
    assert "standard" in err and "signature-batched" in err


def test_new_rejects_a_model_without_a_shipped_template(
    tmp_path, monkeypatch, capsys
) -> None:
    """An unshipped model is rejected with a message naming what IS available.

    Computed rather than hard-coded: every model gains a template as the tickets
    land, so naming one here would couple this test to how far along the toolkit
    happens to be.  Skips once every declared model ships (nothing left to test).
    """
    from problemsetting import meta, templates

    unshipped = sorted(set(meta.MODELS) - set(templates.shipped()))
    if not unshipped:
        pytest.skip("every declared model ships a template")

    model = unshipped[0]
    err = assert_fails(["new", "--model", model, "demo"], monkeypatch, tmp_path, capsys)
    assert "not shipped yet" in err
    assert "standard" in err  # names what is available in this build


def test_new_rejects_an_unknown_language(tmp_path, monkeypatch, capsys) -> None:
    err = assert_fails(
        ["new", "--solutionlang", ".rs", "demo"], monkeypatch, tmp_path, capsys
    )
    assert "'.rs'" in err
    assert ".cpp" in err


def test_new_rejects_a_language_the_template_lacks(tmp_path, monkeypatch, capsys) -> None:
    err = assert_fails(
        ["new", "--solutionlang", ".py", "demo"], monkeypatch, tmp_path, capsys
    )
    assert "ships a model solution only in" in err
    assert "solutionlang: .py" in err



def test_new_defaults_to_the_templates_own_declared_language(tmp_path, monkeypatch) -> None:
    """A single-solution template is unaffected by the declared-language lookup.

    ``pick_solutionlang`` reads the template's ``meta.yml`` to pick the default, so
    that a template shipping more than one solution can say which it demonstrates.
    For every template with one solution the declaration and the file list agree,
    so this is the regression guard on the no-op half of that rule.
    """
    from problemsetting import templates

    single = [
        model
        for model in templates.shipped()
        if len(templates.solution_extensions(model)) == 1
    ]
    if not single:
        pytest.skip("every shipped template ships more than one solution")
    model = single[0]
    assert run(["new", "--model", model, "demo"], monkeypatch, tmp_path) == 0
    assert meta_mod.load(tmp_path / "demo")[1].solutionlang == templates.solution_extensions(model)[0]


def test_new_leaves_no_directory_behind_when_it_fails(tmp_path, monkeypatch, capsys) -> None:
    from problemsetting import meta, templates

    unshipped = sorted(set(meta.MODELS) - set(templates.shipped()))
    model = unshipped[0] if unshipped else "wat"  # unknown model fails the same way
    assert_fails(["new", "--model", model, "demo"], monkeypatch, tmp_path, capsys)
    assert not (tmp_path / "demo").exists()

"""The two-root model: the toolkit checkout vs the directory mounted at ``/problems``.

The toolkit used to conflate them -- one resolver served both meanings -- so a
problem was gradeable only if it lived inside the toolkit checkout.  These tests
pin the split: detection of a problemset repo from cwd, the explicit override and
its precedence, the fallback that keeps the toolkit's own behaviour (and its own
tests) intact, the two accepted problem-path forms, and where ``new`` puts a
problem.

Nothing here needs podman: the roots are directories, and the container layer's
use of them was exercised against a real pool.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from problemsetting import cli
from problemsetting import judges
from problemsetting.errors import JudgeError

TOOLKIT = "vendor/problemsetting"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def write_problemset(root: Path, *, problems: bool = True, toolkit: bool = True) -> Path:
    """A problemset repo: the two markers detection looks for, and one problem.

    Each marker can be left out, so a test can assert that neither alone is
    enough; the problem only exists when ``problems/`` does.
    """
    root.mkdir(parents=True, exist_ok=True)
    if problems:
        (root / "problems").mkdir(parents=True)
        (root / "problems" / "suma").mkdir()
    if toolkit:
        (root / TOOLKIT).mkdir(parents=True)
    return root


# ---------------------------------------------------------------------------
# Detection
# ---------------------------------------------------------------------------


def test_detection_accepts_a_directory_holding_both_markers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = write_problemset(tmp_path / "problemset")
    monkeypatch.chdir(repo)
    assert judges.problemset_root() == repo
    assert judges.problems_root() == repo / "problems"


def test_detection_walks_up_from_a_subdirectory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = write_problemset(tmp_path / "problemset")
    deep = repo / "problems" / "suma" / "submissions"
    deep.mkdir()
    monkeypatch.chdir(deep)
    assert judges.problemset_root() == repo
    assert judges.problems_root() == repo / "problems"


@pytest.mark.parametrize("problems,toolkit", [(True, False), (False, True)])
def test_detection_needs_both_markers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, problems: bool, toolkit: bool
) -> None:
    """Either marker alone is far too common to identify a problemset repo."""
    root = write_problemset(tmp_path / "half", problems=problems, toolkit=toolkit)
    monkeypatch.chdir(root)
    assert judges.problemset_root() is None


def test_detection_looks_below_the_nearest_ancestor_not_the_filesystem_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A nearer ancestor with no ``problems/`` does not stop the walk."""
    outer = write_problemset(tmp_path / "outer")
    inner = outer / "scratch"
    inner.mkdir()
    monkeypatch.chdir(inner)
    assert judges.problemset_root() == outer


# ---------------------------------------------------------------------------
# Override precedence
# ---------------------------------------------------------------------------


def test_the_override_wins_over_detection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = write_problemset(tmp_path / "problemset")
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(repo)  # detection would say repo/problems
    monkeypatch.setenv(judges.PROBLEMS_ROOT_ENV, str(elsewhere))
    assert judges.problems_root() == elsewhere


def test_the_override_wins_with_no_problemset_structure_at_all(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(judges.PROBLEMS_ROOT_ENV, str(tmp_path))
    monkeypatch.chdir(tmp_path)
    assert judges.problems_root() == tmp_path.resolve()


def test_the_override_is_resolved_not_merely_stored(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "real"
    target.mkdir()
    link = tmp_path / "link"
    link.symlink_to(target)
    monkeypatch.setenv(judges.PROBLEMS_ROOT_ENV, str(link))
    assert judges.problems_root() == target.resolve()


# ---------------------------------------------------------------------------
# The fallback
# ---------------------------------------------------------------------------


def test_the_fallback_is_the_toolkit_checkout(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """With no problemset structure, the toolkit is itself the problems root.

    That is the one legitimate falling-through case: the toolkit's own problems
    and every existing test live in its checkout.
    """
    elsewhere = tmp_path / "plain"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)
    monkeypatch.setenv("PROBLEMSETTING_ROOT", str(tmp_path / "checkout"))
    assert judges.problems_root() == (tmp_path / "checkout").resolve()


def test_the_fallback_does_not_read_the_problems_override_into_the_toolkit_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``PROBLEMS_ROOT`` names the mount, never the checkout the image is built from."""
    monkeypatch.setenv("PROBLEMSETTING_ROOT", str(tmp_path))
    monkeypatch.setenv(judges.PROBLEMS_ROOT_ENV, str(tmp_path / "problems"))
    assert judges.toolkit_root() == tmp_path.resolve()
    assert judges.problems_root() == (tmp_path / "problems").resolve()


def test_the_two_names_stay_distinct_under_a_problemset_repo(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = write_problemset(tmp_path / "problemset")
    monkeypatch.chdir(repo)
    monkeypatch.setenv("PROBLEMSETTING_ROOT", str(tmp_path / "checkout"))
    assert judges.problems_root() == repo / "problems"
    assert judges.toolkit_root() == (tmp_path / "checkout").resolve()


# ---------------------------------------------------------------------------
# Problem arguments: the two accepted forms
# ---------------------------------------------------------------------------


def test_a_bare_name_resolves_under_the_problems_root(tmp_path: Path, monkeypatch) -> None:
    repo = write_problemset(tmp_path / "problemset")
    monkeypatch.chdir(repo)
    assert judges.resolve_problem("suma") == repo / "problems" / "suma"


def test_a_path_including_problems_resolves_from_cwd(tmp_path: Path, monkeypatch) -> None:
    repo = write_problemset(tmp_path / "problemset")
    monkeypatch.chdir(repo)
    assert judges.resolve_problem("problems/suma") == repo / "problems" / "suma"


def test_both_forms_name_the_same_directory(tmp_path: Path, monkeypatch) -> None:
    repo = write_problemset(tmp_path / "problemset")
    monkeypatch.chdir(repo)
    assert judges.resolve_problem("suma") == judges.resolve_problem("problems/suma")


def test_a_cwd_relative_directory_wins_with_no_problemset_structure(
    tmp_path: Path, monkeypatch
) -> None:
    """The behaviour every existing caller relies on: cwd decides."""
    problem = tmp_path / "demo-ab"
    problem.mkdir()
    monkeypatch.chdir(tmp_path)
    assert judges.resolve_problem("demo-ab") == problem


def test_a_dot_directory_still_resolves_relative_to_cwd(tmp_path: Path, monkeypatch) -> None:
    problem = tmp_path / "demo"
    problem.mkdir()
    monkeypatch.chdir(problem)
    assert judges.resolve_problem(".") == problem


def test_an_ambiguous_name_is_refused_naming_both_directories(
    tmp_path: Path, monkeypatch
) -> None:
    """Silently picking one of two real problems is the failure worth refusing."""
    repo = write_problemset(tmp_path / "problemset")
    (repo / "suma").mkdir()  # same name beside problems/, a different directory
    monkeypatch.chdir(repo)
    with pytest.raises(JudgeError) as excinfo:
        judges.resolve_problem("suma")
    message = str(excinfo.value)
    assert str(repo / "suma") in message
    assert str(repo / "problems" / "suma") in message


def test_an_explicitly_prefixed_path_is_not_treated_as_a_bare_name(
    tmp_path: Path, monkeypatch
) -> None:
    """``./suma`` is a path the author spelled out, so it may not be refused."""
    repo = write_problemset(tmp_path / "problemset")
    (repo / "suma").mkdir()  # a different directory of the same name
    monkeypatch.chdir(repo)
    assert judges.resolve_problem("./suma") == repo / "suma"
    assert judges.resolve_problem("./problems/suma") == repo / "problems" / "suma"


def test_a_parent_directory_argument_still_resolves_relative_to_cwd(
    tmp_path: Path, monkeypatch
) -> None:
    """``..`` is a path: it must behave as before, not become a problem name.

    Joined to cwd and left unnormalised, exactly as ``Path.cwd() / problem`` did.
    """
    repo = write_problemset(tmp_path / "problemset")
    child = repo / "problems" / "suma"
    monkeypatch.chdir(child)
    assert judges.resolve_problem("..").resolve() == repo / "problems"


def test_the_same_directory_reached_two_ways_is_not_ambiguous(
    tmp_path: Path, monkeypatch
) -> None:
    """``problems/suma`` from the repo root IS ``problems_root/suma``, so no clash."""
    repo = write_problemset(tmp_path / "problemset")
    monkeypatch.chdir(repo / "problems")
    assert judges.resolve_problem("suma") == repo / "problems" / "suma"


def test_a_missing_name_names_the_root_that_was_used(tmp_path: Path, monkeypatch) -> None:
    repo = write_problemset(tmp_path / "problemset")
    monkeypatch.chdir(repo)
    with pytest.raises(JudgeError) as excinfo:
        judges.resolve_problem("absent")
    message = str(excinfo.value)
    assert "absent" in message
    assert str(repo / "problems" / "absent") in message
    assert str(repo / "problems") in message


# ---------------------------------------------------------------------------
# new: where the problem is created
# ---------------------------------------------------------------------------


def scaffold(argv: list[str], monkeypatch, cwd: Path) -> int:
    monkeypatch.chdir(cwd)
    return cli.main(argv)


def test_new_creates_under_the_problems_root_at_a_problemset_repo_root(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    from problemsetting import meta as meta_mod

    repo = write_problemset(tmp_path / "problemset")
    assert scaffold(["new", "nuevo"], monkeypatch, repo) == 0
    assert (repo / "problems" / "nuevo" / "meta.yml").is_file()
    assert not (repo / "nuevo").exists()
    capsys.readouterr()
    assert meta_mod.load(repo / "problems" / "nuevo")[1].model == "standard"


def test_new_creates_under_the_problems_root_when_run_there_directly(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    repo = write_problemset(tmp_path / "problemset")
    assert scaffold(["new", "nuevo"], monkeypatch, repo / "problems") == 0
    assert (repo / "problems" / "nuevo" / "meta.yml").is_file()
    capsys.readouterr()


def test_new_keeps_cwd_relative_placement_away_from_a_problemset_repo(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    plain = tmp_path / "plain"
    plain.mkdir()
    assert scaffold(["new", "demo-ab"], monkeypatch, plain) == 0
    assert (plain / "demo-ab" / "meta.yml").is_file()
    capsys.readouterr()


def test_new_leaves_a_deeper_cwd_alone(tmp_path: Path, monkeypatch, capsys) -> None:
    """A cwd inside the tree is not teleported to the problems root."""
    repo = write_problemset(tmp_path / "problemset")
    deep = repo / "problems" / "suma"
    assert scaffold(["new", "hijo"], monkeypatch, deep) == 0
    assert (deep / "hijo" / "meta.yml").is_file()
    assert not (repo / "problems" / "hijo").exists()
    capsys.readouterr()


def test_the_destination_rule_is_the_one_the_command_uses(
    tmp_path: Path, monkeypatch
) -> None:
    """The seam is a function, so the rule can be read without running `new`."""
    from problemsetting import scaffold as scaffold_mod

    repo = write_problemset(tmp_path / "problemset")
    monkeypatch.chdir(repo)
    assert scaffold_mod.destination_for("suma") == repo / "problems" / "suma"
    monkeypatch.chdir(tmp_path)
    assert scaffold_mod.destination_for("suma") == tmp_path / "suma"


def test_new_obeys_the_override_even_at_a_problemset_repo_root(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    """The override is where problems live, so `new` and `verify` must agree."""
    store = tmp_path / "store"
    store.mkdir()
    repo = write_problemset(tmp_path / "problemset")
    monkeypatch.setenv(judges.PROBLEMS_ROOT_ENV, str(store))
    assert scaffold(["new", "nuevo"], monkeypatch, repo) == 0
    assert (store / "nuevo" / "meta.yml").is_file()
    assert not (repo / "problems" / "nuevo").exists()
    capsys.readouterr()


def test_new_obeys_the_override_from_a_plain_directory(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    store = tmp_path / "store"
    store.mkdir()
    plain = tmp_path / "plain"
    plain.mkdir()
    monkeypatch.setenv(judges.PROBLEMS_ROOT_ENV, str(store))
    assert scaffold(["new", "demo-ab"], monkeypatch, plain) == 0
    assert (store / "demo-ab" / "meta.yml").is_file()
    assert not (plain / "demo-ab").exists()
    capsys.readouterr()


def test_the_scaffold_destination_is_where_the_override_points(
    tmp_path: Path, monkeypatch
) -> None:
    from problemsetting import scaffold as scaffold_mod

    store = tmp_path / "store"
    store.mkdir()
    monkeypatch.setenv(judges.PROBLEMS_ROOT_ENV, str(store))
    monkeypatch.chdir(tmp_path)
    assert scaffold_mod.destination_for("suma") == store / "suma"


# ---------------------------------------------------------------------------
# The module's own contract
# ---------------------------------------------------------------------------


def test_the_override_variable_is_named_problems_root() -> None:
    assert judges.PROBLEMS_ROOT_ENV == "PROBLEMS_ROOT"


def test_the_detection_markers_are_the_vendoring_signature() -> None:
    assert judges.PROBLEMS_DIRNAME == "problems"
    assert re.fullmatch(r"vendor[/\\]problemsetting", str(judges.VENDORED_TOOLKIT))

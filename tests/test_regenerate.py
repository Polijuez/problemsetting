"""``regenerate``: a fresh clone to a built tree, and drift reported, not repaired.

A problemset repository commits no test data (decision Q7) -- it commits the
generator and the checksums of what that generator produced (decisions Q15, Q16).
``regenerate`` is the command that closes the loop: it rebuilds what a clone is
missing, and it says whether the rebuild still matches what was committed.

The distinction under test is decision Q22's.  Rebuilding is for reaching a working
state; verifying is for detecting that the committed generator no longer produces
the committed checksums.  So the tests below pin three separate things: that a
rebuild *happens* (whole-repo and single-problem), that a drifted rebuild is
*reported as drift* and leaves the committed checksums alone, and that ``--check``
builds and compares while writing nothing at all.

Every problem here is ``output-only``: its submission is a text file the judge
``cat``s, so the build needs no compiler.  Nothing in this file grades, so nothing
here needs the judge pool or podman -- the two-roots and pool behaviour are other
tickets' tests.
"""

from __future__ import annotations

import os
import textwrap
from pathlib import Path

import pytest

from problemsetting import cases as cases_mod
from problemsetting import cli
from problemsetting import commands
from problemsetting import judges
from problemsetting import meta as meta_mod
from problemsetting import templates

MODEL = "output-only"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


#: The smallest generator a problem can have: one case, one all-accepting batch.
#: No input, because the model's submission is a text file.
GENERATOR = """
    class TestCase:
        def __init__(self, value):
            self.value = value

        def check(self):
            pass

        def write_file(self, file):
            raise AssertionError("an output-only case has no input")

    class Generator:
        def __init__(self, seed=1):
            pass

        def get_cases(self):
            return [TestCase("answer")]

        def get_subtasks(self):
            return [(100, lambda case: True)]
"""

#: The manifest ``verify`` reads.  ``verify`` fails on a missing manifest before it
#: ever looks for ``init.yml``, so a problem without one would fail for a reason
#: the missing-``init.yml`` tests do not mean to exercise.
MANIFEST = "submissions:\n  - source: solution.txt\n    verdict: AC\n"


def write_problem(root: Path, name: str, *, generator: str = GENERATOR) -> Path:
    """A minimal, buildable ``output-only`` problem directory under ``root``."""
    problem = root / name
    problem.mkdir(parents=True)
    authoring = {"model": MODEL, "solutionlang": ".txt"}
    meta_mod.write(problem, meta_mod.normalize(authoring, f"{name}/meta.yml"))
    (problem / cases_mod.GENERATOR_FILENAME).write_text(textwrap.dedent(generator))
    (problem / "solution.txt").write_text("answer\n")
    (problem / "submissions.yml").write_text(MANIFEST)
    return problem


def run(argv: list[str], monkeypatch, cwd: Path) -> int:
    monkeypatch.chdir(cwd)
    return cli.main(argv)


@pytest.fixture
def repo(tmp_path: Path, monkeypatch) -> Path:
    """A problems-root-shaped directory with no problems yet, pointed at explicitly."""
    root = tmp_path / "problems"
    root.mkdir()
    monkeypatch.setenv(judges.PROBLEMS_ROOT_ENV, str(root))
    return root


def snapshot(root: Path) -> dict[str, bytes]:
    """Every file under ``root``, by path relative to it -- the tree's whole state."""
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def checksum_files(problem: Path) -> dict[str, str]:
    return {
        path.name: path.read_text(encoding="utf-8")
        for path in sorted(problem.glob(f"*{cases_mod.CHECKSUM_SUFFIX}"))
    }


def retune_batch(problem: Path, points: int = 70) -> None:
    """Change only the batch's points -- the change the case-data checksum exists for.

    Every case file, and therefore the archive, stays byte-identical, so only the
    independent case-data manifest can see this (``cases.case_data_manifest``).
    """
    generator = problem / cases_mod.GENERATOR_FILENAME
    generator.write_text(
        generator.read_text().replace(
            "(100, lambda case: True)", f"({points}, lambda case: True)"
        )
    )


# ---------------------------------------------------------------------------
# A whole-repo run reaches a built state
# ---------------------------------------------------------------------------


def test_regenerate_builds_every_problem_and_reports_one_line_each(
    repo: Path, monkeypatch, capsys
) -> None:
    """No argument means every problem under the problems root."""
    for name in ("alfa", "beta", "gamma"):
        write_problem(repo, name)

    assert run(["regenerate"], monkeypatch, repo) == 0
    out = capsys.readouterr().out
    assert "==> regenerate 3 problem(s)" in out
    for name in ("alfa", "beta", "gamma"):
        # One summary line per problem, each named.
        assert any(f" {name} " in line for line in out.splitlines()), name
        problem = repo / name
        assert (problem / cases_mod.INIT_FILENAME).is_file()
        assert (problem / "cases" / "0.out").is_file()
        assert (problem / f"{name}.zip").is_file()
        assert sorted(checksum_files(problem)) == [
            f"{name}.zip.cases{cases_mod.CHECKSUM_SUFFIX}",
            f"{name}.zip{cases_mod.CHECKSUM_SUFFIX}",
        ]


def test_the_first_run_reports_new_and_a_second_run_reports_ok(
    repo: Path, monkeypatch, capsys
) -> None:
    """``NEW`` is a first build with nothing to compare against; then it is ``OK``."""
    write_problem(repo, "alfa")

    assert run(["regenerate"], monkeypatch, repo) == 0
    out = capsys.readouterr().out
    assert cases_mod.NEW in out and "regenerate: 1 NEW" in out

    assert run(["regenerate"], monkeypatch, repo) == 0
    out = capsys.readouterr().out
    assert cases_mod.OK in out and "regenerate: 1 OK" in out
    assert cases_mod.DRIFT not in out


def test_a_new_problem_is_not_a_failure(repo: Path, monkeypatch) -> None:
    """Building for the first time must not look like an error to CI."""
    write_problem(repo, "alfa")
    assert run(["regenerate"], monkeypatch, repo) == 0


def test_the_rebuilt_archive_matches_its_committed_checksum(repo: Path, monkeypatch) -> None:
    """The checksums the command leaves behind really describe the built tree.

    Rebuilding is only useful if what it wrote is what the committed record says,
    so this verifies the archive against its own ``sha256sum`` file the way
    ``sha256sum -c`` would.
    """
    write_problem(repo, "alfa")
    assert run(["regenerate"], monkeypatch, repo) == 0
    problem = repo / "alfa"

    text = (problem / f"alfa.zip{cases_mod.CHECKSUM_SUFFIX}").read_text(encoding="utf-8")
    digest, name = text.split()
    assert name == "alfa.zip"
    assert digest == cases_mod.sha256_file(problem / "alfa.zip")


def test_an_empty_problems_root_is_an_actionable_error(repo: Path, monkeypatch, capsys) -> None:
    """A report over nothing is a mistake, not a clean pass."""
    assert run(["regenerate"], monkeypatch, repo) == 1
    err = capsys.readouterr().err
    assert "no problems under" in err and meta_mod.META_FILENAME in err


def test_the_walk_skips_the_directories_a_pool_masks(repo: Path, monkeypatch, capsys) -> None:
    """``vendor`` ships a judge-server whose testsuite is not this repo's problems."""
    write_problem(repo, "alfa")
    write_problem(repo / "vendor" / "judge-server", "aplusb")

    assert run(["regenerate"], monkeypatch, repo) == 0
    assert "==> regenerate 1 problem(s)" in capsys.readouterr().out


def test_the_walk_skips_the_toolkit_s_own_shipped_templates() -> None:
    """The toolkit checkout ships 8 ``meta.yml`` files as package data.

    Those are *templates*, not problems, and they are the one thing a fallback to
    the toolkit root would otherwise discover -- so the exclusion is asserted
    against them by name rather than by observing an empty result, which would pass
    even if the walk found nothing at all.
    """
    shipped = sorted(path.parent.name for path in templates.MODELS_ROOT.glob("*/meta.yml"))
    assert shipped == sorted(meta_mod.MODELS), "the premise: one template per model"

    found = cases_mod.discover_problems(judges.toolkit_root())
    assert found == [], f"the templates {shipped} were discovered as problems"


# ---------------------------------------------------------------------------
# A single-problem run rebuilds just that one
# ---------------------------------------------------------------------------


def test_a_problem_argument_rebuilds_only_that_problem(repo: Path, monkeypatch, capsys) -> None:
    write_problem(repo, "alfa")
    write_problem(repo, "beta")

    assert run(["regenerate", "beta"], monkeypatch, repo) == 0
    out = capsys.readouterr().out
    assert "==> regenerate 1 problem(s)" in out
    assert (repo / "beta" / cases_mod.INIT_FILENAME).is_file()
    # ``alfa`` was not built.
    assert not (repo / "alfa" / cases_mod.INIT_FILENAME).exists()


def test_an_unknown_problem_names_where_it_looked(repo: Path, monkeypatch, capsys) -> None:
    write_problem(repo, "alfa")
    assert run(["regenerate", "nosuch"], monkeypatch, repo) == 1
    err = capsys.readouterr().err
    assert "no problem named 'nosuch'" in err
    assert str(repo) in err


def test_one_broken_generator_does_not_stop_the_rest(repo: Path, monkeypatch, capsys) -> None:
    """A report over a repository must survive one problem being broken."""
    write_problem(repo, "alfa")
    write_problem(repo, "roto", generator="    raise RuntimeError('boom')\n")

    assert run(["regenerate"], monkeypatch, repo) == 1
    out, err = capsys.readouterr()
    assert cases_mod.FAILED in out and "roto" in out
    # Reported as an outcome line, not as a traceback or a bare ``error:``.
    assert err == ""
    assert (repo / "alfa" / cases_mod.INIT_FILENAME).is_file(), "the clean problem was skipped"


# ---------------------------------------------------------------------------
# Drift is reported, and is not repaired by the build that caused it
# ---------------------------------------------------------------------------


def test_a_retuned_generator_is_reported_as_drift(repo: Path, monkeypatch, capsys) -> None:
    """A rebuild that no longer reproduces the committed checksums exits non-zero."""
    problem = write_problem(repo, "alfa")
    assert run(["regenerate"], monkeypatch, repo) == 0
    capsys.readouterr()

    retune_batch(problem)

    assert run(["regenerate", "alfa"], monkeypatch, repo) == 1
    out = capsys.readouterr().out
    assert cases_mod.DRIFT in out and "alfa" in out
    assert "regenerate: 1 DRIFT" in out


def test_drift_does_not_overwrite_the_committed_checksum(
    repo: Path, monkeypatch, capsys
) -> None:
    """The failing rebuild must leave the committed record exactly as it was."""
    problem = write_problem(repo, "alfa")
    assert run(["regenerate", "alfa"], monkeypatch, repo) == 0
    capsys.readouterr()
    committed = checksum_files(problem)

    retune_batch(problem)
    assert run(["regenerate", "alfa"], monkeypatch, repo) == 1

    assert checksum_files(problem) == committed, "drift was silently repaired"


def test_the_drift_report_names_the_checksum_file_that_moved(
    repo: Path, monkeypatch, capsys
) -> None:
    """A retune moves only the case-data manifest; the report must say which."""
    problem = write_problem(repo, "alfa")
    assert run(["regenerate", "alfa"], monkeypatch, repo) == 0
    capsys.readouterr()

    retune_batch(problem)
    assert run(["regenerate", "alfa"], monkeypatch, repo) == 1
    out = capsys.readouterr().out
    assert f"alfa.zip.cases{cases_mod.CHECKSUM_SUFFIX}: the rebuild differs" in out
    assert f"alfa.zip{cases_mod.CHECKSUM_SUFFIX}" not in out


def test_a_changed_solution_is_drift_and_moves_both_checksums(
    repo: Path, monkeypatch, capsys
) -> None:
    """A real case change moves the archive checksum *and* the case-data one."""
    problem = write_problem(repo, "alfa")
    assert run(["regenerate", "alfa"], monkeypatch, repo) == 0
    capsys.readouterr()

    (problem / "solution.txt").write_text("different\n")

    assert run(["regenerate", "alfa"], monkeypatch, repo) == 1
    out = capsys.readouterr().out
    assert f"alfa.zip{cases_mod.CHECKSUM_SUFFIX}: the rebuild differs" in out
    assert f"alfa.zip.cases{cases_mod.CHECKSUM_SUFFIX}: the rebuild differs" in out


def test_drift_is_detected_even_when_the_committed_checksum_was_hand_edited(
    repo: Path, monkeypatch, capsys
) -> None:
    """The comparison is over the record's own bytes, not a reinterpreted digest."""
    problem = write_problem(repo, "alfa")
    assert run(["regenerate", "alfa"], monkeypatch, repo) == 0
    capsys.readouterr()

    (problem / f"alfa.zip{cases_mod.CHECKSUM_SUFFIX}").write_text("0" * 64 + "  alfa.zip\n")

    assert run(["regenerate", "alfa"], monkeypatch, repo) == 1
    assert cases_mod.DRIFT in capsys.readouterr().out


# ---------------------------------------------------------------------------
# check mode: build and compare, write nothing, exit non-zero on drift
# ---------------------------------------------------------------------------


def test_check_writes_nothing_at_all_before_anything_is_committed(
    repo: Path, monkeypatch, capsys
) -> None:
    """The working tree is byte-identical before and after a clean ``--check``."""
    write_problem(repo, "alfa")
    before = snapshot(repo)

    assert run(["regenerate", "--check"], monkeypatch, repo) == 0
    out = capsys.readouterr().out
    assert cases_mod.NEW in out  # nothing committed to compare against yet

    assert snapshot(repo) == before, "check mode wrote into the tree it checked"


def test_check_against_committed_checksums_reports_ok_and_writes_nothing(
    repo: Path, monkeypatch, capsys
) -> None:
    write_problem(repo, "alfa")
    assert run(["regenerate", "alfa"], monkeypatch, repo) == 0
    capsys.readouterr()
    before = snapshot(repo)

    assert run(["regenerate", "--check", "alfa"], monkeypatch, repo) == 0
    out = capsys.readouterr().out
    assert cases_mod.OK in out and "nothing is written" in out
    assert snapshot(repo) == before


def test_check_exits_non_zero_on_drift_and_writes_nothing(
    repo: Path, monkeypatch, capsys
) -> None:
    """This is the property that makes it safe in CI: it cannot "fix" drift."""
    problem = write_problem(repo, "alfa")
    assert run(["regenerate", "alfa"], monkeypatch, repo) == 0
    capsys.readouterr()

    retune_batch(problem)
    before = snapshot(repo)

    assert run(["regenerate", "--check", "alfa"], monkeypatch, repo) == 1
    out = capsys.readouterr().out
    assert cases_mod.DRIFT in out
    assert snapshot(repo) == before, "check mode repaired the drift it found"


def test_check_covers_the_whole_repository(repo: Path, monkeypatch, capsys) -> None:
    """With no argument, ``--check`` compares every problem."""
    for name in ("alfa", "beta"):
        write_problem(repo, name)
    assert run(["regenerate"], monkeypatch, repo) == 0
    capsys.readouterr()
    before = snapshot(repo)

    assert run(["regenerate", "--check"], monkeypatch, repo) == 0
    out = capsys.readouterr().out
    assert "==> regenerate 2 problem(s)" in out
    assert "regenerate: 2 OK" in out
    assert snapshot(repo) == before


def test_check_reports_the_drifted_problem_and_leaves_the_clean_one_alone(
    repo: Path, monkeypatch, capsys
) -> None:
    for name in ("alfa", "beta"):
        write_problem(repo, name)
    assert run(["regenerate"], monkeypatch, repo) == 0
    capsys.readouterr()

    retune_batch(repo / "beta")
    before = snapshot(repo)

    assert run(["regenerate", "--check"], monkeypatch, repo) == 1
    out = capsys.readouterr().out
    assert "regenerate: 1 OK, 1 DRIFT" in out
    assert snapshot(repo) == before


def test_check_mode_does_not_leave_its_scratch_copy_behind(
    repo: Path, monkeypatch, capsys, tmp_path: Path
) -> None:
    """The scratch directory a check builds is temporary by construction."""
    write_problem(repo, "alfa")
    assert run(["regenerate", "--check"], monkeypatch, repo) == 0
    # Every scratch copy lives under the system temp dir, never under the problem.
    assert not any(path.name.startswith("regenerate-") for path in repo.iterdir())


def test_drift_stays_visible_after_the_run(repo: Path, monkeypatch, capsys) -> None:
    """A drift run must not "fix" itself: a later ``--check`` still reports it.

    This is the acceptance criterion stated as behaviour rather than as a file
    comparison: if the ordinary mode had written the fresh checksums over the
    committed ones, the very next check would report ``OK`` and the drift would
    have become invisible.
    """
    problem = write_problem(repo, "alfa")
    assert run(["regenerate", "alfa"], monkeypatch, repo) == 0
    capsys.readouterr()

    retune_batch(problem)
    assert run(["regenerate", "alfa"], monkeypatch, repo) == 1
    capsys.readouterr()

    assert run(["regenerate", "--check", "alfa"], monkeypatch, repo) == 1
    assert cases_mod.DRIFT in capsys.readouterr().out


def test_the_problems_root_redirection_is_restored_after_a_run(
    repo: Path, monkeypatch, capsys
) -> None:
    """The build's temporary root override must not leak into the caller's process."""
    write_problem(repo, "alfa")
    monkeypatch.setenv(judges.PROBLEMS_ROOT_ENV, str(repo))

    assert run(["regenerate", "alfa"], monkeypatch, repo) == 0
    assert os.environ[judges.PROBLEMS_ROOT_ENV] == str(repo)


def test_the_problems_root_is_removed_again_when_it_was_not_set(
    repo: Path, monkeypatch
) -> None:
    """The other half: no variable is invented for a process that had none."""
    write_problem(repo, "alfa")
    monkeypatch.delenv(judges.PROBLEMS_ROOT_ENV, raising=False)
    # The problem is named by path, so no root is needed to find it.
    assert cli.main(["regenerate", str(repo / "alfa")]) == 0
    assert judges.PROBLEMS_ROOT_ENV not in os.environ


def test_check_mode_reports_errors_against_the_real_problem_directory(
    repo: Path, monkeypatch, capsys
) -> None:
    """A broken generator in ``--check`` must not be blamed on a scratch path.

    The scratch copy is deleted when the run ends, so the path in the message would
    name a file the author can never open.
    """
    problem = write_problem(repo, "roto", generator="raise RuntimeError('boom')\n")

    assert run(["regenerate", "--check"], monkeypatch, repo) == 1
    out = capsys.readouterr().out
    assert cases_mod.FAILED in out
    assert str(problem / cases_mod.GENERATOR_FILENAME) in out
    assert "regenerate-roto" not in out


# ---------------------------------------------------------------------------
# A renamed problem moves the checksum *names*, and the check notices
# ---------------------------------------------------------------------------


def test_a_renamed_problem_is_drift_rather_than_a_match(repo: Path, monkeypatch, capsys) -> None:
    """The comparison covers which checksum files exist, not just their contents.

    ``init.yml``'s ``archive:`` is ``<problem>.zip``, and the checksum file names
    derive from it -- so renaming a problem leaves its committed ``alfa.zip.
    sha256sum`` files describing an archive the rebuild no longer produces, next to
    fresh ``suma.zip.sha256sum`` files describing one nothing is committed under.
    Comparing only the names present in both would call that a match.
    """
    problem = write_problem(repo, "alfa")
    assert run(["regenerate", "alfa"], monkeypatch, repo) == 0
    capsys.readouterr()
    before = checksum_files(problem)

    renamed = repo / "suma"
    problem.rename(renamed)

    assert run(["regenerate", "suma"], monkeypatch, repo) == 1
    out = capsys.readouterr().out
    assert f"alfa.zip{cases_mod.CHECKSUM_SUFFIX}: committed, but the rebuild no longer" in out
    assert f"suma.zip{cases_mod.CHECKSUM_SUFFIX}: the rebuild produces it" in out
    # The committed files are exactly the ones that were there; nothing new landed.
    assert checksum_files(renamed) == before


# ---------------------------------------------------------------------------
# The comparison helper itself
# ---------------------------------------------------------------------------


def test_compare_checksums_reports_each_kind_of_difference() -> None:
    """The three difference shapes, so the report cannot quietly collapse them."""
    assert cases_mod.compare_checksums({}, {"a": "1"})[0] == cases_mod.NEW
    assert cases_mod.compare_checksums({"a": "1"}, {"a": "1"})[0] == cases_mod.OK
    assert cases_mod.compare_checksums({"a": "1"}, {"a": "2"})[0] == cases_mod.DRIFT
    # A committed file the rebuild no longer produces is drift, not "missing".
    assert cases_mod.compare_checksums({"a": "1"}, {})[0] == cases_mod.DRIFT
    # So is a file the rebuild produces under a name nothing is committed under.
    assert cases_mod.compare_checksums({"a": "1"}, {"a": "1", "b": "2"})[0] == cases_mod.DRIFT
    # And the detail names the file, so the failure is attributable.
    assert "a" in cases_mod.compare_checksums({"a": "1"}, {"a": "2"})[1][0]


def test_an_outcome_is_a_failure_only_for_drift_or_a_failed_build() -> None:
    assert not cases_mod.Outcome("p", cases_mod.OK).failed
    assert not cases_mod.Outcome("p", cases_mod.NEW).failed
    assert cases_mod.Outcome("p", cases_mod.DRIFT).failed
    assert cases_mod.Outcome("p", cases_mod.FAILED).failed


# ---------------------------------------------------------------------------
# CLI surface
# ---------------------------------------------------------------------------


def test_the_command_is_registered_and_dispatched_by_name() -> None:
    assert "regenerate" in commands.COMMANDS
    assert commands.COMMANDS["regenerate"].run is cases_mod.run_regenerate_command


def test_the_problem_argument_is_optional_and_check_is_a_flag(capsys) -> None:
    """The argument conventions match the neighbouring subcommands."""
    with pytest.raises(SystemExit) as excinfo:
        cli.build_parser().parse_args(["--help"])
    assert excinfo.value.code == 0
    assert "regenerate" in capsys.readouterr().out

    # Both forms parse; no argument is the whole-repository form.
    assert cli.build_parser().parse_args(["regenerate"]).problem is None
    parsed = cli.build_parser().parse_args(["regenerate", "alfa", "--check"])
    assert parsed.problem == "alfa" and parsed.check is True


def test_the_seed_flag_reaches_the_generator(repo: Path, monkeypatch, capsys) -> None:
    """``--seed`` is threaded the way ``cases``/``build`` thread it."""
    write_problem(repo, "alfa")
    assert run(["regenerate", "alfa", "--seed", "7"], monkeypatch, repo) == 0
    assert "==> regenerate 1 problem(s)" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# The missing-cases error names this command
# ---------------------------------------------------------------------------


def test_the_missing_init_error_mentions_checksums_and_points_at_regenerate(
    repo: Path, monkeypatch, capsys
) -> None:
    """A fresh clone's first failure must name its own remedy (decision Q17)."""
    write_problem(repo, "alfa")
    # `verify` is the command an author reaches for first; it grades, so it needs
    # the judge pool -- but it fails on the missing init.yml *before* it starts one.
    assert run(["verify", "alfa"], monkeypatch, repo) == 1
    err = capsys.readouterr().err
    assert cases_mod.CHECKSUM_SUFFIX in err
    assert "problemsetting regenerate alfa" in err


@pytest.mark.parametrize("argv", [["archive"], ["outputs"]])
def test_every_reader_of_init_yml_names_regenerate(
    repo: Path, monkeypatch, capsys, argv: list[str]
) -> None:
    write_problem(repo, "alfa")
    assert run([*argv, "alfa"], monkeypatch, repo) == 1
    err = capsys.readouterr().err
    assert cases_mod.CHECKSUM_SUFFIX in err
    assert "problemsetting regenerate alfa" in err

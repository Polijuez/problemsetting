"""The archive is reproducible per input, and its committed checksums prove it.

Two clones of the same problem must build the same archive bytes (decision Q21),
otherwise the ``.sha256sum`` files a problemset repository commits (decisions Q7,
Q15, Q16) cannot survive a fresh clone.  The property under test is exactly that:
same inputs, same bytes -- including when the source files' modification times
differ, which is the field that used to leak into the archive.

The archive must stay a *readable* archive: DMOJ opens it with ``zipfile`` and
reads a case's expected answer out of it (``dmoj/problem.py:212-221,273-275``), so
a reproducible archive that no longer opens or serves the right bytes would be a
regression, not a fix.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import textwrap
import zipfile
from pathlib import Path

import pytest

from problemsetting import cases as cases_mod
from problemsetting import cli
from problemsetting import judges
from problemsetting import meta as meta_mod
from problemsetting import templates

STANDARD_MODEL = "standard"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def write_problem(root: Path, name: str, *, generator: str) -> Path:
    """Create a minimal problem directory whose generator is ``generator``."""
    problem = root / name
    problem.mkdir(parents=True)
    authoring = {"model": STANDARD_MODEL, "solutionlang": ".cpp"}
    meta_mod.write(problem, meta_mod.normalize(authoring, f"{name}/meta.yml"))
    (problem / cases_mod.GENERATOR_FILENAME).write_text(textwrap.dedent(generator))
    return problem


#: Two cases, one all-accepting subtask: the smallest shape ``standard`` allows.
GENERATOR = """
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


def build_cases(root: Path, name: str, monkeypatch) -> Path:
    """``cases`` + hand-written expected outputs + ``archive``, no compiler needed."""
    problem = write_problem(root, name, generator=GENERATOR)
    assert run(["cases", name], monkeypatch, root) == 0
    for index in range(2):
        (problem / "cases" / f"{index}.out").write_text(f"{index}\n")
    assert run(["archive", name], monkeypatch, root) == 0
    return problem


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def committed_checksum(problem: Path, filename: str) -> str:
    """The digest recorded in a ``sha256sum``-format file, as the first field."""
    return (problem / filename).read_text(encoding="utf-8").split()[0]


def checksum_file_digest(problem: Path, filename: str) -> str:
    """SHA-256 of a checksum *file*, for comparing manifests as a whole.

    A ``.cases.sha256sum`` has one line per case file, so its first field only
    describes the first case; tests about the whole record hash the file.
    """
    return sha256(problem / filename)


# ---------------------------------------------------------------------------
# Reproducibility (acceptance criterion: byte-identity across two builds)
# ---------------------------------------------------------------------------


def test_two_builds_of_the_same_source_are_byte_identical(
    tmp_path, monkeypatch, capsys
) -> None:
    """Two independent builds, whose mtimes differ, produce identical bytes.

    The two problems live in separate directories and their case files are given
    genuinely different modification times -- a fixed instant in the past versus
    "now" -- which is the difference a fresh clone introduces.  ZIP stores
    second-resolution timestamps, so merely touching a file to *now* would not
    diverge: the old ``ZipFile.write`` implementation embedded identical times
    and stayed byte-identical.  A far-apart, fixed mtime is what makes this test
    fail against that implementation, which is the property under test.
    """
    first = build_cases(tmp_path / "one", "demo", monkeypatch)
    capsys.readouterr()
    second = build_cases(tmp_path / "two", "demo", monkeypatch)
    capsys.readouterr()

    # A rebuild of the *same* problem, after its cases are backdated, must not
    # change its archive either -- the property is about the inputs, not the
    # checkout that happens to hold them.
    distant = 1_000_000_000  # 2001-09-09, far from "now" at second resolution.
    for case in second.glob("cases/*"):
        os.utime(case, (distant, distant))
    assert run(["archive", "demo"], monkeypatch, tmp_path / "two") == 0

    assert sha256(first / "demo.zip") == sha256(second / "demo.zip")
    assert (first / "demo.zip").read_bytes() == (second / "demo.zip").read_bytes()


def test_both_committed_checksums_agree_across_builds(tmp_path, monkeypatch, capsys) -> None:
    """The archive checksum *and* the case-data checksum survive a rebuild."""
    first = build_cases(tmp_path / "one", "demo", monkeypatch)
    capsys.readouterr()
    second = build_cases(tmp_path / "two", "demo", monkeypatch)
    capsys.readouterr()

    for name in (cases_mod.archive_checksum_name("demo.zip"), cases_mod.case_data_checksum_name("demo.zip")):
        assert (first / name).is_file(), name
        assert (first / name).read_text(encoding="utf-8") == (
            second / name
        ).read_text(encoding="utf-8")


def test_the_archive_checksum_is_the_archive_bytes(tmp_path, monkeypatch, capsys) -> None:
    problem = build_cases(tmp_path, "demo", monkeypatch)
    capsys.readouterr()
    recorded = committed_checksum(problem, "demo.zip.sha256sum")
    assert recorded == sha256(problem / "demo.zip")
    # ``sha256sum -c`` reads the same line, so the committed file needs no parser.
    line = (problem / "demo.zip.sha256sum").read_text(encoding="utf-8")
    assert line == f"{recorded}  demo.zip\n"


def test_the_case_data_checksum_hashes_the_case_files_themselves(
    tmp_path, monkeypatch, capsys
) -> None:
    """The second checksum is independent of packaging: real per-file digests."""
    problem = build_cases(tmp_path, "demo", monkeypatch)
    capsys.readouterr()
    manifest = (problem / "demo.zip.cases.sha256sum").read_text(encoding="utf-8")
    lines = manifest.splitlines()
    assert [line.split("  ", 1)[1] for line in lines] == [
        "cases/0.in", "cases/0.out", "cases/1.in", "cases/1.out", "init.yml",
    ]
    # The grading structure rides along as a comment, so the file still verifies
    # with ``sha256sum -c`` while a change in *grouping* also moves this digest.
    assert lines[-1].startswith("# ")
    for line in lines[:4]:
        digest, name = line.split("  ", 1)
        assert digest == sha256(problem / name)


def test_the_rebuilt_archive_is_still_readable_by_the_judge(
    tmp_path, monkeypatch, capsys
) -> None:
    """The archive DMOJ opens must serve exactly the case files on disk.

    A reproducible archive that no longer opens, or that serves different bytes
    than ``init.yml`` names, would fail the moment the judge tried to read an
    expected answer out of it (``dmoj/problem.py``: ``getinfo`` + ``open``).
    """
    problem = build_cases(tmp_path, "demo", monkeypatch)
    capsys.readouterr()
    document = cases_mod.load_init(problem)
    referenced = cases_mod.referenced_cases(document, str(problem / cases_mod.INIT_FILENAME))

    with zipfile.ZipFile(problem / "demo.zip") as archive:
        assert archive.testzip() is None
        assert sorted(archive.namelist()) == sorted(referenced)
        for name in referenced:
            assert archive.read(name) == (problem / name).read_bytes()


def test_a_rebuilt_archive_keeps_the_same_verdicts(tmp_path, monkeypatch, capsys) -> None:
    """Deterministic bytes must not mean degraded contents: two builds grade alike.

    Both archives carry the same member bytes, which is what the judge consumes,
    so the verdicts a real pool reports cannot differ between them.
    """
    first = build_cases(tmp_path / "one", "demo", monkeypatch)
    capsys.readouterr()
    second = build_cases(tmp_path / "two", "demo", monkeypatch)
    capsys.readouterr()

    contents = []
    for problem in (first, second):
        with zipfile.ZipFile(problem / "demo.zip") as archive:
            contents.append({name: archive.read(name) for name in archive.namelist()})
    assert contents[0] == contents[1]


# ---------------------------------------------------------------------------
# Checksums detect changes and mismatches (acceptance criterion)
# ---------------------------------------------------------------------------


def test_changing_the_generator_changes_both_checksums(tmp_path, monkeypatch, capsys) -> None:
    """A real case change must move both digests, so drift is visible as drift."""
    problem = build_cases(tmp_path, "demo", monkeypatch)
    capsys.readouterr()
    before = {
        name: (problem / name).read_text(encoding="utf-8")
        for name in ("demo.zip.sha256sum", "demo.zip.cases.sha256sum")
    }

    (problem / "generator.py").write_text(
        textwrap.dedent(GENERATOR).replace("TestCase(2)", "TestCase(3)")
    )
    assert run(["cases", "demo"], monkeypatch, tmp_path) == 0
    for index in range(2):
        (problem / "cases" / f"{index}.out").write_text(f"{index}\n")
    assert run(["archive", "demo"], monkeypatch, tmp_path) == 0
    capsys.readouterr()

    after = {
        name: (problem / name).read_text(encoding="utf-8")
        for name in ("demo.zip.sha256sum", "demo.zip.cases.sha256sum")
    }
    assert after != before
    assert after["demo.zip.sha256sum"] != before["demo.zip.sha256sum"]
    assert after["demo.zip.cases.sha256sum"] != before["demo.zip.cases.sha256sum"]


def test_a_grouping_only_change_moves_the_case_checksum_not_the_archive(
    tmp_path, monkeypatch, capsys
) -> None:
    """Retuning only the points moves the case-data checksum, and nothing else.

    This is the case the second checksum exists for: the case *files* are
    untouched, so the archive is byte-identical -- an archive-only checksum would
    report "no change" for a generator that now grades differently.  The
    structure digest recorded in the case-data manifest is what catches it.
    """
    problem = build_cases(tmp_path, "demo", monkeypatch)
    capsys.readouterr()
    before_archive = sha256(problem / "demo.zip")
    before = checksum_file_digest(problem, "demo.zip.cases.sha256sum")

    (problem / "generator.py").write_text(
        textwrap.dedent(GENERATOR).replace("(100, lambda", "(60, lambda")
    )
    assert run(["cases", "demo"], monkeypatch, tmp_path) == 0
    assert run(["archive", "demo"], monkeypatch, tmp_path) == 0
    capsys.readouterr()
    assert sha256(problem / "demo.zip") == before_archive, "case files did not change"
    assert checksum_file_digest(problem, "demo.zip.cases.sha256sum") != before


def test_tampering_the_archive_is_a_detectable_mismatch(tmp_path, monkeypatch, capsys) -> None:
    """``sha256sum -c`` accepts the clean archive and rejects a tampered one.

    The check is the consumer's own: the file is plain ``sha256sum`` output, so
    the verification the committed checksum exists to support is that tool's exit
    status -- exactly what ``regenerate --check`` (decision Q22) will call.
    Asserting only that two hashes differ would prove SHA-256 works, not that the
    toolkit recorded the right digest.
    """
    if shutil.which("sha256sum") is None:
        pytest.skip("sha256sum is not installed")
    problem = build_cases(tmp_path, "demo", monkeypatch)
    capsys.readouterr()
    name = "demo.zip.sha256sum"

    def verify() -> int:
        return subprocess.run(
            ["sha256sum", "-c", name], cwd=problem, capture_output=True, text=True
        ).returncode

    # Both committed files verify cleanly, and the tampered archive is rejected.
    for committed_name in (name, "demo.zip.cases.sha256sum"):
        assert subprocess.run(
            ["sha256sum", "-c", committed_name], cwd=problem, capture_output=True
        ).returncode == 0
    archive_path = problem / "demo.zip"
    archive_path.write_bytes(archive_path.read_bytes() + b"\x00")
    assert verify() != 0


def test_tampering_a_case_is_a_detectable_mismatch(tmp_path, monkeypatch, capsys) -> None:
    """A case changed without rebuilding is caught by the case-data checksum."""
    problem = build_cases(tmp_path, "demo", monkeypatch)
    capsys.readouterr()
    committed = (problem / "demo.zip.cases.sha256sum").read_text(encoding="utf-8")
    assert sha256(problem / "cases" / "0.in") in committed

    (problem / "cases" / "0.in").write_text("tampered\n")
    recomputed = cases_mod.case_data_manifest(
        problem,
        cases_mod.referenced_cases(
            cases_mod.load_init(problem), str(problem / cases_mod.INIT_FILENAME)
        ),
        cases_mod.load_init(problem),
    )
    # Text-to-text, so this fails whenever the record stops describing the cases.
    assert recomputed != committed
    assert sha256(problem / "cases" / "0.in") not in committed


# ---------------------------------------------------------------------------
# Naming: derived from the declared archive, not hard-coded
# ---------------------------------------------------------------------------


def test_checksum_names_follow_the_declared_archive_name() -> None:
    assert cases_mod.archive_checksum_name("suma.zip") == "suma.zip.sha256sum"
    assert cases_mod.case_data_checksum_name("suma.zip") == "suma.zip.cases.sha256sum"
    assert cases_mod.archive_checksum_name("custom.bundle") == "custom.bundle.sha256sum"


def test_a_non_default_archive_name_gets_a_matching_checksum(
    tmp_path, monkeypatch, capsys
) -> None:
    """``archive:`` is the source of truth for the checksum's name too."""
    problem = build_cases(tmp_path, "demo", monkeypatch)
    capsys.readouterr()
    # Keep the declared membership, change only the declared archive filename.
    init = (problem / cases_mod.INIT_FILENAME).read_text(encoding="utf-8")
    (problem / cases_mod.INIT_FILENAME).write_text(
        init.replace("archive: demo.zip", "archive: suma.zip")
    )
    (problem / "demo.zip.sha256sum").unlink()
    (problem / "demo.zip.cases.sha256sum").unlink()

    assert run(["archive", "demo"], monkeypatch, tmp_path) == 0
    capsys.readouterr()

    assert (problem / "suma.zip").is_file()
    assert (problem / "suma.zip.sha256sum").is_file()
    assert (problem / "suma.zip.cases.sha256sum").is_file()
    assert committed_checksum(problem, "suma.zip.sha256sum") == sha256(problem / "suma.zip")
    assert not (problem / "demo.zip.sha256sum").exists()


def test_the_same_cases_packaged_under_a_different_name_share_the_case_checksum(
    tmp_path, monkeypatch, capsys
) -> None:
    """Packaging changes only the archive checksum; the case data is unchanged.

    That separation is why two checksums are committed: a rename is not a change
    in the cases, and the case-data checksum must not claim it is.
    """
    problem = build_cases(tmp_path, "demo", monkeypatch)
    capsys.readouterr()
    before = (problem / "demo.zip.cases.sha256sum").read_text(encoding="utf-8")

    init = (problem / cases_mod.INIT_FILENAME).read_text(encoding="utf-8")
    (problem / cases_mod.INIT_FILENAME).write_text(
        init.replace("archive: demo.zip", "archive: suma.zip")
    )
    assert run(["archive", "demo"], monkeypatch, tmp_path) == 0
    capsys.readouterr()

    assert (problem / "suma.zip.cases.sha256sum").read_text(encoding="utf-8") == before


def test_the_archive_helper_is_the_single_writer(tmp_path) -> None:
    """``write_reproducible_zip`` pins what ``ZipFile.write`` would leak."""
    source_a = tmp_path / "a.in"
    source_b = tmp_path / "b.in"
    source_a.write_text("1\n")
    source_b.write_text("2\n")
    source_a.touch()
    archive = tmp_path / "out.zip"
    cases_mod.write_reproducible_zip(
        archive, [("cases/1.in", source_b), ("cases/0.in", source_a)]
    )

    with zipfile.ZipFile(archive) as handle:
        infos = handle.infolist()
    # Sorted membership, pinned timestamps, pinned attributes and level.
    assert [info.filename for info in infos] == ["cases/0.in", "cases/1.in"]
    for info in infos:
        assert info.date_time == cases_mod.ARCHIVE_DATE_TIME
        assert info.external_attr == cases_mod.ARCHIVE_MEMBER_ATTR
        assert info.compress_type == zipfile.ZIP_DEFLATED


def test_the_compression_level_is_pinned_and_honoured(tmp_path, monkeypatch) -> None:
    """The named level reaches zlib: the constant is load-bearing, not decorative.

    ``ZipFile``'s default level (``-1``) is "zlib's default", an undocumented
    constant that a Python upgrade may change -- which would silently rewrite the
    archive bytes.  Writing the same payload at level 0 and at the pinned level
    must produce different collapsed sizes, or the constant is not being applied.
    """
    payload = ("a" * 200 + "\n") * 50
    source = tmp_path / "case.in"
    source.write_text(payload)

    def build(path: Path) -> int:
        cases_mod.write_reproducible_zip(path, [("case.in", source)])
        with zipfile.ZipFile(path) as handle:
            return handle.getinfo("case.in").compress_size

    pinned = build(tmp_path / "pinned.zip")
    monkeypatch.setattr(cases_mod, "ARCHIVE_COMPRESS_LEVEL", 0)
    stored = build(tmp_path / "stored.zip")
    # Level 0 still frames the member in deflate stored blocks, so it is never
    # *smaller* than the payload; the pinned level compresses it far below.
    assert stored >= len(payload)
    assert pinned < len(payload)


# ---------------------------------------------------------------------------
# The rebuilt archive still grades (acceptance criterion, opt-in)
# ---------------------------------------------------------------------------

#: Grading needs the 15 GB judge image and rootless podman, so it is opt-in the
#: same way ``tests/test_judge_pool.py`` is (decision Q29)::
#:
#:     PROBLEMSETTING_JUDGE_TESTS=1 uv run pytest tests/test_archive_reproducible.py
JUDGE_OPT_IN = os.environ.get("PROBLEMSETTING_JUDGE_TESTS") == "1"


@pytest.mark.skipif(
    not JUDGE_OPT_IN, reason="set PROBLEMSETTING_JUDGE_TESTS=1 (needs the judge image and podman)"
)
@pytest.mark.skipif(shutil.which("podman") is None, reason="podman is not installed")
def test_two_rebuilt_archives_grade_to_the_same_verdicts() -> None:
    """Byte-identical archives must grade identically through the real judge.

    The zip-level tests above prove the two builds carry the same member bytes;
    this is the end-to-end proof that the judge -- which reads each expected
    answer out of the archive (``dmoj/problem.py``: ``getinfo`` + ``open``) --
    still accepts the model solution, and reports the same verdicts, for both.

    The problems are built *inside the toolkit checkout* on purpose: a pool
    mounts that checkout at ``/problems``, so a source outside it is not
    gradeable.  Names are distinct from ``test_judge_pool.py``'s so the two
    suites can run in the same session.
    """
    root = judges.repository_root()
    previous = Path.cwd()
    os.chdir(root)
    names = ("t03-repro-a", "t03-repro-b")
    for name in names:
        shutil.rmtree(root / name, ignore_errors=True)
        shutil.copytree(
            templates.template_dir(STANDARD_MODEL),
            root / name,
            ignore=shutil.ignore_patterns(*templates.TEMPLATE_IGNORE),
        )
    try:
        for name in names:
            assert cli.main(["build", name]) == 0
        # A distant mtime on the second build must not change its archive: a
        # mere ``touch()`` (mtime = now) does not diverge at ZIP's 2-second
        # resolution, so it would not exercise the pinning at all.
        distant = 1_000_000_000
        for case in (root / names[1] / "cases").glob("*"):
            os.utime(case, (distant, distant))
        assert cli.main(["archive", names[1]]) == 0

        assert (root / names[0] / f"{names[0]}.zip").read_bytes() == (
            root / names[1] / f"{names[1]}.zip"
        ).read_bytes()

        if not judges.image_exists():
            pytest.skip(judges.build_instructions())
        container = "polijuez-judge-t03-repro"
        config = judges.write_config(judges.pool_dir(root) / "judge.yml")
        judges.stop_container(container)
        try:
            judges.launch_container(container, problems_root=root, config=config)
        except judges.JudgeError as error:
            pytest.skip(str(error))
        try:
            assert judges.wait_ready(container)
            assert judges.update_problems(container) == "200 As you wish."
            for name in names:
                grading = judges.submit(
                    container,
                    name,
                    "CPP17",
                    root / name / "solution.cpp",
                    time_limit=2.0,
                    memory_limit=262144,
                )
                assert grading.compile_error is None, grading.raw
                assert grading.accepted, grading.raw
                assert grading.verdicts["AC"] == 21, grading.raw
        finally:
            judges.stop_container(container)
    finally:
        os.chdir(previous)
        for name in names:
            shutil.rmtree(root / name, ignore_errors=True)


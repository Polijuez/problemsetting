"""The judge substrate: verdict parsing, the generated config, and the pool.

Everything that would need a running 15 GB container is exercised here through
its pure parts -- verdict parsing, the config the judge is handed, container
naming and discovery -- so the suite stays fast and offline.  The container paths
themselves were verified by hand against a real pool (see the ticket's report);
what is asserted below is the logic whose mistakes are silent: a mis-parsed
verdict, a config whose glob form breaks problem discovery, a name that does not
round-trip.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from problemsetting import judges
from problemsetting.errors import JudgeError

# ---------------------------------------------------------------------------
# Verdict parsing
# ---------------------------------------------------------------------------

#: Real ``dmoj`` output, including the ANSI the judge emits when it is not told
#: ``--no-ansi`` and the ``--`` that marks a case skipped after a batch failure.
UNBATCHED = """\
Start grading demo-ab/1 in CPP17...
Test case  1 AC [0.003s (0.003s wall) | 3964kb | 14 switches (1 involuntary)]
Test case  2 WA [0.003s (0.003s wall) | 4012kb | 14 switches (1 involuntary)]
Test case  3 TLE [1.001s (1.002s wall) | 3980kb | 12 switches (1 involuntary)]
Test case  4 --
Done grading demo-ab/1.
"""

BATCHED = """\
Start grading demo/2 in CPP17...
Batch #1
Test case  1 AC [0.002s (0.002s wall) | 3000kb | 10 switches (1 involuntary)]
Test case  2 AC [0.002s (0.002s wall) | 3000kb | 10 switches (1 involuntary)]
Batch #2
Test case  1 WA [0.002s (0.002s wall) | 3000kb | 10 switches (1 involuntary)]
Test case  2 --
Done grading demo/2.
"""

ANSI = (
    "Start grading demo/3 in CPP17...\n"
    "Test case  1 \x1b[1m\x1b[32mAC\x1b[0m [0.003s (0.003s wall) | 3964kb | 14 switches]\n"
    "Done grading demo/3.\n"
)


def test_parse_verdicts_counts_each_code() -> None:
    assert judges.parse_verdicts(UNBATCHED) == {"AC": 1, "WA": 1, "TLE": 1, "--": 1}


def test_parse_verdicts_ignores_the_prompt_and_progress_lines() -> None:
    # "Start grading" and "Done grading" both mention grading and must not be
    # mistaken for results.
    assert judges.parse_verdicts("Start grading demo/1 in CPP17...\nDone grading demo/1.\n") == {}


def test_parse_verdicts_sees_a_verdict_wrapped_in_ansi() -> None:
    assert judges.parse_verdicts(ANSI) == {"AC": 1}


def test_parse_batches_groups_cases_under_each_batch() -> None:
    assert judges.parse_batches(BATCHED) == [["AC", "AC"], ["WA", "--"]]


def test_parse_batches_ignores_cases_outside_any_batch() -> None:
    # A single-batch problem run without batches (no `test_cases:` subtasks) has
    # no section headers, so there is nothing to group under: the caller reads
    # parse_verdicts instead.
    assert judges.parse_batches(UNBATCHED) == []


def test_batched_case_numbers_restart_per_batch() -> None:
    # The same "Test case 1" appears in both batches; grouping by section, not
    # by case number, is what keeps them apart.
    batches = judges.parse_batches(BATCHED)
    assert len(batches) == 2
    assert batches[0][0] == batches[1][0] == "AC" or batches[1][0] == "WA"


# ---------------------------------------------------------------------------
# Grading summaries
# ---------------------------------------------------------------------------


def test_grading_accepted_needs_all_cases_ac() -> None:
    grading = judges.parse_grading(UNBATCHED, 0)
    assert not grading.accepted
    assert grading.failures == 3  # WA + TLE + the skipped "--"


def test_skipped_cases_count_as_failures() -> None:
    # "--" means the case never ran because its batch already failed, which is
    # exactly what should fail a subtask.
    grading = judges.parse_grading(BATCHED, 0)
    assert grading.failures == 2
    assert not grading.accepted


def test_a_clean_run_is_accepted() -> None:
    raw = "Test case  1 AC [0.002s] \nTest case  2 AC [0.002s] \n"
    assert judges.parse_grading(raw, 0).accepted


def test_compile_errors_are_reported_as_such_not_as_zero_verdicts() -> None:
    raw = "Start grading demo/1 in CPP17...\nFailed compiling submission!\nmain.cpp:3: error: expected ';'\n"
    grading = judges.parse_grading(raw, 0)
    assert grading.compile_error == "Failed compiling submission!"
    assert grading.verdicts == {}


def test_an_unknown_problem_is_reported_rather_than_looking_empty() -> None:
    raw = "error: unknown problem 'no-such-problem'\n"
    grading = judges.parse_grading(raw, 0)
    assert "unknown problem" in (grading.run_error or "")
    assert grading.compile_error is None


def test_a_nonzero_status_with_no_verdicts_is_a_run_error_not_a_compile_error() -> None:
    """Infrastructure failures must not masquerade as the CE verdict.

    ``compile_error`` is a *result* -- the submission failed to build, which DMOJ
    reports as ``CE`` -- so it may satisfy an entry declaring ``verdict: CE``.
    A non-zero status with no verdicts and no compile marker is the *absence* of
    a result: the pool client reports its own timeout this way
    (``error: command timed out after 600s``, exit 102).  Classifying that as a
    compile error let an infrastructure failure satisfy a declared ``CE`` and
    report a pass on a submission that was never compiled.
    """
    grading = judges.parse_grading("error: command timed out after 600s\n", 102)
    assert grading.compile_error is None
    assert grading.run_error == "error: command timed out after 600s"


def test_a_genuine_compile_error_is_still_a_compile_error() -> None:
    raw = "Failed compiling submission!\nmain.cpp:3: error: expected ';'\n"
    grading = judges.parse_grading(raw, 1)
    assert grading.compile_error == "Failed compiling submission!"
    assert grading.run_error is None


def test_verdict_lines_win_over_a_nonzero_status() -> None:
    # A grading failure is not a command failure; DMOJ reports it through
    # verdicts, so a status of 1 must not override them.
    grading = judges.parse_grading("Test case  1 WA [0.001s] \n", 1)
    assert grading.compile_error is None
    assert grading.verdicts == {"WA": 1}


# ---------------------------------------------------------------------------
# The generated judge config
# ---------------------------------------------------------------------------


def test_write_config_uses_the_single_segment_glob(tmp_path) -> None:
    path = judges.write_config(tmp_path / "judge.yml")
    assert path.read_text() == "problem_storage_globs:\n  - /problems/**/\n"


def test_config_glob_form_is_the_one_get_problem_root_accepts() -> None:
    # `get_problem_root()` filters candidates with
    # `fnmatch(problem_config, os.path.join(glob, 'init.yml'))`, so the glob has
    # to match `<root>/<problem>/init.yml` and nothing deeper.  `/**/*` would also
    # match nested dirs and let a wrong root win.
    text = judges.write_config.__doc__ or ""
    assert "/problems/**/" in text
    assert "fnmatch" in text or "get_problem_roots" in text


# ---------------------------------------------------------------------------
# Pool naming and sizing
# ---------------------------------------------------------------------------


def test_default_count_is_capped() -> None:
    count = judges.default_count()
    assert 1 <= count <= judges.MAX_DEFAULT_COUNT


def test_default_count_uses_nproc_and_never_zero() -> None:
    assert judges.default_count() == max(
        1, min(__import__("os").cpu_count() or 1, judges.MAX_DEFAULT_COUNT)
    )


def test_container_names_round_trip_through_their_ordinal() -> None:
    name = judges.container_name(3)
    assert name == f"{judges.NAME_PREFIX}3"
    assert name.removeprefix(judges.NAME_PREFIX) == "3"


def test_ensure_pool_rejects_a_non_positive_count(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("PROBLEMSETTING_ROOT", str(tmp_path))
    monkeypatch.setattr(judges, "ensure_image", lambda root=None: None)
    with pytest.raises(JudgeError, match="at least 1"):
        judges.ensure_pool(0, root=tmp_path)


# ---------------------------------------------------------------------------
# The image-missing error
# ---------------------------------------------------------------------------


def test_build_instructions_name_the_command_and_the_repo(tmp_path) -> None:
    message = judges.build_instructions(tmp_path)
    assert "problemsetting judges build" in message
    assert judges.IMAGE in message
    assert "github.com/DMOJ/judge-server" in message
    assert f"TAG={judges.BUILD_ARG_TAG}" in message


def test_require_image_raises_with_instructions_when_absent(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(judges, "image_exists", lambda image=judges.IMAGE: False)
    with pytest.raises(JudgeError) as excinfo:
        judges.require_image(tmp_path)
    assert "judges build" in str(excinfo.value)


def test_repository_root_honours_the_override(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("PROBLEMSETTING_ROOT", str(tmp_path))
    assert judges.repository_root() == tmp_path.resolve()


def test_container_path_maps_under_the_mount(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("PROBLEMSETTING_ROOT", str(tmp_path))
    source = tmp_path / "demo" / "solution.cpp"
    source.parent.mkdir()
    source.write_text("int main(){}\n")
    assert judges.container_path(source) == "/problems/demo/solution.cpp"


def test_container_path_refuses_a_file_outside_the_mount(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("PROBLEMSETTING_ROOT", str(tmp_path / "here"))
    (tmp_path / "here").mkdir()
    with pytest.raises(JudgeError, match="outside the directory mounted at"):
        judges.container_path(tmp_path / "elsewhere" / "solution.cpp")


# ---------------------------------------------------------------------------
# The pool's mount and capabilities
# ---------------------------------------------------------------------------


def test_sandbox_capabilities_match_production() -> None:
    # Mirrors `juez/scripts/run.sh`'s spawn: the cptbox sandbox needs all three.
    assert set(judges.SANDBOX_CAPS) == {"SYS_PTRACE", "SETUID", "SETGID"}


def test_the_image_is_the_one_production_uses() -> None:
    assert judges.IMAGE == "localhost/dmoj/judge-tier3:latest"
    assert judges.BASE_IMAGE == "dmoj/runtimes-tier3"


def test_the_container_command_bypasses_the_entrypoint_deliberately() -> None:
    # The image's entrypoint runs `dmoj-cli`, which exits after one command; the
    # pool runs the launcher instead, so it repeats the entrypoint's environment.
    command = judges._container_command()
    for setting in ("DMOJ_IN_DOCKER=1", "HOME=/home/judge", "PYTHONIOENCODING=utf8"):
        assert setting in command
    assert "launcher.py" in command
    assert "setpriv" in command


def test_container_state_is_none_for_a_missing_container(monkeypatch) -> None:
    monkeypatch.setattr(
        judges,
        "_capture",
        lambda args: subprocess.CompletedProcess(args, 125, "", "no such container"),
    )
    assert judges.container_state("polijuez-judge-99") is None


def test_list_containers_sorts_by_ordinal(monkeypatch) -> None:
    output = (
        f"{judges.NAME_PREFIX}10 exited\n"
        f"{judges.NAME_PREFIX}2 running\n"
        "some-other-container running\n"
        f"{judges.NAME_PREFIX}1 running\n"
    )
    monkeypatch.setattr(
        judges, "_capture", lambda args: subprocess.CompletedProcess(args, 0, output, "")
    )
    assert judges.list_containers() == [
        (1, f"{judges.NAME_PREFIX}1", "running"),
        (2, f"{judges.NAME_PREFIX}2", "running"),
        (10, f"{judges.NAME_PREFIX}10", "exited"),
    ]
    assert judges.running_containers() == [f"{judges.NAME_PREFIX}1", f"{judges.NAME_PREFIX}2"]


def test_stop_removes_autostopped_containers_too(monkeypatch, capsys) -> None:
    """An idle container autostops and stays behind in the ``exited`` state.

    ``judges stop`` used to iterate :func:`running_containers` only, so those
    exited containers were invisible to it and accumulated silently -- six
    survived several stops in practice.  Stop must mean "remove ours", whatever
    state they are in.
    """
    output = (
        f"{judges.NAME_PREFIX}1 running\n"
        f"{judges.NAME_PREFIX}2 exited\n"
        f"{judges.NAME_PREFIX}3 exited\n"
    )
    monkeypatch.setattr(
        judges, "_capture", lambda args: subprocess.CompletedProcess(args, 0, output, "")
    )
    removed: list[str] = []
    monkeypatch.setattr(
        judges,
        "stop_container",
        lambda name: (removed.append(name), True)[1],
    )

    assert judges._action_stop(None) == 0
    assert removed == [
        f"{judges.NAME_PREFIX}1",
        f"{judges.NAME_PREFIX}2",
        f"{judges.NAME_PREFIX}3",
    ]
    assert len(capsys.readouterr().out.strip().splitlines()) == 3


# ---------------------------------------------------------------------------
# The mounted root, read back from the container
# ---------------------------------------------------------------------------

#: A fake ``podman inspect``: it answers the state query and the mount query
#: differently, the way the real one does, so a test can drive both without
#: caring which order :func:`judges.require_mount` asks in.
def fake_inspect(monkeypatch, *, state: str | None, mount: Path | None) -> list[list[str]]:
    """Install a ``_capture`` that reports ``state`` and ``mount``; return calls."""
    calls: list[list[str]] = []

    def capture(args: list[str]) -> subprocess.CompletedProcess:
        calls.append(args)
        if args[:2] == ["podman", "ps"]:
            return subprocess.CompletedProcess(args, 0, "", "")
        if state is None:
            return subprocess.CompletedProcess(args, 125, "", "no such container")
        if judges._MOUNT_SOURCE_FORMAT in args:
            source = "" if mount is None else str(mount)
            return subprocess.CompletedProcess(args, 0, source, "")
        return subprocess.CompletedProcess(args, 0, state, "")

    monkeypatch.setattr(judges, "_capture", capture)
    return calls


def test_the_mounted_root_is_read_back_from_the_container(monkeypatch) -> None:
    """Not from anything the toolkit wrote down (decision Q23)."""
    fake_inspect(monkeypatch, state="running", mount=Path("/srv/otro/problems"))
    assert judges.container_mount("polijuez-judge-1") == Path("/srv/otro/problems").resolve()
    # The format asks for the mount whose destination is the problems mount, so
    # an unrelated bind mount cannot be mistaken for it.
    assert judges.PROBLEMS_MOUNT in judges._MOUNT_SOURCE_FORMAT
    assert ".Destination" in judges._MOUNT_SOURCE_FORMAT


def test_a_container_with_no_mount_at_problems_reports_none(monkeypatch) -> None:
    fake_inspect(monkeypatch, state="running", mount=None)
    assert judges.container_mount("polijuez-judge-1") is None


def test_a_missing_container_has_no_mounted_root(monkeypatch) -> None:
    fake_inspect(monkeypatch, state=None, mount=None)
    assert judges.container_mount("polijuez-judge-99") is None


def test_a_pool_on_the_same_root_is_still_adopted(tmp_path, monkeypatch) -> None:
    """"Already running does not double-start" survives the identity check."""
    fake_inspect(monkeypatch, state="running", mount=tmp_path)
    monkeypatch.setattr(
        judges,
        "launch_container",
        lambda *args, **kwargs: pytest.fail("a matching container must not be re-created"),
    )
    assert judges.start_container(1, tmp_path, tmp_path / "judge.yml") == "running"


def test_a_pool_on_a_different_root_is_refused_naming_both(
    tmp_path, monkeypatch
) -> None:
    """The silent wrong-grade this ticket exists to stop."""
    mine = tmp_path / "mine" / "problems"
    theirs = tmp_path / "theirs" / "problems"
    fake_inspect(monkeypatch, state="running", mount=theirs)
    monkeypatch.setattr(
        judges,
        "launch_container",
        lambda *args, **kwargs: pytest.fail("a foreign container must not be replaced"),
    )
    with pytest.raises(JudgeError) as excinfo:
        judges.start_container(1, mine, tmp_path / "judge.yml")
    message = str(excinfo.value)
    assert str(mine.resolve()) in message
    assert str(theirs.resolve()) in message
    assert "judges stop" in message


def test_a_container_with_no_problems_mount_is_refused_too(tmp_path, monkeypatch) -> None:
    """A hand-made container is not adoptable either; the refusal says why."""
    mine = tmp_path / "mine"
    fake_inspect(monkeypatch, state="running", mount=None)
    with pytest.raises(JudgeError) as excinfo:
        judges.start_container(1, mine, tmp_path / "judge.yml")
    message = str(excinfo.value)
    assert str(mine.resolve()) in message
    assert "no /problems mount" in message
    assert "judges stop" in message


def test_require_mount_lets_a_matching_container_through(tmp_path, monkeypatch) -> None:
    fake_inspect(monkeypatch, state="running", mount=tmp_path)
    assert judges.require_mount("polijuez-judge-1", tmp_path) is None


def test_require_mount_accepts_a_symlinked_root(tmp_path, monkeypatch) -> None:
    """The comparison is on resolved paths, not on spellings."""
    real = tmp_path / "real"
    real.mkdir()
    link = tmp_path / "link"
    link.symlink_to(real)
    fake_inspect(monkeypatch, state="running", mount=real)
    assert judges.require_mount("polijuez-judge-1", link) is None


def test_require_mount_is_silent_about_a_container_that_does_not_exist(
    tmp_path, monkeypatch
) -> None:
    """Nothing to adopt means nothing to refuse; the caller starts one instead."""
    fake_inspect(monkeypatch, state=None, mount=None)
    assert judges.require_mount("polijuez-judge-1", tmp_path) is None


def test_submit_refuses_to_grade_through_a_foreign_pool(tmp_path, monkeypatch) -> None:
    """Every grading path funnels through ``submit``, so the check lives there too.

    ``verify`` and ``stress`` reuse a *running* container rather than starting
    one (``_running_container``, ``containers``), so the refusal cannot be only
    in ``start_container``.
    """
    theirs = tmp_path / "theirs"
    theirs.mkdir()
    fake_inspect(monkeypatch, state="running", mount=theirs)
    monkeypatch.setattr(
        judges,
        "run_command",
        lambda *args, **kwargs: pytest.fail("nothing may be sent to a foreign pool"),
    )
    source = theirs / "solution.cpp"
    source.write_text("int main(){}\n", encoding="utf-8")
    with pytest.raises(JudgeError) as excinfo:
        judges.submit(
            "polijuez-judge-1",
            "suma",
            "CPP17",
            source,
            time_limit=1.0,
            memory_limit=262144,
            problems_root=tmp_path / "mine",
        )
    message = str(excinfo.value)
    assert str((tmp_path / "mine").resolve()) in message
    assert str(theirs.resolve()) in message


def test_status_reports_the_root_each_container_is_mounted_on(
    tmp_path, monkeypatch, capsys
) -> None:
    """So the mismatch is visible before a grading command is attempted."""
    mine = tmp_path / "mine"
    theirs = tmp_path / "theirs"
    output = f"{judges.NAME_PREFIX}1 running\n"
    mounts = {
        f"{judges.NAME_PREFIX}1": str(theirs),
    }

    def capture(args: list[str]) -> subprocess.CompletedProcess:
        if args[:2] == ["podman", "ps"]:
            return subprocess.CompletedProcess(args, 0, output, "")
        if judges._MOUNT_SOURCE_FORMAT in args:
            return subprocess.CompletedProcess(args, 0, mounts.get(args[2], ""), "")
        return subprocess.CompletedProcess(args, 0, "running", "")

    monkeypatch.setattr(judges, "_capture", capture)
    monkeypatch.setattr(judges, "image_exists", lambda image=judges.IMAGE: True)
    assert judges._action_status(type("A", (), {"count": 1})()) == 0
    printed = capsys.readouterr().out
    assert str(theirs.resolve()) in printed
    assert str(mine.resolve()) not in printed
    containers, _ = judges.pool_status(1)
    assert containers == [(f"{judges.NAME_PREFIX}1", "running", theirs.resolve())]

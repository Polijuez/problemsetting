"""``stress``: the small-case hook, the two passes, and what a run reports.

Everything here runs offline except the last section.  The pieces that decide
whether a run is trustworthy are pure: which seed reproduces which cases, that a
disagreement is the *judge's* verdict and not this module's comparison, that a
case's echoed output is attributed to the right case, and that "nothing ran" is
never reported as success.  Those are tested directly, against transcripts and
against a fake pool.

The judge calls themselves are the last section's, and they are opt-in: they need
the image, podman, and a minute of judge discovery.
"""

from __future__ import annotations

import base64
import os
import shutil
from pathlib import Path

import pytest

from problemsetting import cases as cases_mod
from problemsetting import judges, stress, templates
from problemsetting.errors import CaseError, JudgeError, OutputError

#: A real ``dmoj`` transcript from a pass A run, verbatim from a pool container:
#: the checker's feedback carries the submission's stdout, base64'd.
PASS_A = """\
Start grading stress-abstress-a0/22 in CPP17...
Test case  1 AC [0.004s (0.005s wall) | 4008kb | 14 switches (1 involuntary)] (stress-out:1:MAo=) 
Test case  2 AC [0.003s (0.004s wall) | 3988kb | 14 switches (1 involuntary)] (stress-out:2:Mwo=) 
Test case  3 WA [0.004s (0.004s wall) | 3888kb | 15 switches (2 involuntary)] (stress-out:3:Ngo=) 
Done grading stress-abstress-a0/22.
"""

#: A pass B transcript: case 2 was rejected, and the checker echoed both outputs.
PASS_B = """\
Start grading stress-abstress-b0/23 in CPP17...
Test case  1 AC [0.004s (0.005s wall) | 4008kb | 14 switches (1 involuntary)] 
Test case  2 WA [0.003s (0.004s wall) | 3988kb | 14 switches (1 involuntary)] (stress-diff:2:model=MTQ5Mg==:brute=MTQ5MQ==) 
Done grading stress-abstress-b0/23.
"""


def encode(text: str) -> str:
    return base64.b64encode(text.encode()).decode()


# ---------------------------------------------------------------------------
# Reading the judge's transcript
# ---------------------------------------------------------------------------


def test_each_case_is_paired_with_the_bytes_its_checker_echoed() -> None:
    found = stress.echoed_outputs(PASS_A)
    assert sorted(found) == [1, 2, 3]
    assert found[1].payload == b"0\n"
    assert found[2].payload == b"3\n"
    assert found[3].payload == b"6\n"


def test_a_rejected_case_reports_both_answers() -> None:
    found = stress.compared_outputs(PASS_B)
    assert found[2].verdict == "WA"
    assert found[2].payload == (b"1492", b"1491")


def test_a_case_without_an_echoed_output_carries_no_payload() -> None:
    """An ``AC`` case whose checker never ran has no bytes, and must not pretend otherwise."""
    found = stress.echoed_outputs("Test case  1 AC [0.004s (0.005s wall) | 4008kb]\n")
    assert found[1].payload is None


def test_a_payload_that_is_not_base64_is_not_read_as_bytes() -> None:
    """A transcript line that is not base64 must not decode to something arbitrary."""
    assert stress._decode("not base64!!") is None


def test_ansi_wrapped_transcripts_parse_the_same() -> None:
    wrapped = PASS_A.replace("AC", "\x1b[1;32mAC\x1b[0m")
    assert stress.echoed_outputs(wrapped)[1].payload == b"0\n"


def test_the_reader_round_trips_whatever_the_checkers_emit() -> None:
    """The checker grammar and its reader are one source, checked by behaviour.

    The checkers *interpolate* the format strings and the reader *derives* its regex
    from them, so the property to assert is the round trip: feed each checker's
    emitted feedback through the reader and get the same values back.  Asserting
    the literal appears in the generated source would be true by construction.
    """
    for case_position, payload in ((0, b"42\n"), (1, b"-7\n"), (2, b"")):
        echo = stress.OUT_FEEDBACK % (case_position + 1, encode(payload.decode()))
        line = f"Test case {case_position + 1:2d} AC [0.001s (0.001s wall) | 3000kb] ({echo}) "
        found = stress.echoed_outputs(line)
        assert found[case_position + 1].payload == payload

    diff = stress.DIFF_FEEDBACK % (2, encode("10\n"), encode("9\n"))
    line = f"Test case  2 WA [0.001s (0.001s wall) | 3000kb] ({diff}) "
    assert stress.compared_outputs(line)[2].payload == (b"10\n", b"9\n")


# ---------------------------------------------------------------------------
# Tiny cases: the seed is the reproducibility contract
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def generator_module():
    """The shipped ``standard`` template's own generator, loaded as author code."""
    import importlib.util
    import sys

    path = templates.template_dir("standard") / "generator.py"
    spec = importlib.util.spec_from_file_location("stress_generator", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["stress_generator"] = module
    spec.loader.exec_module(module)
    return module


def test_a_seed_reproduces_the_same_tiny_cases(generator_module) -> None:
    first = stress.small_cases(generator_module.Generator(1), 1234, 25, "generator.py")
    second = stress.small_cases(generator_module.Generator(1), 1234, 25, "generator.py")
    assert first == second
    assert len(first) == 25


def test_a_different_seed_produces_different_cases(generator_module) -> None:
    first = stress.small_cases(generator_module.Generator(1), 1, 25, "generator.py")
    second = stress.small_cases(generator_module.Generator(1), 2, 25, "generator.py")
    assert first != second


def test_the_hook_seed_is_independent_of_the_generators_own_seed(generator_module) -> None:
    """``--seed`` pins the hook, so the generator's own seed cannot change the cases."""
    first = stress.small_cases(generator_module.Generator(999), 77, 10, "generator.py")
    second = stress.small_cases(generator_module.Generator(1), 77, 10, "generator.py")
    assert first == second


def test_a_case_is_rendered_the_way_cases_renders_a_real_one(generator_module) -> None:
    assert stress.render(generator_module.TestCase(2, 3), 0, "generator.py") == "2 3\n"


def test_a_hook_returning_several_cases_per_call_is_accumulated() -> None:
    """A problem whose small inputs come in pairs writes its hook that way."""

    class Case:
        def __init__(self, n):
            self.n = n

        def write_file(self, file):
            file.write(f"{self.n}\n")

    class Generator:
        def gen_small(self, rand):
            n = rand.randint(0, 9)
            return [Case(n), Case(n)]

    texts = stress.small_cases(Generator(), 5, 8, "generator.py")
    assert len(texts) == 8
    # Results come in pairs, so every odd-indexed case repeats the one before it.
    assert texts[0::2] == texts[1::2]
    # And the same seed still reproduces them exactly.
    assert texts == stress.small_cases(Generator(), 5, 8, "generator.py")


def test_a_hook_returning_nothing_is_refused() -> None:
    class Generator:
        def gen_small(self, rand):
            return []

    with pytest.raises(CaseError, match="returned no cases"):
        stress.small_cases(Generator(), 1, 4, "generator.py")


def test_a_hook_raising_is_reported_with_the_generator_file() -> None:
    class Generator:
        def gen_small(self, rand):
            raise ZeroDivisionError("boom")

    with pytest.raises(CaseError, match=r"gen_small\(\) failed"):
        stress.small_cases(Generator(), 1, 4, "generator.py")


def test_a_case_without_write_file_is_refused() -> None:
    class Case:
        pass

    class Generator:
        def gen_small(self, rand):
            return [Case()]

    with pytest.raises(CaseError, match="write_file"):
        stress.small_cases(Generator(), 1, 4, "generator.py")


# ---------------------------------------------------------------------------
# Chunking and the scratch problems
# ---------------------------------------------------------------------------


def test_chunks_are_contiguous_and_cover_every_case() -> None:
    items = [str(index) for index in range(10)]
    chunks = stress.split(items, 3)
    assert [len(chunk) for chunk in chunks] == [4, 3, 3]
    assert [item for chunk in chunks for item in chunk] == items


def test_chunking_never_produces_an_empty_chunk() -> None:
    assert len(stress.split(["a", "b"], 5)) == 2


def test_scratch_init_is_a_flat_list_of_non_zero_point_cases() -> None:
    """Batches short-circuit; a stress run wants every disagreement, not the first."""
    text = stress.render_init(3, stress.DIFF_CHECKER)
    assert "batched" not in text
    assert text.count("points: 1") == 3
    assert "checker: diff.py" in text


def test_a_scratch_problem_has_every_file_its_init_yml_names(tmp_path: Path) -> None:
    directory = tmp_path / "stress-demo-a0"
    stress.write_scratch(
        directory, ["1 2\n", "3 4\n"], stress.ECHO_CHECKER, stress.ECHO_CHECKER_SOURCE
    )
    assert (directory / "echo.py").is_file()
    assert (directory / "cases" / "0.in").read_text() == "1 2\n"
    assert (directory / "cases" / "1.out").read_bytes() == b""
    init = (directory / "init.yml").read_text()
    assert "cases/0.in" in init and "cases/1.out" in init


def test_expected_outputs_are_written_verbatim(tmp_path: Path) -> None:
    directory = tmp_path / "stress-demo-b0"
    stress.write_scratch(directory, ["1 2\n"], stress.DIFF_CHECKER, stress.DIFF_CHECKER_SOURCE)
    stress.write_expected(directory, [b"3\n"])
    assert (directory / "cases" / "0.out").read_bytes() == b"3\n"


def test_scratch_cleanup_removes_the_whole_tree(tmp_path: Path) -> None:
    directory = tmp_path / "stress-demo-a0"
    stress.write_scratch(directory, ["1 2\n"], stress.ECHO_CHECKER, stress.ECHO_CHECKER_SOURCE)
    stress.remove_scratch([directory])
    assert not directory.exists()


def test_a_leftover_scratch_tree_is_replaced_not_reused(tmp_path: Path) -> None:
    """A killed run leaves its scratch problem behind; the next run must still work."""
    directory = tmp_path / "stress-demo-a0"
    (directory / "cases").mkdir(parents=True)
    (directory / "cases" / "stale.in").write_text("old\n")
    stress.write_scratch(directory, ["1 2\n"], stress.ECHO_CHECKER, stress.ECHO_CHECKER_SOURCE)
    assert not (directory / "cases" / "stale.in").exists()
    assert (directory / "cases" / "0.in").read_text() == "1 2\n"


def test_the_scratch_name_is_not_a_dot_directory() -> None:
    """DMOJ discovers problems with ``glob``, which skips hidden directories."""
    name = stress.scratch_name("demo", "a", 0)
    assert name == "stress-demo-a0"
    assert not name.startswith(".")


# ---------------------------------------------------------------------------
# The run: what it reports, and what it refuses to report
# ---------------------------------------------------------------------------


@pytest.fixture
def problem(tmp_path: Path) -> Path:
    """A minimal problem: ``meta.yml``, generator, model solution, brute, manifest."""
    (tmp_path / "meta.yml").write_text(
        "model: standard\nsolutionlang: .cpp\nlimits:\n  .cpp:\n    tl: 1.0\n    ml: 262144\n",
        encoding="utf-8",
    )
    (tmp_path / "generator.py").write_text(
        "class Case:\n"
        "    def write_file(self, f):\n"
        "        f.write('1\\n')\n"
        "\n"
        "\n"
        "class Generator:\n"
        "    def __init__(self, seed=0):\n"
        "        pass\n"
        "\n"
        "    def get_cases(self):\n"
        "        return [Case()]\n"
        "\n"
        "    def get_subtasks(self):\n"
        "        return [(100, lambda case: True)]\n"
        "\n"
        "    def gen_small(self, rand):\n"
        "        return [Case()]\n",
        encoding="utf-8",
    )
    (tmp_path / "solution.cpp").write_text("int main(){}\n", encoding="utf-8")
    (tmp_path / "submissions").mkdir()
    (tmp_path / "submissions" / "brute.cpp").write_text("int main(){}\n", encoding="utf-8")
    (tmp_path / "submissions.yml").write_text(
        "submissions:\n"
        "  - source: solution.cpp\n"
        "    role: model\n"
        "  - source: submissions/brute.cpp\n"
        "    role: brute\n",
        encoding="utf-8",
    )
    return tmp_path


def test_a_problem_without_the_hook_is_skipped_with_the_reason(
    problem: Path, monkeypatch, capsys
) -> None:
    (problem / "generator.py").write_text(
        (problem / "generator.py")
        .read_text()
        .replace("    def gen_small(self, rand):\n        return [Case()]\n", ""),
        encoding="utf-8",
    )
    monkeypatch.chdir(problem)
    assert stress.run_stress(".", count=3, seed=1) == 0
    out = capsys.readouterr().out
    assert "skipped" in out
    assert "no gen_small(rand)" in out
    assert "generator.py" in out


def test_a_problem_without_a_brute_force_is_skipped_with_the_reason(
    problem: Path, monkeypatch, capsys
) -> None:
    (problem / "submissions.yml").write_text(
        "submissions:\n  - source: solution.cpp\n    role: model\n", encoding="utf-8"
    )
    monkeypatch.chdir(problem)
    assert stress.run_stress(".", count=3, seed=1) == 0
    out = capsys.readouterr().out
    assert "skipped" in out
    assert "role: brute" in out and "submissions.yml" in out


def test_an_output_only_model_is_skipped_with_the_reason(
    problem: Path, monkeypatch, capsys
) -> None:
    (problem / "meta.yml").write_text("model: output-only\nsolutionlang: .txt\n", encoding="utf-8")
    monkeypatch.chdir(problem)
    assert stress.run_stress(".", count=3, seed=1) == 0
    assert "grades a text file" in capsys.readouterr().out


def test_a_case_count_below_one_is_refused(problem: Path, monkeypatch) -> None:
    monkeypatch.chdir(problem)
    with pytest.raises(CaseError, match="at least 1"):
        stress.run_stress(".", count=0, seed=1)

def test_a_missing_model_solution_names_the_declared_language(problem: Path, monkeypatch) -> None:
    # The manifest does not name the model solution: its path is the convention
    # `solution<solutionlang>`, so `stress` checks it itself.
    (problem / "submissions.yml").write_text(
        "submissions:\n  - source: submissions/brute.cpp\n    role: brute\n", encoding="utf-8"
    )
    (problem / "solution.cpp").unlink()
    monkeypatch.chdir(problem)
    with pytest.raises(OutputError, match="solutionlang: .cpp"):
        stress.run_stress(".", count=3, seed=1)


def test_no_tiny_cases_means_nothing_runs_and_that_is_reported(
    problem: Path, monkeypatch
) -> None:
    """``gen_small`` answering nothing must fail loudly, never report success."""

    class Empty:
        def gen_small(self, rand):
            return []

        def get_cases(self):
            return []

        def get_subtasks(self):
            return []

    monkeypatch.chdir(problem)
    monkeypatch.setattr(judges, "running_containers", lambda: ["fake-1"])
    monkeypatch.setattr(judges, "submit", lambda *args, **kwargs: pytest.fail("nothing to run"))
    monkeypatch.setattr(stress.cases_mod, "load_generator", lambda directory, seed=None: Empty())
    with pytest.raises(CaseError, match="returned no cases"):
        stress.run_stress(".", count=5, seed=1)


# ---------------------------------------------------------------------------
# The run, against a fake pool
# ---------------------------------------------------------------------------


class FakePool:
    """``submit`` answered from canned transcripts, with the calls recorded.

    ``answers`` is what the model solution "printed" per case, keyed by the scratch
    problem's name; ``disagreements`` is the set of case positions the brute force
    got wrong.  Nothing is compiled: this is about how a run drives the pool and
    reads it back.
    """

    def __init__(self, answers: dict[str, list[str]]):
        self.answers = answers
        self.disagreements: set[int] = set()
        self.calls: list[tuple[str, str, str]] = []

    def submit(self, name, problem, executor, source, *, time_limit, memory_limit, **_):
        self.calls.append((name, problem, executor))
        assert source.is_file(), source
        # Both passes name the same scratch problem's cases, so one table answers
        # them; only the checker's feedback differs between the two.
        pass_a = problem.rsplit("-", 1)[-1].startswith("a")
        answers = self.answers[problem.replace("-b", "-a")]
        lines = [f"Start grading {problem}/x in CPP17..."]
        for index, output in enumerate(answers):
            position = index + 1
            measure = "[0.001s (0.001s wall) | 3000kb]"
            if pass_a:
                lines.append(
                    f"Test case {position:2d} AC {measure} "
                    f"(stress-out:{position}:{encode(output)}) "
                )
            elif position in self.disagreements:
                lines.append(
                    f"Test case {position:2d} WA {measure} "
                    f"(stress-diff:{position}:model={encode(output)}:brute={encode('wrong\n')}) "
                )
            else:
                lines.append(f"Test case {position:2d} AC {measure} ")
        return judges.parse_grading("\n".join(lines) + "\n", 0)


@pytest.fixture
def fake_pool(tmp_path: Path, problem: Path, monkeypatch):
    """Point the run at one fake container.

    The problem is copied to ``zzz`` because the scratch problems are named after
    the problem directory, and the fake pool answers by that name.
    """
    shutil.copytree(problem, tmp_path / "zzz")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(judges, "running_containers", lambda: ["fake-1"])
    monkeypatch.setattr(judges, "update_problems", lambda name: "As you wish.")
    pool = FakePool({"stress-zzz-a0": []})
    monkeypatch.setattr(judges, "submit", pool.submit)
    return pool


def test_a_clean_run_reports_the_case_count(fake_pool, problem: Path, capsys) -> None:
    fake_pool.answers["stress-zzz-a0"] = [f"{index}\n" for index in range(30)]
    assert stress.run_stress("zzz", count=30, seed=42) == 0
    out = capsys.readouterr().out
    assert "no counterexample" in out
    assert "all 30 case(s)" in out
    assert "seed 42" in out


def test_a_disagreement_reports_the_case_the_input_and_the_seed(
    fake_pool, problem: Path, capsys
) -> None:
    fake_pool.answers["stress-zzz-a0"] = [f"{index}\n" for index in range(20)]
    fake_pool.disagreements = {7}
    assert stress.run_stress("zzz", count=20, seed=99) == 1
    out = capsys.readouterr().out
    assert "counterexample found" in out
    assert "case        7 of 20" in out
    assert "seed        99" in out
    assert "--seed 99 --cases 20" in out
    assert "verdict     WA" in out
    assert "input       1" in out  # the tiny case's own rendered input


def test_a_verdict_that_is_not_wa_is_not_reported_as_a_counterexample(
    fake_pool, problem: Path, monkeypatch, capsys
) -> None:
    """``TLE``/``RTE`` mean the brute force had no comparable answer, not a disagreement."""
    fake_pool.answers["stress-zzz-a0"] = [f"{index}\n" for index in range(10)]
    fake_pool.disagreements = {4}
    monkeypatch.setattr(
        judges,
        "parse_grading",
        lambda raw, status: judges.Grading(
            raw=raw.replace(" WA ", " TLE "),
            verdicts={"TLE": 1, "AC": 9},
            batches=[],
            compile_error=None,
        ),
    )
    assert stress.run_stress("zzz", count=10, seed=1) == 1
    out = capsys.readouterr().out
    assert "counterexample found" not in out
    assert "verdict     TLE" in out
    assert "seed        1" in out


def test_the_finding_is_the_judges_verdict_not_a_local_comparison(
    fake_pool, problem: Path, monkeypatch
) -> None:
    """A run whose transcripts report no failure is not a finding, however it looks."""
    fake_pool.answers["stress-zzz-a0"] = [f"{index}\n" for index in range(10)]
    monkeypatch.setattr(fake_pool, "disagreements", set())
    assert stress.run_stress("zzz", count=10, seed=1) == 0


def test_the_scratch_problems_are_removed_when_the_run_ends(fake_pool, problem: Path) -> None:
    fake_pool.answers["stress-zzz-a0"] = [f"{index}\n" for index in range(5)]
    root = judges.repository_root()
    stress.run_stress("zzz", count=5, seed=1)
    assert not list(root.glob(f"{stress.SCRATCH_PREFIX}zzz-*"))


def test_both_passes_run_per_chunk_and_only_that_many_times(
    fake_pool, problem: Path
) -> None:
    """Thousands of cases are two submissions per container, not thousands."""
    fake_pool.answers["stress-zzz-a0"] = [f"{index}\n" for index in range(500)]
    assert stress.run_stress("zzz", count=500, seed=1) == 0
    assert len(fake_pool.calls) == 2
    assert {problem for _, problem, _ in fake_pool.calls} == {"stress-zzz-a0", "stress-zzz-b0"}


def test_a_model_solution_that_does_not_answer_a_case_is_reported(
    problem: Path, monkeypatch
) -> None:
    """The answers are the reference; a case without one must not be silently skipped."""

    def submit(name, problem_, executor, source, *, time_limit, memory_limit, **_):
        raw = f"Test case  1 AC [0.001s (0.001s wall) | 3000kb] (stress-out:1:{encode('0\n')}) "
        return judges.parse_grading(raw, 0)

    monkeypatch.chdir(problem)
    monkeypatch.setattr(judges, "running_containers", lambda: ["fake-1"])
    monkeypatch.setattr(judges, "update_problems", lambda name: "As you wish.")
    monkeypatch.setattr(judges, "submit", submit)
    with pytest.raises(JudgeError, match="did not answer case 2"):
        stress.run_stress(".", count=3, seed=1)


def test_case_answers_are_written_as_the_expected_outputs(
    fake_pool, problem: Path, monkeypatch
) -> None:
    """Pass B is graded against the model solution's answers, byte for byte."""
    fake_pool.answers["stress-zzz-a0"] = ["10\n", "20\n", "30\n"]
    seen: list[bytes] = []
    real_write = stress.write_expected

    def spy(directory, outputs):
        seen.extend(outputs)
        return real_write(directory, outputs)

    monkeypatch.setattr(stress, "write_expected", spy)
    stress.run_stress("zzz", count=3, seed=1)
    assert seen == [b"10\n", b"20\n", b"30\n"]


def test_the_run_reports_the_seed_it_used(fake_pool, problem: Path, capsys) -> None:
    """A run with no ``--seed`` still has to name one, or its failures are unactionable."""
    fake_pool.answers["stress-zzz-a0"] = [f"{index}\n" for index in range(4)]
    assert stress.run_stress("zzz", count=4) == 0
    assert "seed " in capsys.readouterr().out


# ---------------------------------------------------------------------------
# Through a real judge pool.  Opt-in.
# ---------------------------------------------------------------------------

JUDGE_OPT_IN = os.environ.get("PROBLEMSETTING_JUDGE_TESTS") == "1"

#: A problem built inside the checkout from the shipped template: the pool mounts
#: the checkout at ``/problems``, so a fixture anywhere else would exercise a
#: layout no real pool has.
FIXTURE = "stress-fixture"

judge = pytest.mark.skipif(
    not JUDGE_OPT_IN,
    reason="set PROBLEMSETTING_JUDGE_TESTS=1 (needs the judge image and podman)",
)


@pytest.fixture(scope="module")
def built_problem():
    """The shipped ``standard`` template, built into the checkout, then removed."""
    destination = judges.repository_root() / FIXTURE
    shutil.rmtree(destination, ignore_errors=True)
    shutil.copytree(
        templates.template_dir("standard"),
        destination,
        ignore=shutil.ignore_patterns(*templates.TEMPLATE_IGNORE),
    )
    assert cases_mod.run_build(FIXTURE, seed=None) == 0
    yield destination
    shutil.rmtree(destination, ignore_errors=True)


@judge
def test_the_template_agrees_with_its_own_brute_force(
    built_problem: Path, monkeypatch, capsys
) -> None:
    """One acceptance run: a real pool, real compiles, and a real comparison."""
    monkeypatch.chdir(judges.repository_root())
    assert stress.run_stress(FIXTURE, count=60, seed=2024) == 0
    out = capsys.readouterr().out
    assert "no counterexample" in out
    assert "all 60 case(s)" in out
    assert not list(judges.repository_root().glob(f"{stress.SCRATCH_PREFIX}{FIXTURE}-*"))


@judge
def test_a_perturbed_model_solution_is_caught_with_a_reproducible_seed(
    built_problem: Path, monkeypatch, capsys
) -> None:
    """The other acceptance run, and the one that proves the comparison has teeth."""
    solution = built_problem / "solution.cpp"
    original = solution.read_text()
    solution.write_text(
        original.replace(
            "std::cout << a + b << '\\n';",
            # Wrong whenever a is positive enough to show up quickly, while every
            # declared case still passes: exactly the silent failure stress exists for.
            "std::cout << a + b + (a > 10 ? 1 : 0) << '\\n';",
        )
    )
    try:
        monkeypatch.chdir(judges.repository_root())
        assert stress.run_stress(FIXTURE, count=60, seed=2024) == 1
        out = capsys.readouterr().out
        assert "counterexample found" in out
        assert "seed        2024" in out
        assert "--seed 2024 --cases 60" in out
        # The reported seed reproduces the failure: run it again, get it again.
        assert stress.run_stress(FIXTURE, count=60, seed=2024) == 1
    finally:
        solution.write_text(original)

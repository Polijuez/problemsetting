#!/usr/bin/env python3

import argparse
import importlib.util
import json
import os
import signal
import subprocess
import sys
import tempfile
import threading
import time
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, as_completed, wait
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

try:
    import resource
except ImportError:
    resource = None

# ------------------------------------------------------------------
# Shim mínimo de DMOJ para ejecutar checker.py localmente.
# Permite usar:
#   from dmoj.result import CheckerResult
#   from dmoj.utils.unicode import utf8text
# aunque DMOJ no esté instalado.
# ------------------------------------------------------------------
try:
    from dmoj.result import CheckerResult  # type: ignore
    from dmoj.utils.unicode import utf8text  # type: ignore
except ImportError:
    import types

    @dataclass
    class CheckerResult:
        passed: bool
        points: float = 0.0

    def utf8text(data):
        if isinstance(data, bytes):
            return data.decode("utf-8", errors="replace")
        return str(data)

    dmoj_mod = types.ModuleType("dmoj")
    dmoj_result_mod = types.ModuleType("dmoj.result")
    dmoj_utils_mod = types.ModuleType("dmoj.utils")
    dmoj_unicode_mod = types.ModuleType("dmoj.utils.unicode")

    dmoj_result_mod.CheckerResult = CheckerResult
    dmoj_unicode_mod.utf8text = utf8text

    sys.modules.setdefault("dmoj", dmoj_mod)
    sys.modules.setdefault("dmoj.result", dmoj_result_mod)
    sys.modules.setdefault("dmoj.utils", dmoj_utils_mod)
    sys.modules.setdefault("dmoj.utils.unicode", dmoj_unicode_mod)


IS_WINDOWS = sys.platform == "win32"
HAS_SIGXCPU = hasattr(signal, "SIGXCPU")
_CANCELLED = threading.Event()

# Global cap on the number of concurrently running test-case subprocesses.
# All nested pools (problems -> solutions -> cases) end up launching case
# subprocesses; bounding this one number keeps total CPU contention at the
# intended level so wall-clock measurements don't inflate into false TLEs.
# Stored in a holder so it can be resized from main() after computing jobs.
_CASE_SEM = {"sem": threading.BoundedSemaphore(1)}

C = {
    "A": "\033[92m",
    "PA": "\033[96m",
    "W": "\033[91m",
    "T": "\033[93m",
    "R": "\033[95m",
    "S": "\033[2m",
    "bold": "\033[1m",
    "dim": "\033[2m",
    "reset": "\033[0m",
}


@dataclass
class CaseInfo:
    case_id: str


@dataclass
class SubtaskInfo:
    index: int
    points: float
    cases: List[CaseInfo]


@dataclass
class Problem:
    name: str
    directory: Path
    subtasks: List[SubtaskInfo]
    time_limit: float
    memory_limit_mb: int


@dataclass
class RunResult:
    case_id: str
    verdict: str
    time_ms: float
    checker_points: float
    error: str = ""
    mem_mb: float = 0.0


@dataclass
class SolutionReport:
    solution_name: str
    problem_name: str
    run_results: Dict[str, RunResult] = field(default_factory=dict)
    case_subtasks: Dict[str, List[int]] = field(default_factory=dict)
    subtask_score: Dict[int, float] = field(default_factory=dict)
    subtask_max: Dict[int, float] = field(default_factory=dict)
    subtask_total_cases: Dict[int, int] = field(default_factory=dict)
    total_score: float = 0.0
    total_possible: float = 0.0
    max_time_ms: float = 0.0
    max_memory_mb: float = 0.0


def parse_init_yml(path: Path) -> List[SubtaskInfo]:
    if not path.exists():
        return []
    lines = path.read_text().splitlines()
    subtasks = []
    current = None
    idx = 0
    for line in lines:
        s = line.strip()
        if s.startswith("- points:"):
            pts = float(s.split(":")[1].strip())
            current = SubtaskInfo(index=idx, points=pts, cases=[])
            subtasks.append(current)
            idx += 1
        elif current is not None and "in:" in s and "out:" in s:
            try:
                in_part = s.split("in:")[1].split(",")[0].strip().rstrip("}")
                case_id = Path(in_part).stem
                current.cases.append(CaseInfo(case_id=case_id))
            except (IndexError, ValueError):
                pass
    return subtasks


def load_config(path: Path) -> dict:
    p = path / "config.json"
    if p.exists():
        return json.loads(p.read_text())
    return {}


def find_problems(root: Path, only: Optional[List[str]] = None) -> List[Problem]:
    problems = []
    for d in sorted(root.iterdir()):
        if not d.is_dir():
            continue
        if not (d / "soluciones").exists():
            continue
        if only and d.name not in only:
            continue
        cfg = load_config(d)
        subtasks = parse_init_yml(d / "init.yml")
        problems.append(Problem(
            name=d.name,
            directory=d,
            subtasks=subtasks,
            time_limit=cfg.get("time_limit", 2.0),
            memory_limit_mb=cfg.get("memory_limit_mb", 512),
        ))
    return problems


def ensure_cases(problem: Problem) -> bool:
    cases_dir = problem.directory / "cases"
    if cases_dir.exists() and any(cases_dir.glob("*.in")):
        return True
    print(f"  {C['W']}No cases/ or empty for {problem.name}, skipping (run generate_cases.py first){C['reset']}")
    return False


def ensure_outputs(problem: Problem) -> bool:
    cases_dir = problem.directory / "cases"
    if not cases_dir.exists():
        return False
    ins = list(cases_dir.glob("*.in"))
    if not ins:
        return False
    if all((cases_dir / (p.stem + ".out")).exists() for p in ins):
        return True
    print(f"  {C['W']}Missing .out files for {problem.name}, skipping (run generate_outputs.py first){C['reset']}")
    return False


def compile_solution(problem: Problem, cpp_path: Path) -> Optional[Path]:
    exe_path = problem.directory / f".test_{cpp_path.stem}.exe"

    evaluator = problem.directory / "evaluator.cpp"
    if not evaluator.exists():
        print(f"    {C['W']}Missing evaluator.cpp in {problem.name}{C['reset']}")
        return None

    cmd = [
        "g++", "-std=c++17", "-O2", "-static",
        "-o", str(exe_path),
        str(evaluator), str(cpp_path),
        f"-I{problem.directory}",
    ]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if r.returncode != 0:
            print(f"    {C['W']}Compile error [{cpp_path.name}]:{C['reset']}")
            for line in r.stderr.strip().splitlines()[-5:]:
                print(f"      {C['dim']}{line}{C['reset']}")
            return None
        return exe_path
    except subprocess.TimeoutExpired:
        print(f"    {C['W']}Compile timeout [{cpp_path.name}]{C['reset']}")
        return None


def _set_limits(mem_bytes: int, cpu_secs: int):
    if resource is None:
        return
    try:
        resource.setrlimit(resource.RLIMIT_AS, (mem_bytes, mem_bytes))
    except (ValueError, OSError):
        pass
    try:
        resource.setrlimit(resource.RLIMIT_CPU, (cpu_secs, cpu_secs))
    except (ValueError, OSError):
        pass


def _monitor_peak_rss(pid: int, result: list, stop_event: Optional[threading.Event] = None, poll_interval: float = 0.01):
    peak_kb = 0
    while True:
        if stop_event is not None and stop_event.is_set():
            break
        try:
            with open(f"/proc/{pid}/status") as f:
                for line in f:
                    if line.startswith("VmRSS:"):
                        kb = int(line.split()[1])
                        if kb > peak_kb:
                            peak_kb = kb
        except (FileNotFoundError, ProcessLookupError, ValueError, PermissionError):
            break
        time.sleep(poll_interval)
    result[0] = peak_kb / 1024.0


def run_program(exe: Path, inp: Path, out: Path, time_limit: float, mem_limit_mb: int) -> Tuple[str, float, float, str]:
    mem_bytes = mem_limit_mb * 1024 * 1024
    cpu_secs = max(1, int(time_limit * 2) + 1)
    timeout = time_limit + max(0.25, time_limit * 0.5)

    start = time.monotonic()
    try:
        popen_kwargs = {
            "stdout": subprocess.DEVNULL,
            "stderr": subprocess.PIPE,
        }
        if not IS_WINDOWS:
            popen_kwargs["preexec_fn"] = lambda: _set_limits(mem_bytes, cpu_secs)

        proc = subprocess.Popen(
            [str(exe), str(inp), str(out)],
            **popen_kwargs,
        )

        mem_result = [0.0]
        mem_done = threading.Event()
        monitor = threading.Thread(
            target=_monitor_peak_rss,
            args=(proc.pid, mem_result),
            kwargs={"stop_event": mem_done},
            daemon=True,
        )
        monitor.start()

        try:
            _, stderr = proc.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
            mem_done.set()
            monitor.join(timeout=1.0)
            elapsed = (time.monotonic() - start) * 1000
            return "T", elapsed, mem_result[0], "killed after timeout"

        mem_done.set()
        monitor.join(timeout=1.0)
        elapsed = (time.monotonic() - start) * 1000

        if proc.returncode == 0:
            if elapsed >= time_limit * 1000:
                return "T", elapsed, mem_result[0], f"finished after TL ({elapsed:.0f}ms)"
            return "A", elapsed, mem_result[0], ""
        elif proc.returncode == 255 or (HAS_SIGXCPU and proc.returncode == -signal.SIGXCPU):
            return "T", elapsed, mem_result[0], f"exit {proc.returncode}"
        elif proc.returncode < 0:
            sig_name = signal.Signals(-proc.returncode).name if -proc.returncode in signal.Signals else str(-proc.returncode)
            return "R", elapsed, mem_result[0], f"killed by {sig_name}"
        else:
            stderr_text = stderr.decode(errors="replace").strip() if stderr else ""
            short_err = stderr_text.splitlines()[-1] if stderr_text else f"exit {proc.returncode}"
            return "R", elapsed, mem_result[0], short_err[:120]
    except Exception as e:
        elapsed = (time.monotonic() - start) * 1000
        return "R", elapsed, 0.0, str(e)[:120]


def load_checker(problem: Problem):
    checker_path = problem.directory / "checker.py"
    if not checker_path.exists():
        return None

    module_name = f"checker_{problem.name}"
    spec = importlib.util.spec_from_file_location(module_name, checker_path)
    mod = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(mod)
        return mod.check
    except Exception:
        return None


def check_with_dmoj_checker(check_fn, process_output: bytes, judge_output: bytes,
                            judge_input: bytes, point_value: float) -> Tuple[bool, float]:
    try:
        from dmoj.result import CheckerResult
        from dmoj.utils.unicode import utf8text
        result = check_fn(
            process_output=utf8text(process_output),
            judge_output=utf8text(judge_output),
            judge_input=utf8text(judge_input),
            point_value=point_value,
            submission_source="",
        )
        return result.passed, float(result.points)
    except ImportError:
        return simple_check(process_output, judge_output, point_value)


def simple_check(process_output: bytes, judge_output: bytes, point_value: float) -> Tuple[bool, float]:
    actual = process_output.decode(errors="replace").split()
    expected = judge_output.decode(errors="replace").split()
    if actual == expected:
        return True, point_value
    return False, 0.0


def _run_case(problem: Problem, exe_path: Path, cases_dir: Path, checker_fn, case_id: str) -> RunResult:
    """Run a single test case and grade it, returning a RunResult (thread-safe)."""
    inp = cases_dir / f"{case_id}.in"
    exp = cases_dir / f"{case_id}.out"
    if not inp.exists():
        return RunResult(case_id=case_id, verdict="S", time_ms=0, checker_points=0, error="missing input")

    with tempfile.NamedTemporaryFile(suffix=".out", delete=False) as tmp:
        tmp_path = Path(tmp.name)

    with _CASE_SEM["sem"]:
        verdict, t_ms, mem_mb, err = run_program(exe_path, inp, tmp_path, problem.time_limit, problem.memory_limit_mb)

    cp_points = 0.0
    if verdict == "A":
        proc_bytes = tmp_path.read_bytes() if tmp_path.exists() else b""
        exp_bytes = exp.read_bytes() if exp.exists() else b""
        inp_bytes = inp.read_bytes() if inp.exists() else b""

        if checker_fn is not None:
            passed, cp_points = check_with_dmoj_checker(
                checker_fn, proc_bytes, exp_bytes, inp_bytes,
                point_value=1.0,
            )
        else:
            passed, cp_points = simple_check(proc_bytes, exp_bytes, point_value=1.0)

        if passed and cp_points > 0 and cp_points < 1.0:
            verdict = "P"
        else:
            verdict = "A" if passed else "W"
        if not passed and cp_points == 0:
            cp_points = 0.0

    try:
        tmp_path.unlink()
    except OSError:
        pass

    return RunResult(
        case_id=case_id, verdict=verdict, time_ms=t_ms,
        checker_points=cp_points, error=err, mem_mb=mem_mb,
    )


def is_hard_fail(r: RunResult) -> bool:
    """A verdict that settles a subtask's minimum to 0 regardless of other cases.

    TLE/RTE and a plain full WA (0 points) are hard fails. A partial (PA, >0 points)
    is not, since another case could still score lower.
    """
    return r.verdict in ("T", "R", "W")


def test_solution(problem: Problem, exe_path: Path, solution_name: str, jobs: int, skip_on_fail: bool = False) -> SolutionReport:
    report = SolutionReport(
        solution_name=solution_name,
        problem_name=problem.name,
    )

    cases_dir = problem.directory / "cases"
    checker_fn = load_checker(problem)

    unique_case_ids: Set[str] = set()
    for st in problem.subtasks:
        report.subtask_max[st.index] = st.points
        report.subtask_total_cases[st.index] = len(st.cases)
        for c in st.cases:
            unique_case_ids.add(c.case_id)
            report.case_subtasks.setdefault(c.case_id, []).append(st.index)

    case_ids = sorted(unique_case_ids, key=lambda x: int(x) if x.isdigit() else x)
    results: Dict[str, RunResult] = {}

    if _CANCELLED.is_set():
        for case_id in case_ids:
            results[case_id] = RunResult(case_id=case_id, verdict="S", time_ms=0, checker_points=0, error="cancelled")
    else:
        workers = max(1, min(jobs, len(case_ids)))

        def run_one(cid: str) -> Tuple[str, RunResult]:
            return cid, _run_case(problem, exe_path, cases_dir, checker_fn, cid)

        pending = list(case_ids)
        case_subtasks = report.case_subtasks  # case_id -> [subtask indices]
        failed_subtasks: Set[int] = set()

        def skippable(cid: str) -> bool:
            # Skip a case only if every subtask that needs it has already failed
            # (that is, some earlier case of each subtask hard-failed), so skipping
            # it cannot change any subtask's points.
            sts = case_subtasks.get(cid, [])
            return bool(sts) and all(s in failed_subtasks for s in sts)

        def mark_skipped(cid: str):
            results[cid] = RunResult(case_id=cid, verdict="S", time_ms=0, checker_points=0,
                                     error="skipped: all dependent subtasks already failed")

        with ThreadPoolExecutor(max_workers=workers) as pool:
            running: Dict[Any, str] = {}
            try:
                while pending and len(running) < workers:
                    cid = pending.pop(0)
                    if skip_on_fail and skippable(cid):
                        mark_skipped(cid)
                        continue
                    running[pool.submit(run_one, cid)] = cid

                while running and not _CANCELLED.is_set():
                    done, _ = wait(list(running), return_when=FIRST_COMPLETED)
                    for fut in done:
                        cid = running.pop(fut)
                        try:
                            _, r = fut.result()
                        except Exception as e:
                            r = RunResult(case_id=cid, verdict="R", time_ms=0, checker_points=0, error=str(e)[:120])
                        if is_hard_fail(r):
                            for s in case_subtasks.get(cid, []):
                                failed_subtasks.add(s)
                        results[r.case_id] = r
                    # refill with cases that are not yet safe to skip
                    while pending and len(running) < workers:
                        if _CANCELLED.is_set():
                            break
                        cid = pending.pop(0)
                        if skip_on_fail and skippable(cid):
                            mark_skipped(cid)
                            continue
                        running[pool.submit(run_one, cid)] = cid
            except KeyboardInterrupt:
                _CANCELLED.set()

        # drain any in-flight futures that finished after we stopped scheduling (e.g. on cancel)
        for fut, cid in list(running.items()):
            if fut.done():
                try:
                    _, r = fut.result()
                    results[r.case_id] = r
                except Exception:
                    pass

        # mark any case that never ran
        for case_id in case_ids:
            if case_id not in results:
                if _CANCELLED.is_set():
                    results[case_id] = RunResult(case_id=case_id, verdict="S", time_ms=0, checker_points=0, error="cancelled")
                else:
                    mark_skipped(case_id)

    report.max_time_ms = max((r.time_ms for r in results.values()), default=0.0)
    report.max_memory_mb = max((r.mem_mb for r in results.values()), default=0.0)
    report.run_results = results

    for st in problem.subtasks:
        num_cases = len(st.cases)
        if num_cases == 0:
            report.subtask_score[st.index] = st.points
            report.total_score += st.points
            report.total_possible += st.points
            continue

        min_pts = 1.0
        all_ac = True
        for c in st.cases:
            r = results.get(c.case_id)
            if r is None or r.verdict not in ("A", "P"):
                all_ac = False
                break
            min_pts = min(min_pts, r.checker_points)

        if all_ac:
            report.subtask_score[st.index] = round(st.points * min_pts, 2)
        else:
            report.subtask_score[st.index] = 0.0

        report.total_score += report.subtask_score[st.index]
        report.total_possible += st.points

    return report


def print_report(report: SolutionReport, time_limit: float, show_details: bool = True, show_memory: bool = False, show_pct: bool = False):
    n = len(report.run_results)
    verdicts = ""
    for cid in sorted(report.run_results, key=lambda x: int(x) if x.isdigit() else x):
        r = report.run_results[cid]
        if r.verdict == "S":
            col = C["S"]
            letter = "-"
        elif r.verdict == "P":
            col = C["PA"]
            letter = "P"
        else:
            col = C.get(r.verdict, C["reset"])
            letter = r.verdict
        verdicts += f"{col}{letter}{C['reset']}"

    print(f"\n{C['bold']}  {report.solution_name}{C['reset']}  "
          f"{C['bold']}{report.total_score:.1f}/{report.total_possible:.0f}{C['reset']}  "
          f"({n} cases)  {verdicts}")

    if show_details:
        failed = []
        for cid in sorted(report.run_results, key=lambda x: int(x) if x.isdigit() else x):
            r = report.run_results[cid]
            if r.verdict not in ("A", "S"):
                failed.append(r)

        if failed:
            entries = []
            for r in failed:
                vname = {"W": "WA", "T": "TLE", "R": "RTE", "P": "PA", "S": "SKIP"}.get(r.verdict, r.verdict)
                msg = f"({r.error})" if r.error else ""
                tstr = f"{r.time_ms:.0f}ms" if r.time_ms > 0 else ""
                extra = " ".join(filter(None, [tstr, msg]))
                if r.verdict == "P" and show_pct:
                    extra = f"{int(round(r.checker_points * 100))}% " + extra if extra else f"{int(round(r.checker_points * 100))}%"
                sts = report.case_subtasks.get(r.case_id, [])
                substask_str = f"S{''.join(str(s + 1) for s in sorted(sts))}"
                vcol = C.get(r.verdict, C["reset"])
                if r.verdict == "P":
                    vcol = C["PA"]
                entry = f"{vcol}{r.case_id}({substask_str}):{vname}{C['reset']}"
                if extra:
                    entry += f" {C['dim']}{extra}{C['reset']}"
                entries.append(entry)

            print(f"  {C['bold']}Failed:{C['reset']}")
            line = "    "
            for entry in entries:
                stripped = ""
                in_escape = False
                for ch in entry:
                    if ch == '\033':
                        in_escape = True
                    elif in_escape and ch == 'm':
                        in_escape = False
                    elif not in_escape:
                        stripped += ch
                entry_len = len(stripped)
                if len(line) + entry_len + 3 > 100 and line.strip():
                    print(line)
                    line = "    "
                line += entry + "  "
            if line.strip():
                print(line)

    print(f"  {C['bold']}Subtasks:{C['reset']}", end="")
    for st in sorted(report.subtask_score):
        sc = report.subtask_score[st]
        mx = report.subtask_max[st]
        if sc >= mx - 0.01:
            color = C["A"]
        elif sc > 0:
            color = C["PA"]
        else:
            color = C["W"]
        pct = f" ({int(round(sc / mx * 100))}%)" if show_pct else ""
        print(f"  {color}S{st+1}: {sc:.1f}/{mx:.0f}pt{pct}{C['reset']}", end="")
    print()

    parts = [f"{report.max_time_ms:.0f}ms"]
    if show_memory:
        parts.append(f"{report.max_memory_mb:.1f}MB")
    tl_ms = time_limit * 1000
    time_color = C["A"] if report.max_time_ms < tl_ms * 0.8 else C["T"] if report.max_time_ms < tl_ms else C["W"]
    if show_memory:
        print(f"  {C['bold']}Max time:{C['reset']} {time_color}{parts[0]}{C['reset']}  "
              f"{C['bold']}Max memory:{C['reset']} {parts[1]}")
    else:
        print(f"  {C['bold']}Max time:{C['reset']} {time_color}{parts[0]}{C['reset']}")


class LiveStatus:
    def __init__(self):
        self._height = 0

    def _clear(self):
        if self._height > 0:
            sys.stdout.write(f"\033[{self._height}A")
            for _ in range(self._height):
                sys.stdout.write("\033[2K\n")
            sys.stdout.write(f"\033[{self._height}A")
            self._height = 0

    def update(self, running_names, total):
        self._clear()
        if running_names:
            names = ", ".join(sorted(running_names))
            n = len(running_names)
            line = f"  {C['dim']}Testing: {names} ({n}/{total}){C['reset']}"
        else:
            line = ""
        sys.stdout.write(f"\033[2K{line}\n")
        self._height = 1
        sys.stdout.flush()

    def finish(self):
        self._clear()


def main():
    parser = argparse.ArgumentParser(description="Compile and test all solutions against generated cases")
    parser.add_argument("-p", "--problems", nargs="*", help="Only test these problems")
    parser.add_argument("-s", "--solutions", nargs="*", help="Only test these solution names")
    parser.add_argument("-j", "--jobs", type=int, default=None,
                        help="Max concurrent problems/solutions/testcases (default: 80%% of available CPUs)")
    parser.add_argument("-d", "--no-details", action="store_true", help="Don't show per-case failure details")
    parser.add_argument("-m", "--show-memory", action="store_true", help="Show peak memory usage per solution")
    parser.add_argument("--pct", action="store_true", help="Show partially awarded points as a percentage")
    parser.add_argument("--skip-on-fail", action="store_true",
                        help="Stop launching remaining test cases of a solution after a hard fail "
                             "(TLE/RTE/WA). Never the default; partials (PA) do not trigger it.")
    args = parser.parse_args()

    if args.jobs is None:
        args.jobs = max(1, round((os.cpu_count() or 1) * 0.8))

    # Cap total concurrent test-case subprocesses at the job budget, so the
    # nested problem/solution pools don't multiply each other's concurrency.
    _CASE_SEM["sem"] = threading.BoundedSemaphore(max(1, args.jobs))

    root = Path(__file__).parent
    cwd = Path.cwd()

    if args.problems is None and (cwd / "soluciones").exists() and cwd != root:
        args.problems = [cwd.name]

    problems = find_problems(root, only=args.problems)
    if not problems:
        print(f"{C['W']}No problems with soluciones/ found{C['reset']}")
        return 1

    print(f"{C['bold']}Found {len(problems)} problem(s): {', '.join(p.name for p in problems)}{C['reset']}")

    all_reports: List[SolutionReport] = []

    def process_problem(problem: Problem) -> List[SolutionReport]:
        reports = []
        print(f"\n{C['bold']}[{problem.name}] Generating cases...{C['reset']}", flush=True)
        if not ensure_cases(problem):
            return reports
        print(f"[{problem.name}] Generating outputs...", flush=True)
        if not ensure_outputs(problem):
            return reports

        sols_dir = problem.directory / "soluciones"
        solutions = sorted(sols_dir.glob("*.cpp"))
        if args.solutions:
            solutions = [s for s in solutions if s.stem in args.solutions]
        if not solutions:
            print(f"[{problem.name}] {C['dim']}no .cpp files in soluciones/{C['reset']}", flush=True)
            return reports

        print(f"[{problem.name}] Compiling {len(solutions)} solution(s)...", flush=True)
        compiled: Dict[str, Path] = {}
        for sol in solutions:
            if _CANCELLED.is_set():
                break
            exe = compile_solution(problem, sol)
            if exe:
                compiled[sol.stem] = exe

        if not compiled:
            print(f"[{problem.name}] {C['W']}no solutions compiled{C['reset']}", flush=True)
            return reports

        print(f"[{problem.name}] Testing {len(compiled)} solution(s)...", flush=True)

        live = LiveStatus() if sys.stdout.isatty() else None
        running = set(compiled.keys())
        total = len(compiled)

        if live:
            live.update(running, total)

        pool = ThreadPoolExecutor(max_workers=min(args.jobs, len(compiled)))
        futures = {
            pool.submit(test_solution, problem, exe, name, args.jobs, args.skip_on_fail): name
            for name, exe in compiled.items()
        }
        try:
            for fut in as_completed(futures):
                if _CANCELLED.is_set():
                    for f in futures:
                        f.cancel()
                    break
                name = futures[fut]
                try:
                    report = fut.result()
                    reports.append(report)
                except Exception as e:
                    print(f"[{problem.name}] {C['W']}{name}: exception {e}{C['reset']}", flush=True)

                running.discard(name)
                if live:
                    live._clear()
                last_report = reports[-1] if reports else None
                if last_report:
                    print_report(last_report, problem.time_limit, show_details=not args.no_details, show_memory=args.show_memory, show_pct=args.pct)
                if live:
                    live.update(running, total)
        finally:
            pool.shutdown(wait=False)

        if live:
            live.finish()

        for exe in compiled.values():
            try:
                exe.unlink()
            except OSError:
                pass

        return reports

    pool = ThreadPoolExecutor(max_workers=min(args.jobs, len(problems)))
    futures = {pool.submit(process_problem, p): p for p in problems}
    try:
        for fut in as_completed(futures):
            if _CANCELLED.is_set():
                for f in futures:
                    f.cancel()
                break
            try:
                all_reports.extend(fut.result())
            except Exception as e:
                p = futures[fut]
                print(f"{C['W']}[{p.name}] crashed: {e}{C['reset']}")
    except KeyboardInterrupt:
        _CANCELLED.set()
        print(f"\n{C['W']}Cancelled.{C['reset']}")
    finally:
        pool.shutdown(wait=False)

    if all_reports:
        print(f"\n{'='*60}")
        print(f"{C['bold']}SUMMARY{C['reset']}")
        print(f"{'='*60}")
        for r in sorted(all_reports, key=lambda x: (-x.total_score, x.problem_name, x.solution_name)):
            pct = (r.total_score / r.total_possible * 100) if r.total_possible else 0
            color = C["A"] if pct >= 99.9 else C["T"] if pct > 0 else C["W"]
            print(f"  {color}{r.total_score:6.1f}/{r.total_possible:.0f} ({pct:5.1f}%){C['reset']}  "
                  f"{r.problem_name}/{r.solution_name}")

    print(f"\n{C['bold']}Done.{C['reset']}")
    return 130 if _CANCELLED.is_set() else 0


if __name__ == "__main__":
    sys.exit(main())

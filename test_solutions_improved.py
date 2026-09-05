#Chat gpt le agrega que termine la subtask al primer TLE (creo)
#!/usr/bin/env python3

import argparse
import importlib.util
import json
try:
    import resource
except ImportError:
    resource = None
import signal
import subprocess
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

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


C = {
    "A": "\033[92m",
    "W": "\033[91m",
    "T": "\033[93m",
    "R": "\033[95m",
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
    winner_correct: bool = False
    m_correct: bool = False


@dataclass
class SolutionReport:
    solution_name: str
    problem_name: str
    run_results: Dict[str, RunResult] = field(default_factory=dict)
    subtask_score: Dict[int, float] = field(default_factory=dict)
    subtask_max: Dict[int, float] = field(default_factory=dict)
    subtask_total_cases: Dict[int, int] = field(default_factory=dict)
    total_score: float = 0.0
    total_possible: float = 0.0


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


def run_program(exe: Path, inp: Path, out: Path, time_limit: float, mem_limit_mb: int) -> Tuple[str, float, str]:
    mem_bytes = mem_limit_mb * 1024 * 1024
    cpu_secs = int(time_limit) + 1

    start = time.monotonic()
    try:
        popen_kwargs = {
            "stdout": subprocess.DEVNULL,
            "stderr": subprocess.PIPE,
        }
        if resource is not None:
            popen_kwargs["preexec_fn"] = lambda: _set_limits(mem_bytes, cpu_secs)

        proc = subprocess.Popen(
            [str(exe), str(inp), str(out)],
            **popen_kwargs,
        )
        try:
            _, stderr = proc.communicate(timeout=time_limit + 1.0)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
            elapsed = (time.monotonic() - start) * 1000
            return "T", elapsed, "killed after timeout"

        elapsed = (time.monotonic() - start) * 1000

        if proc.returncode == 0:
            return "A", elapsed, ""
        elif proc.returncode == -signal.SIGXCPU or proc.returncode == 255:
            return "T", elapsed, f"exit {proc.returncode}"
        elif proc.returncode < 0:
            sig_name = signal.Signals(-proc.returncode).name if -proc.returncode in signal.Signals else str(-proc.returncode)
            return "R", elapsed, f"killed by {sig_name}"
        else:
            stderr_text = stderr.decode(errors="replace").strip() if stderr else ""
            short_err = stderr_text.splitlines()[-1] if stderr_text else f"exit {proc.returncode}"
            return "R", elapsed, short_err[:120]
    except Exception as e:
        elapsed = (time.monotonic() - start) * 1000
        return "R", elapsed, str(e)[:120]


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
        result = check_fn(
            process_output=utf8text(process_output),
            judge_output=utf8text(judge_output),
            judge_input=utf8text(judge_input),
            point_value=point_value,
            submission_source="",
        )
        return bool(result.passed), float(result.points)
    except Exception as e:
        # Si el checker explota, no fingimos un simple_check:
        # mostramos el error para poder depurarlo.
        print(f"    {C['W']}Checker error: {e}{C['reset']}")
        return False, 0.0

def simple_check(process_output: bytes, judge_output: bytes, point_value: float) -> Tuple[bool, float]:
    actual = process_output.decode(errors="replace").split()
    expected = judge_output.decode(errors="replace").split()
    if actual == expected:
        return True, point_value
    return False, 0.0


def test_solution(problem: Problem, exe_path: Path, solution_name: str) -> SolutionReport:
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

    cache: Dict[str, RunResult] = {}

    for case_id in sorted(unique_case_ids, key=lambda x: int(x) if x.isdigit() else x):
        inp = cases_dir / f"{case_id}.in"
        exp = cases_dir / f"{case_id}.out"
        if not inp.exists():
            cache[case_id] = RunResult(case_id=case_id, verdict="R", time_ms=0, checker_points=0, error="missing input")
            continue

        with tempfile.NamedTemporaryFile(suffix=".out", delete=False) as tmp:
            tmp_path = Path(tmp.name)

        verdict, t_ms, err = run_program(exe_path, inp, tmp_path, problem.time_limit, problem.memory_limit_mb)

        cp_points = 0.0
        winner_correct = False
        m_correct = False

        if verdict == "A":
            proc_bytes = tmp_path.read_bytes() if tmp_path.exists() else b""
            exp_bytes = exp.read_bytes() if exp.exists() else b""
            inp_bytes = inp.read_bytes() if inp.exists() else b""

            actual_tokens = proc_bytes.decode(errors="replace").split()
            expected_tokens = exp_bytes.decode(errors="replace").split()

            winner_correct = (
                len(actual_tokens) >= 1 and
                len(expected_tokens) >= 1 and
                actual_tokens[0] == expected_tokens[0]
            )

            # M cuenta como correcto solamente si la salida tiene exactamente
            # la cantidad esperada de valores y todos los M coinciden.
            m_correct = (
                len(actual_tokens) == len(expected_tokens) and
                len(expected_tokens) >= 1 and
                actual_tokens[1:] == expected_tokens[1:]
            )

            if checker_fn is not None:
                passed, cp_points = check_with_dmoj_checker(
                    checker_fn, proc_bytes, exp_bytes, inp_bytes,
                    point_value=1.0,
                )
            else:
                passed, cp_points = simple_check(proc_bytes, exp_bytes, point_value=1.0)

            verdict = "A" if passed else "W"
            if not passed and cp_points == 0:
                cp_points = 0.0

        try:
            tmp_path.unlink()
        except OSError:
            pass

        cache[case_id] = RunResult(
            case_id=case_id,
            verdict=verdict,
            time_ms=t_ms,
            checker_points=cp_points,
            error=err,
            winner_correct=winner_correct,
            m_correct=m_correct,
        )

        # Stop testing this solution after its first TLE.
        if verdict == "T":
            break

    report.run_results = cache

    for st in problem.subtasks:
        num_cases = len(st.cases)

        if num_cases == 0:
            report.subtask_score[st.index] = st.points
            report.total_score += st.points
            report.total_possible += st.points
            continue

        winner_all_correct = True
        m_all_correct = True

        for c in st.cases:
            r = cache.get(c.case_id)

            # Si el caso no se ejecutó (por ejemplo por TLE previo),
            # ninguna de las dos mitades puede considerarse correcta.
            if r is None:
                winner_all_correct = False
                m_all_correct = False
                continue

            if not r.winner_correct:
                winner_all_correct = False

            if not r.m_correct:
                m_all_correct = False

        score = 0.0

        # 50% de la subtarea si acertó TODOS los ganadores.
        if winner_all_correct:
            score += st.points * 0.5

        # 50% de la subtarea si acertó TODOS los M.
        if m_all_correct:
            score += st.points * 0.5

        report.subtask_score[st.index] = round(score, 2)
        report.total_score += report.subtask_score[st.index]
        report.total_possible += st.points

    return report


def print_report(report: SolutionReport, show_details: bool = True):
    n = len(report.run_results)
    verdicts = ""
    for cid in sorted(report.run_results, key=lambda x: int(x) if x.isdigit() else x):
        r = report.run_results[cid]
        verdicts += f"{C.get(r.verdict, C['reset'])}{r.verdict}{C['reset']}"

    print(f"\n{C['bold']}  {report.solution_name}{C['reset']}  "
          f"{C['bold']}{report.total_score:.1f}/{report.total_possible:.0f}{C['reset']}  "
          f"({n} cases)  {verdicts}")

    if not show_details:
        return

    failed = []
    for cid in sorted(report.run_results, key=lambda x: int(x) if x.isdigit() else x):
        r = report.run_results[cid]
        if r.verdict != "A":
            failed.append(r)

    if failed:
        entries = []
        for r in failed:
            vname = {"W": "WA", "T": "TLE", "R": "RTE"}.get(r.verdict, r.verdict)
            msg = f"({r.error})" if r.error else ""
            tstr = f"{r.time_ms:.0f}ms" if r.time_ms > 0 else ""
            extra = " ".join(filter(None, [tstr, msg]))
            entry = f"{C.get(r.verdict, '')}{r.case_id}:{vname}{C['reset']}"
            if extra:
                entry += f" {C['dim']}{extra}{C['reset']}"
            entries.append(entry)

        print(f"  {C['bold']}Failed:{C['reset']}")
        line = "    "
        for entry in entries:
            bare = f"{r.case_id}:{vname}" if False else ""
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
        color = C["A"] if sc >= mx - 0.01 else C["W"]
        print(f"  {color}S{st+1}: {sc:.1f}/{mx:.0f}pt{C['reset']}", end="")
    print()


def main():
    parser = argparse.ArgumentParser(description="Compile and test all solutions against generated cases")
    parser.add_argument("-p", "--problems", nargs="*", help="Only test these problems")
    parser.add_argument("-s", "--solutions", nargs="*", help="Only test these solution names")
    parser.add_argument("-j", "--jobs", type=int, default=4, help="Parallel jobs (default: 4)")
    parser.add_argument("-d", "--no-details", action="store_true", help="Don't show per-case failure details")
    args = parser.parse_args()

    root = Path(__file__).parent

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
            exe = compile_solution(problem, sol)
            if exe:
                compiled[sol.stem] = exe

        if not compiled:
            print(f"[{problem.name}] {C['W']}no solutions compiled{C['reset']}", flush=True)
            return reports

        print(f"[{problem.name}] Testing {len(compiled)} solution(s)...", flush=True)

        with ThreadPoolExecutor(max_workers=min(args.jobs, len(compiled))) as pool:
            futures = {
                pool.submit(test_solution, problem, exe, name): name
                for name, exe in compiled.items()
            }
            for fut in as_completed(futures):
                name = futures[fut]
                try:
                    report = fut.result()
                    reports.append(report)
                except Exception as e:
                    print(f"[{problem.name}] {C['W']}{name}: exception {e}{C['reset']}", flush=True)

        for report in sorted(reports, key=lambda r: -r.total_score):
            print_report(report, show_details=not args.no_details)

        for exe in compiled.values():
            try:
                exe.unlink()
            except OSError:
                pass

        return reports

    with ThreadPoolExecutor(max_workers=min(args.jobs, len(problems))) as pool:
        futures = {pool.submit(process_problem, p): p for p in problems}
        for fut in as_completed(futures):
            try:
                all_reports.extend(fut.result())
            except Exception as e:
                p = futures[fut]
                print(f"{C['W']}[{p.name}] crashed: {e}{C['reset']}")

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
    return 0


if __name__ == "__main__":
    sys.exit(main())

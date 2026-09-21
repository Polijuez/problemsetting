#!/usr/bin/env python3
"""Grade candidate submissions against a built problem using the real DMOJ judge.

Wraps ``dmoj-cli`` running inside the ``localhost/dmoj/judge-tier3:latest``
container (via the judge container's ``cli`` entry point).  Unlike
``test_solutions.py`` -- a local, hand-rolled ``rlimit`` sandbox with no DMOJ
executors -- this uses the exact same executors and cptbox sandbox that
production judging uses, but without the site/bridge/supervisor stack.

Usage:
    uv run python judge_solutions.py <problem_name> [--solution <path>]
        [--lang HASK|CPP17|PY3] [--time-limit 2.0] [--memory-limit 262144]

The problem must already be built: ``<problem_name>/init.yml`` must exist and
its ``archive:`` file (or a ``cases/`` directory with ``.in``/``.out`` files)
must be present.  If only ``cases/`` exists, the archive is zipped from it,
mirroring what ``scripts/build.sh`` does.
"""

import argparse
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent

# Container image plus the capability flags required by the cptbox sandbox
# (mirrors scripts/run.sh "spawn").
JUDGE_IMAGE = "localhost/dmoj/judge-tier3:latest"
SANDBOX_CAPS = ["SYS_PTRACE", "SETUID", "SETGID"]

# DMOJ executor id by source extension.
LANG_BY_EXT = {
    ".hs": "HASK",
    ".cpp": "CPP17",
    ".py": "PY3",
}


def check_image() -> None:
    """Exit with build instructions if the judge image is not available locally."""
    result = subprocess.run(
        ["podman", "image", "exists", JUDGE_IMAGE],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    if result.returncode != 0:
        print(
            f"Judge image not found ({JUDGE_IMAGE}). Build it from the Polijuez "
            "repo: just build judgeserver",
            file=sys.stderr,
        )
        raise SystemExit(1)


def resolve_problem_dir(problem_name: str) -> Path:
    """Resolve a problem directory by its name, requiring an init.yml."""
    problem_dir = REPO_ROOT / problem_name
    if not (problem_dir / "init.yml").is_file():
        print(
            f"error: problem '{problem_name}' not found or not built\n"
            f"  expected {problem_dir / 'init.yml'}\n"
            "  Build it first (generate_cases.py + generate_outputs.py, or "
            "just build problems <name>).",
            file=sys.stderr,
        )
        raise SystemExit(1)
    return problem_dir


def read_archive_name(problem_dir: Path) -> str:
    """Return the archive filename declared in init.yml, if any."""
    import yaml  # repo dependency (pyproject.toml)

    with (problem_dir / "init.yml").open() as fh:
        config = yaml.safe_load(fh) or {}
    return config.get("archive", "")


def ensure_archive(problem_dir: Path) -> None:
    """Make sure the problem's DMOJ archive exists.

    DMOJ resolves cases from the ``archive:`` zip declared in init.yml.  The
    problemsetting worktree keeps loose ``cases/``.in/``.out`` files instead, so
    when the archive is missing but ``cases/`` has at least one input file we
    zip it -- the same step scripts/build.sh performs -- before grading.
    """
    archive_name = read_archive_name(problem_dir)
    if not archive_name:
        return
    archive_path = problem_dir / archive_name
    if archive_path.is_file():
        return
    cases_dir = problem_dir / "cases"
    if not cases_dir.is_dir() or not any(cases_dir.glob("*.in")):
        print(
            f"error: archive '{archive_name}' is missing and no cases/ to build "
            f"it from in {problem_dir}",
            file=sys.stderr,
        )
        raise SystemExit(1)
    print(f"==> archiving cases/ -> {archive_name}")
    with zipfile.ZipFile(archive_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for case in sorted(cases_dir.iterdir()):
            if case.suffix in (".in", ".out"):
                zf.write(case, case.name)


def pick_solution(problem_dir: Path, solution_arg: Path | None) -> Path:
    """Choose the source to grade, defaulting to the problem's model solution."""
    if solution_arg is not None:
        path = Path(solution_arg)
        return path if path.is_absolute() else (Path.cwd() / path).resolve()
    for ext in LANG_BY_EXT:
        candidate = problem_dir / f"solution{ext}"
        if candidate.is_file():
            return candidate
    print(
        f"error: no solution found (pass --solution or provide "
        f"solution.hs/.cpp/.py in {problem_dir})",
        file=sys.stderr,
    )
    raise SystemExit(1)


def detect_lang(solution: Path, lang_arg: str | None) -> str:
    """Determine the DMOJ executor id.

    An explicit ``--lang`` (already validated by argparse ``choices``) wins;
    otherwise infer it from the solution file's extension.
    """
    if lang_arg:
        return lang_arg.upper()
    ext = solution.suffix.lower()
    lang = LANG_BY_EXT.get(ext)
    if lang is None:
        print(
            f"error: cannot infer DMOJ language from '{solution.name}' "
            f"(pass --lang HASK|CPP17|PY3)",
            file=sys.stderr,
        )
        raise SystemExit(1)
    return lang


def container_source_path(solution: Path) -> str:
    """Map a host source file to its path inside the /problems mount."""
    try:
        rel = solution.resolve().relative_to(REPO_ROOT)
    except ValueError:
        print(
            f"error: solution must live under the problemsetting repo "
            f"({REPO_ROOT}), got {solution}",
            file=sys.stderr,
        )
        raise SystemExit(1)
    return f"/problems/{rel.as_posix()}"


def parse_verdicts(raw: str) -> dict:
    """Count per-case verdicts from DMOJ-cli's per-case report lines."""
    counts = {}
    for line in raw.splitlines():
        stripped = line.strip()
        # "  Test case  1 WA [0.015s ...]"  |  "  Test case  2 --"
        if not stripped.startswith("Test case"):
            continue
        parts = stripped.split()
        # parts: ["Test","case","N",VERDICT,...] -> take parts[3]
        if len(parts) < 4:
            continue
        verdict = parts[3]
        counts[verdict] = counts.get(verdict, 0) + 1
    return counts


def main() -> None:
    parser = argparse.ArgumentParser(description="Grade submissions with the real DMOJ judge-tier3 container (cli mode).")
    parser.add_argument("problem", help="name of the problem directory to grade against")
    parser.add_argument("--solution", "-s", help="submission source to grade (default: the problem's solution.<ext>)")
    parser.add_argument("--lang", "-l", help="DMOJ executor id (default: inferred from extension)", choices=sorted(LANG_BY_EXT.values()))
    parser.add_argument("--time-limit", "-tl", type=float, default=2.0, help="per-case time limit in seconds (default: 2.0)")
    parser.add_argument("--memory-limit", "-ml", type=int, default=262144, help="per-case memory limit in KB (default: 262144)")
    args = parser.parse_args()

    check_image()
    problem_dir = resolve_problem_dir(args.problem)
    ensure_archive(problem_dir)

    solution = pick_solution(problem_dir, args.solution)
    if not solution.is_file():
        print(f"error: solution file not found: {solution}", file=sys.stderr)
        raise SystemExit(1)
    lang = detect_lang(solution, args.lang)
    src_in_container = container_source_path(solution)

    # Temp judge.yml.  problem_storage_globs must use the single-segment Docker
    # form (/problems/**/) -- the trailing "/**/*" form fails DMOJ's
    # get_problem_root() fnmatch filter and breaks grading.
    with tempfile.NamedTemporaryFile("w", suffix=".yml", delete=False) as cfg:
        cfg.write("problem_storage_globs:\n  - /problems/**/\n")
        cfg_path = Path(cfg.name)

    try:
        cmd = [
            "podman", "run", "--rm",
        ]
        for cap in SANDBOX_CAPS:
            cmd += ["--cap-add", cap]
        cmd += [
            "-v", f"{REPO_ROOT}:/problems:z",
            "-v", f"{cfg_path}:/judge.yml:z",
            JUDGE_IMAGE,
            "cli", "-c", "/judge.yml", "--",
            "submit", args.problem, lang, src_in_container,
            "-tl", str(args.time_limit),
            "-ml", str(args.memory_limit),
        ]

        print(f"==> grading {args.problem} {lang} via {JUDGE_IMAGE}")
        # Stream DMOJ output live while collecting it for verdict parsing.
        # Keep the child + its stdout pipe reaped/closed even if the read loop
        # is interrupted (e.g. Ctrl-C) so podman isn't orphaned.
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        chunks: list[str] = []
        try:
            assert proc.stdout is not None
            for line in proc.stdout:
                sys.stdout.write(line)
                sys.stdout.flush()
                chunks.append(line)
        finally:
            if proc.stdout is not None:
                proc.stdout.close()
            if proc.poll() is None:
                proc.kill()
            proc.wait()
        combined = "".join(chunks)

        verdicts = parse_verdicts(combined)

        if "Failed compiling submission" in combined or "CompileError" in combined:
            sys.exit(1)
        if "InvalidCommandException" in combined or "unknown language" in combined.lower() or "unknown problem" in combined.lower():
            sys.exit(1)

        if verdicts:
            graded = {v: n for v, n in verdicts.items() if v != "--"}
            # Any reported case that isn't Accepted fails the run; "--" marks a
            # case skipped because an earlier case in its batch already failed.
            failures = sum(n for v, n in graded.items() if v != "AC")
            summary = ", ".join(f"{v}:{n}" for v, n in sorted(verdicts.items()))
            print(f"\n==> per-case verdicts: {summary}")
            ok = failures == 0 and graded and "AC" in graded
            if ok:
                print("==> accepted")
            else:
                print("==> NOT accepted", file=sys.stderr)
            sys.exit(0 if ok else 1)

        # Fallback: could not parse any verdict line.
        if "Accepted" in combined:
            sys.exit(0)
        sys.exit(proc.returncode if proc.returncode != 0 else 1)
    finally:
        cfg_path.unlink(missing_ok=True)


if __name__ == "__main__":
    main()

"""Judge substrate: the judge image, and a pool of long-lived judge containers.

Two pieces, both required before a submission can be graded locally:

**The image.**  ``localhost/dmoj/judge-tier3:latest``, built from the
``vendor/judge-server`` submodule (decision Q7) exactly the way production does
it (``juez/scripts/utils.sh:asegurar_imagen_judgeserver_disponible``): the
vendored ``patches/hask-mempolicy.patch`` is applied to the submodule first, then
``podman build --build-arg TAG=master``.  The patch is not cosmetic -- without it
the HASK executor's self-test faults on syscall 239 and GHC is silently never
registered, so every Haskell submission fails with "no valid runtime".

**The pool.**  N named containers (decision Q20), started on demand, discovered
by name so a pool survives across invocations (``judges start`` then a later
``judges status``), and stopped explicitly or on an idle timeout.  A container
runs :mod:`problemsetting.judge_runtime.launcher`, which builds a ``LocalJudge``,
calls ``listen()`` once -- discovery and the executor self-test -- and then stays
on a control FIFO; :mod:`problemsetting.judge_runtime.client` sends it one
command at a time and streams the output back.  Grading is therefore
``submit <problem> <executor> <source> -tl <seconds> -ml <KiB>``:

* the **judge** reports verdicts as ``Test case  1 WA [0.004s ...]``, batched
  problems sectioning them under ``Batch #1``; :func:`parse_verdicts` and
  :func:`parse_batches` read both (the approach ``judge_solutions.py`` already
  used).
* the **toolkit** re-discovers problems after regenerating cases by POSTing to
  the judge's ``/update/problems`` control endpoint (decision Q28) rather than
  restarting containers.
"""

from __future__ import annotations

import dataclasses
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

from .commands import Command, register
from .errors import JudgeError

#: The image production builds and runs (``juez/scripts/run.sh``).
IMAGE = "localhost/dmoj/judge-tier3:latest"

#: The base image's Dockerfile, and the tag its ``ARG`` picks up.  ``TAG=master``
#: is what production uses; it is a moving target by construction.
BASE_IMAGE = "dmoj/runtimes-tier3"
BUILD_ARG_TAG = "master"

#: The three capabilities the cptbox sandbox needs -- a mirror of
#: ``juez/scripts/run.sh``'s ``spawn``.  SYS_PTRACE is for the sandbox's ptrace
#: supervision, SETUID/SETGID for dropping to the executor's user.
SANDBOX_CAPS = ("SYS_PTRACE", "SETUID", "SETGID")

#: Mount point for the worktree inside the containers.
PROBLEMS_MOUNT = "/problems"

#: Container name prefix.  Containers are discovered by this prefix plus a
#: numeric suffix, which is what makes the pool survive between invocations.
NAME_PREFIX = "polijuez-judge-"

#: Cap on the ``nproc``-derived default pool size (decision Q28).  Each judge
#: holds a self-tested executor set and grades one submission at a time, so the
#: useful parallelism is bounded well below the core count on a big machine;
#: 8 keeps a 16-core box from starting 16 judges that all idle.
MAX_DEFAULT_COUNT = 8

#: Default idle timeout, in seconds: a pool nobody has used for half an hour
#: stops itself rather than holding ~500 MiB per container forever.
DEFAULT_IDLE_TIMEOUT = 1800

#: Where the in-container launcher keeps its FIFO and spool.
POOL_DIR = "/run/dmoj-pool"

#: Boot (discovery + every executor's self-test) measured at ~50 s on this
#: machine's first run and faster when warm; this bounds it generously.
READY_TIMEOUT = 900.0

#: A single ``submit`` needs to compile and run every case, so the client's
#: per-command timeout is separate from, and much longer than, the boot timeout.
COMMAND_TIMEOUT = 600.0


# ---------------------------------------------------------------------------
# Process helpers
# ---------------------------------------------------------------------------


def _run(args: list[str], **kwargs) -> subprocess.CompletedProcess:
    """Run a command, reporting "not installed" as an actionable error."""
    if shutil.which(args[0]) is None:
        raise JudgeError(
            f"{args[0]!r} is not installed or not on PATH; the judge pool needs "
            f"podman (rootless is fine)"
        )
    return subprocess.run(args, **kwargs)


def _capture(args: list[str]) -> subprocess.CompletedProcess:
    return _run(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)


def _podman(args: list[str], **kwargs) -> subprocess.CompletedProcess:
    return _run(["podman", *args], **kwargs)


def image_exists(image: str = IMAGE) -> bool:
    """Whether ``image`` is present in the local podman store."""
    result = _capture(["podman", "image", "exists", image])
    return result.returncode == 0


def repository_root() -> Path:
    """The toolkit's own checkout -- the directory holding ``vendor/``.

    Prefers this toolkit's worktree, because ``git submodule`` state only exists
    there: an installed copy of the package (decision Q2 makes it a pinned ``uv``
    git dependency of the problem repos) has no ``vendor/`` and no submodule
    gitlink, so the checkout has to be named explicitly.  ``PROBLEMSETTING_ROOT``
    is that escape hatch, and it is also what a test uses to point at a fixture
    tree.
    """
    override = os.environ.get("PROBLEMSETTING_ROOT")
    if override:
        return Path(override).resolve()
    for parent in Path(__file__).resolve().parents:
        if (parent / "pyproject.toml").is_file() and (parent / "src").is_dir():
            return parent
    raise JudgeError(
        "cannot locate the problemsetting checkout (no pyproject.toml above the "
        "installed package).  The judge image is built from its vendor/judge-server "
        "submodule, which only exists in a checkout: set PROBLEMSETTING_ROOT to it"
    )


# ---------------------------------------------------------------------------
# Image bootstrap
# ---------------------------------------------------------------------------


def submodule_dir(root: Path | None = None) -> Path:
    """Path of the vendored judge-server checkout."""
    return (root or repository_root()) / "vendor" / "judge-server"


def patches_dir(root: Path | None = None) -> Path:
    """Path of the vendored patches applied before the build."""
    return (root or repository_root()) / "patches"


def build_instructions(root: Path | None = None) -> str:
    """The exact command to build the image, and where it comes from.

    Named in every "image missing" error, because the image is 15 GB and the
    author should be able to build it without reading the source.
    """
    root = root or repository_root()
    return (
        f"the judge image {IMAGE} is not available locally.\n"
        f"  Build it with:  problemsetting judges build\n"
        f"  (equivalently:  podman build --build-arg TAG={BUILD_ARG_TAG} "
        f"-t {IMAGE} {submodule_dir(root)}/.docker/tier3)\n"
        f"  It is built from the judge-server submodule at {submodule_dir(root)}, "
        f"which comes from https://github.com/DMOJ/judge-server.git"
    )


def require_image(root: Path | None = None) -> Path:
    """Return the repo root, or raise naming how to build the image."""
    root = root or repository_root()
    if not image_exists():
        raise JudgeError(build_instructions(root))
    return root


def apply_patches(root: Path | None = None) -> list[str]:
    """Apply every vendored patch to the submodule; return the ones applied.

    Applying is idempotent: a patch that is already in is detected with
    ``git apply --check`` failing on a *reverse* test, and skipped rather than
    failing the build.  The submodule working tree is intentionally left
    modified -- that is the state the Dockerfile builds from, and re-applying is
    a no-op.
    """
    root = root or repository_root()
    submodule = submodule_dir(root)
    if not (submodule / ".docker").is_dir():
        raise JudgeError(
            f"the judge-server submodule is not checked out at {submodule}; fetch it with "
            f"'git submodule update --init --depth 1 vendor/judge-server'"
        )
    applied = []
    for patch in sorted(patches_dir(root).glob("*.patch")):
        check = _capture(
            ["git", "-C", str(submodule), "apply", "--check", "--reverse", str(patch)]
        )
        if check.returncode == 0:
            continue  # already applied
        result = _capture(["git", "-C", str(submodule), "apply", str(patch)])
        if result.returncode != 0:
            raise JudgeError(
                f"cannot apply {patch.name} to {submodule}: {result.stderr.strip()}"
            )
        applied.append(patch.name)
    return applied


def build_image(root: Path | None = None, *, timeout: float | None = None) -> int:
    """Build the judge image from the submodule.  Returns podman's exit status."""
    root = root or repository_root()
    context = submodule_dir(root) / ".docker" / "tier3"
    if not context.is_dir():
        raise JudgeError(
            f"no image build context at {context}; the judge-server submodule is "
            f"missing -- fetch it with 'git submodule update --init --depth 1 vendor/judge-server'"
        )
    for name in apply_patches(root):
        print(f"applied {name} to the judge-server submodule")
    args = [
        "podman",
        "build",
        "--build-arg",
        f"TAG={BUILD_ARG_TAG}",
        "-t",
        IMAGE,
        str(context),
    ]
    print(f"building {IMAGE} from {context}", flush=True)
    print(f"  base image {BASE_IMAGE}; this pull plus build is multi-GB and slow", flush=True)
    kwargs = {} if timeout is None else {"timeout": timeout}
    return _run(args, **kwargs).returncode


def ensure_image(root: Path | None = None) -> None:
    """Build the image if it is absent; raise with instructions if that fails."""
    root = root or repository_root()
    if image_exists():
        return
    if build_image(root) != 0:
        raise JudgeError(
            f"building {IMAGE} failed; see podman's output above.  The build context "
            f"is {submodule_dir(root)}/.docker/tier3"
        )
    if not image_exists():
        raise JudgeError(f"podman reported success but {IMAGE} is still absent")


# ---------------------------------------------------------------------------
# Pool sizing and container discovery
# ---------------------------------------------------------------------------


def default_count() -> int:
    """The ``nproc``-derived, capped default pool size (decision Q28)."""
    return max(1, min(os.cpu_count() or 1, MAX_DEFAULT_COUNT))


def container_name(ordinal: int) -> str:
    return f"{NAME_PREFIX}{ordinal}"


def container_state(name: str) -> str | None:
    """``running``/``exited``/... for ``name``, or None if it does not exist."""
    result = _capture(["podman", "inspect", name, "--format", "{{.State.Status}}"])
    if result.returncode != 0:
        return None
    return result.stdout.strip()


def list_containers() -> list[tuple[int, str, str]]:
    """Pool containers as ``(ordinal, name, state)``, ordered by ordinal."""
    result = _capture(
        [
            "podman",
            "ps",
            "-a",
            "--filter",
            f"name={NAME_PREFIX}",
            "--format",
            "{{.Names}} {{.State}}",
        ]
    )
    if result.returncode != 0:
        raise JudgeError(f"cannot list containers: {result.stderr.strip()}")
    found = []
    for line in result.stdout.splitlines():
        parts = line.split()
        if len(parts) != 2:
            continue
        name, state = parts
        suffix = name.removeprefix(NAME_PREFIX)
        if not suffix.isdigit():
            continue
        found.append((int(suffix), name, state))
    return sorted(found)


def running_containers() -> list[str]:
    return [name for _, name, state in list_containers() if state == "running"]


# ---------------------------------------------------------------------------
# The generated judge config
# ---------------------------------------------------------------------------


def write_config(path: Path) -> Path:
    """Write the judge config the pool containers load.

    ``problem_storage_globs`` must use the single-segment ``/problems/**/`` form
    (verified against ``dmoj/judgeenv.py:get_problem_roots``, which does
    ``dirname(dirname(x))`` on each matched ``init.yml``): the ``/**/*`` form
    used by ``juez/config/judge.yml`` also matches nested files, and those extra
    roots break ``get_problem_root()``'s ``fnmatch`` filter.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"problem_storage_globs:\n  - {PROBLEMS_MOUNT}/**/\n")
    return path


def pool_dir(root: Path) -> Path:
    """Host directory holding the generated config, so status can report it."""
    return root / ".judge-pool"


# ---------------------------------------------------------------------------
# Starting and stopping containers
# ---------------------------------------------------------------------------


def _container_command() -> str:
    """The shell the container runs: prepare the pool dir, then drop privileges.

    Two jobs, both of which need root *inside* the container:

    * ``/run`` is root-owned, and the launcher runs as ``judge`` (``dmoj``
      refuses to run as root, ``judge.py:sanity_check``), so the FIFO's
      directory is created and chowned here.
    * the launcher is executed through ``setpriv`` exactly the way the image's
      own entrypoint runs ``dmoj-cli``, so the judge sees the same user, HOME
      and PATH the production judge does.
    """
    return (
        # These are the image's own entrypoint's settings (`/judge/.docker/entry`),
        # repeated because this command bypasses it.  Without HOME=/home/judge the
        # judge's self-test cannot find the toolchains that live under it; the
        # entrypoint also sets LANG/PYTHONIOENCODING so that UTF-8 output from a
        # submission survives.
        "export DMOJ_IN_DOCKER=1 PYTHONUNBUFFERED=1 LANG=C.UTF-8 "
        "PYTHONIOENCODING=utf8 HOME=/home/judge; "
        f"mkdir -p {POOL_DIR}/spool && chown -R judge:judge {POOL_DIR} && "
        ". /home/judge/.profile 2>/dev/null; "
        "exec setpriv --reuid judge --regid judge --clear-groups "
        "/env/bin/python3 /run/judge_runtime/launcher.py"
    )


def start_container(
    ordinal: int,
    root: Path,
    config: Path,
    *,
    idle_timeout: int = DEFAULT_IDLE_TIMEOUT,
) -> str:
    """Start one pool container, or adopt the running one with that name.

    Adopting rather than re-creating is what makes "already running does not
    double-start" true, and it is also why a pool is cheap to leave alone: the
    expensive part is ``listen()``, so a running container is always preferred
    over a fresh one.
    """
    name = container_name(ordinal)
    state = container_state(name)
    if state == "running":
        return "running"
    if state is not None:
        # A stopped container is removed rather than restarted: its launcher has
        # already run, and `podman start` would replay that dead process rather
        # than the command used here.
        _podman(["rm", "-f", name], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    launch_container(
        name,
        problems_root=root,
        config=config,
        idle_timeout=idle_timeout,
    )
    return "started"


def container_run_args(
    name: str,
    *,
    problems_root: Path,
    config: Path,
    idle_timeout: int = DEFAULT_IDLE_TIMEOUT,
) -> list[str]:
    """The ``podman run`` arguments for one pool container.

    Split out from :func:`launch_container` because they are the container's
    whole contract -- the mount, the three capabilities, the generated config,
    and the launcher -- and reading them is how one checks that contract.
    """
    runtime = Path(__file__).resolve().parent / "judge_runtime"
    args = ["podman", "run", "-d", "-i", "--name", name]
    for cap in SANDBOX_CAPS:
        args += ["--cap-add", cap]
    args += [
        "-e",
        f"JUDGE_IDLE_TIMEOUT={idle_timeout}",
        "-e",
        f"JUDGE_POOL_DIR={POOL_DIR}",
        "-e",
        "JUDGE_CONFIG=/judge.yml",
        "-v",
        f"{problems_root}:{PROBLEMS_MOUNT}:z",
        "-v",
        f"{config}:/judge.yml:z",
        "-v",
        f"{runtime}:/run/judge_runtime:z",
        "--entrypoint",
        "/bin/bash",
        IMAGE,
        "-c",
        _container_command(),
    ]
    return args


def launch_container(
    name: str,
    *,
    problems_root: Path,
    config: Path,
    idle_timeout: int = DEFAULT_IDLE_TIMEOUT,
) -> None:
    """Run one pool container under ``name``; raise if podman refuses."""
    result = _capture(
        container_run_args(
            name, problems_root=problems_root, config=config, idle_timeout=idle_timeout
        )
    )
    if result.returncode != 0:
        raise JudgeError(
            f"cannot start {name}: {result.stderr.strip() or result.stdout.strip()}"
        )


def stop_container(name: str) -> bool:
    """Stop and remove ``name``; True if something was actually removed."""
    if container_state(name) is None:
        return False
    _podman(["rm", "-f", name], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return True


def ensure_pool(
    count: int | None = None,
    *,
    root: Path | None = None,
    idle_timeout: int = DEFAULT_IDLE_TIMEOUT,
) -> tuple[Path, list[str], list[str]]:
    """Make sure ``count`` containers are running; return root, names, started.

    The image is built first if absent, so ``judges start`` is the single command
    that takes a bare checkout to a working pool.
    """
    root = root or repository_root()
    ensure_image(root)
    wanted = count if count is not None else default_count()
    if wanted < 1:
        raise JudgeError(f"pool size must be at least 1, got {wanted}")
    config = write_config(pool_dir(root) / "judge.yml")

    started, names = [], []
    for ordinal in range(1, wanted + 1):
        name = container_name(ordinal)
        outcome = start_container(ordinal, root, config, idle_timeout=idle_timeout)
        names.append(name)
        if outcome == "started":
            started.append(name)
    return root, names, started


def pool_status(count: int | None = None) -> tuple[list[tuple[str, str]], int]:
    """Return ``(running name/state pairs, wanted count)``."""
    wanted = count if count is not None else default_count()
    known = {name: state for _, name, state in list_containers()}
    return sorted(known.items()), wanted


# ---------------------------------------------------------------------------
# Driving a container
# ---------------------------------------------------------------------------


@dataclasses.dataclass(frozen=True)
class Grading:
    """A parsed ``submit`` report."""

    raw: str
    verdicts: dict[str, int]
    batches: list[list[str]]
    compile_error: str | None

    @property
    def failures(self) -> int:
        """Cases reported with a non-AC verdict, ``--`` (skipped) included."""
        return sum(n for verdict, n in self.verdicts.items() if verdict != "AC")

    @property
    def accepted(self) -> bool:
        return bool(self.verdicts.get("AC")) and self.failures == 0


def require_running(name: str) -> None:
    state = container_state(name)
    if state != "running":
        raise JudgeError(
            f"judge container {name} is not running (state: {state or 'absent'}); "
            f"start the pool with 'problemsetting judges start'"
        )


def run_command(
    name: str,
    command: str,
    *,
    command_id: str,
    timeout: float = COMMAND_TIMEOUT,
) -> tuple[int, str]:
    """Send one command to a pool container; return ``(status, output)``.

    The client runs inside the container, so it reaches the launcher's FIFO
    (``podman exec`` starts a new process and cannot write the judge's stdin) and
    streams the command's output back here as it is produced.
    """
    require_running(name)
    request = json.dumps({"id": command_id, "command": command, "timeout": timeout})
    result = _run(
        # The client is mounted by start_container, alongside the launcher.
        ["podman", "exec", "-i", name, "/env/bin/python3", "/run/judge_runtime/client.py"],
        input=request,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=timeout + 60,
    )
    output = result.stdout
    if result.stderr.strip():
        output += result.stderr
    return result.returncode, output


def submit(
    name: str,
    problem: str,
    executor: str,
    source: Path,
    *,
    time_limit: float,
    memory_limit: int,
    problems_root: Path | None = None,
    command_id: str | None = None,
    timeout: float = COMMAND_TIMEOUT,
) -> Grading:
    """Grade one submission in a pool container and parse the verdicts.

    ``time_limit`` is in **seconds** and ``memory_limit`` in **KiB**, which is
    exactly what ``submit`` takes (``dmoj/commands/submit.py``: ``-tl`` float
    seconds defaulting to 2.0, ``-ml`` int KiB defaulting to 65536), so the values
    are passed through unchanged and never converted.

    ``problems_root`` is the host directory mounted at ``/problems`` -- the
    toolkit checkout for a normal pool.  It is a parameter because the source
    path has to be expressed relative to *that* mount: mapping against the wrong
    root would silently grade a different file.
    """
    source_in_container = container_path(source, problems_root)
    command = (
        f"submit {problem} {executor} {source_in_container} "
        f"-tl {time_limit:g} -ml {int(memory_limit)}"
    )
    status, raw = run_command(
        name,
        command,
        command_id=command_id or f"submit-{problem}-{os.getpid()}",
        timeout=timeout,
    )
    return parse_grading(raw, status)


def container_path(source: Path, problems_root: Path | None = None) -> str:
    """Map a host path under the mounted root to its ``/problems/...`` path."""
    problems_root = problems_root or repository_root()
    try:
        relative = source.resolve().relative_to(problems_root.resolve())
    except ValueError:
        raise JudgeError(
            f"{source} is outside the directory mounted at {PROBLEMS_MOUNT} "
            f"({problems_root}); only files under it are visible to the pool "
            f"containers"
        ) from None
    return f"{PROBLEMS_MOUNT}/{relative.as_posix()}"


# ---------------------------------------------------------------------------
# Verdict parsing
# ---------------------------------------------------------------------------

#: ``  Test case  1 WA [0.004s ...]`` / ``  Test case  2 --``.  The verdict is
#: the token after the case number; ``--`` marks a case skipped because an
#: earlier case in the same batch failed, and it fails the batch too.
_CASE_RE = re.compile(r"Test case\s+(\d+)\s+(\S+)")
_BATCH_RE = re.compile(r"Batch #(\d+)")
_COMPILE_ERROR_MARKERS = (
    "Failed compiling submission",
    "CompileError",
    "Failed compiling",
)
_COMMAND_ERROR_MARKERS = (
    "unknown problem",
    "unknown language",
    "no language is selected",
    "Unrecognized command",
)


#: DMOJ colours verdicts (`dmoj/judge.py:_ipc_result` wraps them in
#: ``ansi_style``).  The launcher passes ``--no-ansi``, but the toolkit is not the
#: only thing that can drive a pool container, so stripping here keeps the parser
#: from depending on how the judge was invoked.
_ANSI_RE = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")


def parse_verdicts(raw: str) -> dict[str, int]:
    """Count per-case verdicts, keyed by verdict code."""
    counts: dict[str, int] = {}
    for line in _ANSI_RE.sub("", raw).splitlines():
        match = _CASE_RE.search(line)
        if match:
            verdict = match.group(2)
            counts[verdict] = counts.get(verdict, 0) + 1
    return counts


def parse_batches(raw: str) -> list[list[str]]:
    """Group per-case verdicts by ``Batch #k`` section, in the order reported."""
    batches: list[list[str]] = []
    for line in _ANSI_RE.sub("", raw).splitlines():
        if _BATCH_RE.search(line):
            batches.append([])
            continue
        match = _CASE_RE.search(line)
        if match and batches:
            batches[-1].append(match.group(2))
    return batches


def parse_grading(raw: str, status: int) -> Grading:
    """Turn a ``submit`` transcript into a :class:`Grading`.

    A command-level failure (unknown problem or language, a compile error) is
    reported as a compile error rather than as "zero verdicts", because the two
    need different fixes and an empty verdict set alone cannot tell them apart.
    """
    compile_error = None
    for marker in _COMPILE_ERROR_MARKERS:
        if marker in raw:
            compile_error = _extract_compile_error(raw)
            break
    if compile_error is None and not parse_verdicts(raw):
        for marker in _COMMAND_ERROR_MARKERS:
            if marker in raw:
                compile_error = raw.strip()
                break
    if compile_error is None and status != 0 and not parse_verdicts(raw):
        compile_error = raw.strip() or f"judge exited with status {status}"
    return Grading(
        raw=raw,
        verdicts=parse_verdicts(raw),
        batches=parse_batches(raw),
        compile_error=compile_error,
    )


def _extract_compile_error(raw: str) -> str:
    """The compiler's message, which is everything after the failure banner."""
    for line in raw.splitlines():
        if "Failed compiling" in line:
            return line.strip()
    return raw.strip()


# ---------------------------------------------------------------------------
# Problem re-discovery
# ---------------------------------------------------------------------------


def update_problems(name: str) -> str:
    """Tell a pool container to re-scan problem directories.

    Decision Q28: after regenerating cases the pool is told to re-discover, not
    restarted.  ``dmoj/control.py`` serves exactly ``POST /update/problems`` (and
    ``GET /metrics``) from inside the container's own loopback; the launcher
    starts that endpoint because ``judge run``'s HTTP server is not on the CLI
    path.  Requesting it through ``podman exec`` keeps it off the host entirely.
    """
    require_running(name)
    script = (
        "from urllib.request import urlopen, Request\n"
        "try:\n"
        "    r = urlopen(Request('http://127.0.0.1:9998/update/problems', method='POST'), timeout=30)\n"
        "    print(r.status, r.read().decode())\n"
        "except Exception as e:\n"
        "    raise SystemExit(f'error: {e}')\n"
    )
    result = _capture(["podman", "exec", name, "/env/bin/python3", "-c", script])
    if result.returncode != 0:
        raise JudgeError(
            f"cannot ask {name} to re-discover problems: "
            f"{result.stderr.strip() or result.stdout.strip()}"
        )
    return result.stdout.strip()


# ---------------------------------------------------------------------------
# Readiness and idle autostop
# ---------------------------------------------------------------------------


def wait_ready(name: str, timeout: float = READY_TIMEOUT) -> bool:
    """Block until the container's launcher finished discovery."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        state = container_state(name)
        if state != "running":
            return False
        result = _capture(["podman", "exec", name, "test", "-f", f"{POOL_DIR}/ready"])
        if result.returncode == 0:
            return True
        time.sleep(0.5)
    return False


# ---------------------------------------------------------------------------
# `judges` subcommand
# ---------------------------------------------------------------------------

HELP = "manage the judge image and the pool of long-lived judge containers"

ACTIONS = ("build", "start", "status", "stop", "update")


def add_arguments(parser) -> None:
    parser.add_argument(
        "action",
        choices=ACTIONS,
        help=(
            "build: build the judge image from the submodule; "
            "start: start (or reuse) the pool; "
            "status: list the pool; "
            "stop: stop and remove the pool; "
            "update: ask running containers to re-discover problems"
        ),
    )
    parser.add_argument(
        "--count",
        type=int,
        default=None,
        help=f"pool size (default: min(nproc, {MAX_DEFAULT_COUNT}) = {default_count()})",
    )
    parser.add_argument(
        "--idle-timeout",
        type=int,
        default=DEFAULT_IDLE_TIMEOUT,
        metavar="SECONDS",
        help=f"stop a container after this long with no command (default: {DEFAULT_IDLE_TIMEOUT})",
    )


def _action_start(args) -> int:
    _, names, started = ensure_pool(args.count, idle_timeout=args.idle_timeout)
    for name in started:
        print(f"started {name}")
    for name in names:
        if name not in started:
            print(f"reusing {name} (already running)")
    print(f"{len(names)} judge container(s) available; waiting for discovery")
    for name in names:
        if wait_ready(name):
            print(f"  {name} ready")
        else:
            print(f"  {name} did not report ready in time", file=sys.stderr)
    return 0


def _action_stop(_args) -> int:
    stopped = [name for name in running_containers() if stop_container(name)]
    for name in stopped:
        print(f"stopped {name}")
    if not stopped:
        print("no judge containers to stop")
    return 0


def _action_status(args) -> int:
    containers, wanted = pool_status(args.count)
    if not containers:
        print(f"no judge containers (a pool of {wanted} would be started by `judges start`)")
    for name, state in containers:
        print(f"  {name}  {state}")
    print(f"image  {IMAGE}  {'present' if image_exists() else 'MISSING'}")
    return 0


def _action_update(_args) -> int:
    names = running_containers()
    if not names:
        raise JudgeError("no judge containers running; start the pool with 'judges start'")
    for name in names:
        print(f"{name}: {update_problems(name)}")
    return 0


def run(args) -> int:
    actions = {
        "build": lambda _args: build_image(),
        "start": _action_start,
        "stop": _action_stop,
        "status": _action_status,
        "update": _action_update,
    }
    return actions[args.action](args)


register(Command(name="judges", help=HELP, add_arguments=add_arguments, run=run))

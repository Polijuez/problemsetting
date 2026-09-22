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
import itertools
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

#: Paths under the problems mount that must NOT be discoverable as problems.
#: The vendored judge-server is the important one: its own testsuite ships ~46
#: problems, several of which collide with natural author names (``batched``,
#: ``easy``, ``sorted``, ``generator``, ``aplusb``).  DMOJ discovers recursively,
#: so without masking them an author's ``batched`` silently loses the
#: duplicate-name race to DMOJ's and the judge grades the wrong problem.
#: ``.judge-pool`` holds the generated config and is masked for tidiness.
MASKED_UNDER_PROBLEMS = ("vendor", ".judge-pool")

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


#: Environment override naming the problems root outright (decision Q6).  It wins
#: over detection, so a script can point at a problems tree from anywhere.
PROBLEMS_ROOT_ENV = "PROBLEMS_ROOT"

#: The directory holding a problemset repo's problems.  Beside
#: :data:`VENDORED_TOOLKIT` it is the vendoring signature detection walks up for.
PROBLEMS_DIRNAME = "problems"

#: The vendored toolkit's own path inside a problemset repo.  `problems/` and this
#: together mean "this directory is a problemset repo" -- neither alone does.
VENDORED_TOOLKIT = Path("vendor") / "problemsetting"


def toolkit_root() -> Path:
    """The toolkit's own checkout -- the directory holding ``vendor/``.

    This is where the judge image is built from, so it is the root that
    ``vendor/judge-server`` is resolved against; it is **not** the directory
    mounted at ``/problems`` (see :func:`problems_root`).

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


def repository_root() -> Path:
    """Historical name for :func:`toolkit_root`, kept for existing callers.

    It has always meant the toolkit checkout, and the build paths and the tests
    still call it that way; new code should say which root it means.
    """
    return toolkit_root()


def problemset_root(start: Path | None = None) -> Path | None:
    """The problemset repo at or above ``start`` (default: cwd), or None.

    Detection is the vendoring signature rather than a guess: a directory holding
    **both** ``problems/`` and ``vendor/problemsetting/`` is a problemset repo
    (decision Q6).  Either marker alone is too common to mean anything -- the
    toolkit's own checkout holds ``vendor/`` but no ``problems/``.
    """
    here = (start or Path.cwd()).resolve()
    for candidate in (here, *here.parents):
        if (candidate / PROBLEMS_DIRNAME).is_dir() and (candidate / VENDORED_TOOLKIT).is_dir():
            return candidate
    return None


def problems_root() -> Path:
    """The host directory bind-mounted at ``/problems``.

    Every gradeable problem and artifact has to live under it, and it is *not*
    the toolkit root in general -- a problemset repo mounts ``<repo>/problems``,
    so the toolkit and its vendored judge-server are structurally out of reach
    (decision Q1).  Three sources, in order (decision Q6):

    1. ``PROBLEMS_ROOT``, when set: named outright.
    2. Detection: a cwd inside a problemset repo uses that repo's ``problems/``.
    3. Otherwise the toolkit root -- the one case where the toolkit *is* the
       problems root, which is how the toolkit's own tests and problems work.
    """
    override = problems_root_override()
    if override is not None:
        return override
    detected = problemset_root()
    if detected is not None:
        return (detected / PROBLEMS_DIRNAME).resolve()
    return toolkit_root()


def problems_root_override() -> Path | None:
    """``PROBLEMS_ROOT`` resolved, or None when it is unset.

    The explicit half of :func:`problems_root`, named so a caller that needs to
    *distinguish* "the author said where problems live" from "we guessed" can ask
    without re-reading the environment.
    """
    override = os.environ.get(PROBLEMS_ROOT_ENV)
    return Path(override).resolve() if override else None


def _default_problems_root() -> Path:
    """:func:`problems_root`, under a name a ``problems_root`` parameter cannot shadow.

    Every caller that needs the default also takes a ``problems_root`` argument,
    so the resolver itself has to be reachable by another name from inside them.
    """
    return problems_root()


def resolve_problem(problem: str, *, root: Path | None = None) -> Path:
    """The directory a problem argument names, or an error naming where we looked.

    Two forms are accepted, because both read naturally from a problemset repo
    root: ``<problem>``, resolved against the problems root, and a path such as
    ``problems/<problem>``, resolved against cwd like every other path.  A bare
    name that exists relative to cwd wins -- that is the behaviour every existing
    caller relies on -- but a bare name that exists in **both** places and is not
    the same directory is refused rather than silently resolving to one of them.

    "Is this a path or a bare name?" is decided on the argument as typed, not on
    ``Path``'s normalised parts: ``Path('./suma').parts`` is ``('suma',)``, so a
    parts-based test would treat an explicitly prefixed path as a bare name and
    could refuse it as ambiguous -- exactly when the author had already said which
    one they meant.
    """
    root = root if root is not None else problems_root()
    given = Path(problem)
    cwd_candidate = Path.cwd() / given
    if _is_path(problem):
        # A path, not a bare name: resolved against cwd exactly as before.
        return cwd_candidate
    root_candidate = root / given
    in_cwd = cwd_candidate.exists()
    in_root = root_candidate.exists()
    if in_cwd and in_root and cwd_candidate.resolve() != root_candidate.resolve():
        raise JudgeError(
            f"{problem!r} names two different directories: {cwd_candidate} and "
            f"{root_candidate}.  The problems root is {root}; pass the path you mean"
        )
    if in_cwd:
        return cwd_candidate
    if in_root:
        return root_candidate
    raise JudgeError(
        f"no problem named {problem!r}: looked for {cwd_candidate} and {root_candidate} "
        f"(the problems root is {root})"
    )


def _is_path(problem: str) -> bool:
    """Whether the argument was given as a path rather than as a bare problem name.

    Anything carrying a separator, and the two dot-directories, is a path a caller
    spelled out on purpose; only a single plain component is a name to look up
    under the problems root as well.
    """
    if problem in (os.curdir, os.pardir):
        return True
    separators = {os.sep} | ({os.altsep} if os.altsep else set())
    return any(separator in problem for separator in separators)


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


def mask_dir(root: Path) -> Path:
    """Create and return the empty directory bound over :data:`MASKED_UNDER_PROBLEMS`.

    One empty directory serves every mask target: the containers only ever see
    its emptiness, never its contents.  It lives inside :func:`pool_dir` so a
    single ``rm -rf`` of the pool directory cleans up both.
    """
    path = pool_dir(root) / "mask"
    path.mkdir(parents=True, exist_ok=True)
    return path


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
    problems_root: Path,
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
        problems_root=problems_root,
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
    ]
    # Mask the vendored judge-server, whose own testsuite ships ~46 problems
    # (``batched``, ``easy``, ``sorted``, ``generator``, ``aplusb``, ...).  DMOJ
    # discovers with ``glob.iglob(..., recursive=True)`` over ``/problems/**/``,
    # so it descends into ``vendor/judge-server/testsuite/`` and finds them --
    # and a problem the author names ``batched`` then loses the duplicate-name
    # race to DMOJ's, so the judge silently grades the WRONG problem.  Measured:
    # without this mask discovery returns 62 init.yml of which 46 are the
    # vendored suite's; with it, 15 and only the author's.
    #
    # An empty bind-mount over the path is what actually hides it: ``--tmpfs``
    # does not override an existing volume mount at the same target, and a
    # glob-level exclusion is not available (the judge takes globs, not
    # patterns to skip).  The mask directory is created empty and never written.
    mask = mask_dir(problems_root)
    for relative in MASKED_UNDER_PROBLEMS:
        target = problems_root / relative
        if target.exists():
            args += ["-v", f"{mask}:{PROBLEMS_MOUNT}/{relative}:z"]
    args += [
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
    problems_root: Path | None = None,
    idle_timeout: int = DEFAULT_IDLE_TIMEOUT,
) -> tuple[Path, list[str], list[str]]:
    """Make sure ``count`` containers are running; return problems root, names, started.

    The image is built first if absent, so ``judges start`` is the single command
    that takes a bare checkout to a working pool.

    ``root`` is the **toolkit** root the image is built from; ``problems_root`` is
    the directory mounted at ``/problems``.  They are separate because a problemset
    repo mounts only its ``problems/`` (decision Q1), so the toolkit and its
    vendored judge-server are never visible to the containers; when neither is
    given, each is resolved by its own rule (:func:`toolkit_root`,
    :func:`problems_root`).
    """
    toolkit = root or toolkit_root()
    mount = _default_problems_root() if problems_root is None else problems_root
    ensure_image(toolkit)
    wanted = count if count is not None else default_count()
    if wanted < 1:
        raise JudgeError(f"pool size must be at least 1, got {wanted}")
    config = write_config(pool_dir(mount) / "judge.yml")

    started, names = [], []
    for ordinal in range(1, wanted + 1):
        name = container_name(ordinal)
        outcome = start_container(ordinal, mount, config, idle_timeout=idle_timeout)
        names.append(name)
        if outcome == "started":
            started.append(name)
    return mount, names, started


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
    """A parsed ``submit`` report.

    ``compile_error`` and ``run_error`` are deliberately distinct.  The first is
    a *result*: the submission failed to build, which DMOJ reports as the ``CE``
    verdict, so it legitimately satisfies an entry declaring ``verdict: CE``.
    The second is the absence of a result: the run never produced a verdict for a
    reason that has nothing to do with the submission (the container died, the
    command timed out, the judge rejected the invocation).  Treating the two as
    one made an infrastructure failure *satisfy* a declared ``CE`` and report a
    pass on a submission that was never compiled at all.
    """

    raw: str
    verdicts: dict[str, int]
    batches: list[list[str]]
    compile_error: str | None
    run_error: str | None = None

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
    try:
        result = _run(
            # The client is mounted alongside the launcher.
            [
                "podman",
                "exec",
                "-i",
                name,
                "/env/bin/python3",
                "/run/judge_runtime/client.py",
            ],
            input=request,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            # The client enforces `timeout` itself and reports it as its own
            # exit status; this outer bound only catches a client that died
            # without reporting, which would otherwise hang the toolkit forever.
            timeout=timeout + 60,
        )
    except subprocess.TimeoutExpired:
        raise JudgeError(
            f"the command never finished: {name} did not report a result for "
            f"{command_id!r} within {timeout + 60:g}s.  The container may be stuck "
            f"mid-compile; check it with 'podman logs {name}'"
        ) from None
    output = result.stdout
    if result.stderr.strip():
        output += result.stderr

    return result.returncode, output

#: The sequence that makes each of one process's ``submit`` command ids unique.
#: The launcher keys a command's spool file by that id, so two submissions
#: sharing one id -- which is what a ``verify`` run over several entries does --
#: would have the second read the first's transcript and report its verdict.
_SUBMISSION_SEQUENCE = itertools.count(1)


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
    problemset repo's ``problems/`` for a normal pool, and only the toolkit
    checkout when the toolkit is itself the problems root.  It is a parameter
    because the source path has to be expressed relative to *that* mount: mapping
    against the wrong root would silently grade a different file.
    """
    source_in_container = container_path(source, problems_root)
    command = (
        f"submit {problem} {executor} {source_in_container} "
        f"-tl {time_limit:g} -ml {int(memory_limit)}"
    )
    status, raw = run_command(
        name,
        command,
        command_id=command_id or f"submit-{problem}-{os.getpid()}-{next(_SUBMISSION_SEQUENCE)}",
        timeout=timeout,
    )
    return parse_grading(raw, status)


def container_path(source: Path, problems_root: Path | None = None) -> str:
    """Map a host path under the mounted root to its ``/problems/...`` path."""
    problems_root = problems_root or _default_problems_root()
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

#: A batch header is a line that IS the header, not one that merely contains the
#: text: DMOJ emits it alone (``dmoj/judge.py:242``,
#: ``report(ansi_style('#ansi[Batch #%d](yellow|bold)'))``).  Anchoring matters
#: because a compiler echoes the offending source line verbatim, so a submission
#: containing ``// Batch #2`` in its source produced a diagnostic line that
#: opened a phantom batch section -- which then looked like a stale-discovery
#: problem instead of the compile error it was.
_BATCH_RE = re.compile(r"^\s*Batch #(\d+)\s*$")

#: The pool launcher's own per-case points line, which it prints immediately
#: after the ``Test case`` line it describes (see
#: :func:`problemsetting.judge_runtime.launcher.case_points_line`).  DMOJ's own
#: transcript never carries points, so this line is the only way a fractional
#: ``CheckerResult`` score -- a checker returning ``CheckerResult(True, 0.7 *
#: point_value)`` -- is distinguishable from full marks.  It is optional: a
#: transcript without it (or from a judge driven directly, without the launcher)
#: parses exactly as it did before, with the points simply unknown.
_CASE_POINTS_RE = re.compile(r"<<<DMOJ-POOL CASE\s+(\d+)\s+([^/\s]+)/([^>\s]+)>>>")

#: The measurement that follows a verdict, as ``dmoj/judge.py:_ipc_result``
#: formats it: ``[0.004s (0.005s wall) | 3964kb | 14 switches ...]``.  Only the
#: CPU time and the peak memory are captured -- the wall clock is the same
#: measurement with the unavoidable scheduling noise added, and the toolkit
#: reports what a limit would be calibrated against.  A skipped (``--``) case
#: carries no bracket at all, so the measurement is optional as a group.
_CASE_DETAIL_RE = re.compile(
    r"Test case\s+(\d+)\s+(\S+)"
    r"(?:\s+\[\s*([\d.]+)s\s+\([\d.]+\s*s wall\)\s*\|\s*(\d+)kb)"
)
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


@dataclasses.dataclass(frozen=True)
class CaseResult:
    """One ``Test case`` line: its verdict and what the judge measured.

    ``time`` is seconds and ``memory`` is KiB, exactly as the judge reported
    them; they are observation only, never fed back as a limit.  ``points`` and
    ``total`` are the grader's own score for the case and what it was worth,
    taken from the launcher's synthetic points line; both are ``None`` when the
    transcript carries no such line, which is what a judge driven outside the
    pool reports.
    """

    number: int
    verdict: str
    time: float | None = None
    memory: int | None = None
    points: float | None = None
    total: float | None = None

    @property
    def fraction(self) -> float | None:
        """``points`` as a share of what the case was worth, or None if unknown.

        A zero-point case has no share to report -- every verdict earns all of
        nothing -- so it answers None rather than dividing by zero.
        """
        if self.points is None or not self.total:
            return None
        return self.points / self.total


def parse_case_line(line: str) -> CaseResult | None:
    """The case one line reports, or None when the line is not a result.

    The measurements are optional as a group: ``--`` (a case skipped after an
    earlier failure in its batch) is reported with no bracket at all, and a
    transcript whose timing was formatted differently must still yield its
    verdicts rather than losing every case.
    """
    match = _CASE_DETAIL_RE.search(line)
    if match:
        return CaseResult(
            number=int(match.group(1)),
            verdict=match.group(2),
            time=float(match.group(3)),
            memory=int(match.group(4)),
        )
    match = _CASE_RE.search(line)
    if match:
        return CaseResult(number=int(match.group(1)), verdict=match.group(2))
    return None


def parse_case_points(line: str) -> tuple[int, float, float] | None:
    """The ``(position, points, total)`` one points line carries, or None.

    ``position`` is the same ``case_number`` DMOJ printed on the ``Test case``
    line it follows -- one global counter across the whole run, batches included
    (``dmoj/judge.py`` incrementing ``case_number`` before each case), which is
    what makes the pair matchable even though a batch restarts nothing.
    """
    match = _CASE_POINTS_RE.search(_ANSI_RE.sub("", line))
    if match is None:
        return None
    try:
        return int(match.group(1)), float(match.group(2)), float(match.group(3))
    except ValueError:  # a malformed line must not lose the run
        return None


def _scored_case(line: str, following: str | None) -> CaseResult | None:
    """The case ``line`` reports, with ``following``'s points folded in.

    ``following`` is the next line in the transcript, which is where the
    launcher puts a case's points line.  The fold only binds when that line's
    position matches the case, so a malformed, doubled or stray line is simply
    left to be read as the ordinary non-case line it falls back to.
    """
    case = parse_case_line(line)
    if case is None or following is None:
        return case
    scored = parse_case_points(following)
    if scored is None:
        return case
    position, points, total = scored
    if position != case.number:
        return case
    return dataclasses.replace(case, points=points, total=total)


def parse_cases(raw: str) -> list[CaseResult]:
    """Every reported case, in judge order, with its verdict and measurements.

    A ``Test case`` line can also contain ``Batch #k``: DMOJ interpolates the
    grader's feedback into it (``dmoj/judge.py`` ``colored_feedback``) and a
    checker may echo the submission's own text there.  This reader has always
    taken such a line for the case it reports, so it must not consult the batch
    header at all.
    """
    lines = _ANSI_RE.sub("", raw).splitlines()
    results: list[CaseResult] = []
    index = 0
    while index < len(lines):
        case = _scored_case(lines[index], lines[index + 1] if index + 1 < len(lines) else None)
        if case is not None:
            results.append(case)
            if case.points is not None:
                index += 1  # the points line it consumed
        index += 1
    return results


def parse_verdicts(raw: str) -> dict[str, int]:
    """Count per-case verdicts, keyed by verdict code."""
    counts: dict[str, int] = {}
    for case in parse_cases(raw):
        counts[case.verdict] = counts.get(case.verdict, 0) + 1
    return counts


def parse_batch_cases(raw: str) -> list[list[CaseResult]]:
    """Group reported cases by ``Batch #k`` section, in the order reported.

    Sectioning is on the header first, which is the opposite precedence to
    :func:`parse_cases` and always has been: a ``Batch #k`` line opens a section
    even if it is also a ``Test case`` line (see that function), and a case
    before the first header belongs to no section.
    """
    lines = _ANSI_RE.sub("", raw).splitlines()
    batches: list[list[CaseResult]] = []
    index = 0
    while index < len(lines):
        line = lines[index]
        if _BATCH_RE.search(line):
            batches.append([])
            index += 1
            continue
        case = _scored_case(line, lines[index + 1] if index + 1 < len(lines) else None)
        if case is None:
            index += 1
            continue
        if batches:
            batches[-1].append(case)
        if case.points is not None:
            index += 1  # the points line it consumed
        index += 1
    return batches


def parse_batches(raw: str) -> list[list[str]]:
    """Per-batch verdict codes, in the order reported."""
    return [[case.verdict for case in group] for group in parse_batch_cases(raw)]


def parse_grading(raw: str, status: int) -> Grading:
    """Turn a ``submit`` transcript into a :class:`Grading`.

    Three outcomes, and they are not interchangeable:

    * a compile error -- the submission failed to build, which is the ``CE``
      verdict and may satisfy an entry declaring ``CE``;
    * a command error -- the judge rejected the invocation itself (unknown
      problem or language), which is the author's mistake and is reported as
      such;
    * a run error -- anything else that produced no verdict from a non-zero
      status.  A non-zero status with no verdicts and no compile marker means
      the run failed, not the submission: the pool client reports its own
      timeout this way (``error: command timed out after 600s``, exit 102).
      Classifying that as a compile error let an infrastructure failure
      *satisfy* a declared ``verdict: CE``, i.e. report a pass on a submission
      that was never compiled.
    """
    verdicts = parse_verdicts(raw)
    compile_error = None
    for marker in _COMPILE_ERROR_MARKERS:
        if marker in raw:
            compile_error = _extract_compile_error(raw)
            break

    run_error = None
    if compile_error is None and not verdicts:
        for marker in _COMMAND_ERROR_MARKERS:
            if marker in raw:
                run_error = raw.strip()
                break
        else:
            if status != 0:
                run_error = raw.strip() or f"judge exited with status {status}"

    return Grading(
        raw=raw,
        verdicts=verdicts,
        batches=parse_batches(raw),
        compile_error=compile_error,
        run_error=run_error,
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
    # Every container of ours, not just the running ones: an idle container
    # autostops itself and stays behind in the ``exited`` state, so a stop that
    # only looked at running containers left those to accumulate silently.  Observed
    # in practice -- six autostopped containers survived several `judges stop`s.
    stopped = [name for _, name, _ in list_containers() if stop_container(name)]
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

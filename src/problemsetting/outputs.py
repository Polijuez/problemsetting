"""``outputs``: run the model solution over every case, producing ``cases/*.out``.

The expected outputs are the judge's yardstick for every submission, so this is
the step where a mistake is worst: an expected output produced by a program the
judge never builds turns into a silently wrong verdict for every contestant.
Two facts therefore drive the whole module.

**The commands mirror the judge's own executors.**  Compiling and running are the
same shapes ``dmoj/executors/<EXECUTOR>.py`` uses -- same source order, same
``-DONLINE_JUDGE``, same ``-O2 -lm -std=`` flags -- so that a difference between
the local run and the judged run is a difference the author can see.  The host
toolchain is the one the judge image ships (``gcc``/``g++``/``ghc``/``javac``/
``python3``); the resolved ``executor`` axis decides the C/C++ standard and the
interpreter for the Python family.

**A function-signature model is composed exactly as ``SignatureGrader`` does.**
``dmoj/graders/signature.py:20-28`` textually prefixes the submission with
``#include "<header>"`` plus ``#define main main_<uuid>``, then hands the header
and the entry point to the executor as *extra source files* -- ``CLikeExecutor``
writes them out and passes all three to the compiler, in the order submission,
header, entry (``dmoj/executors/c_like_executor.py:33-79``).  This module
reproduces that: the prefix, the ``-DSIGNATURE_GRADER`` define, the header
compiled as its own translation unit, and the source order.  One deliberate
addition, noted where it happens: the composed file lives under ``__meta__``
rather than beside the header, so ``-I`` names the problem directory.

**Incrementality is a content-addressed DAG.**  Every step -- a source file, a
compiled program, one case's expected output -- is a :class:`Node` whose
*fingerprint* is derived from its recipe plus its inputs' fingerprints, never
from the bytes of what it produced (a compiled binary is a deterministic
function of the recipe and the sources, so hashing 15 MB of it buys nothing).
Unchanged solution plus unchanged cases therefore recompile and rerun nothing;
editing one case reruns that case alone.  The cache lives in the problem's
``__meta__/outputs/cache.json``, a gitignored build artifact.

**A failure deletes what it invalidated.**  ``.out`` files are written to a
temporary name and renamed only on success, so a crash, a timeout or a non-zero
exit cannot leave a partial file; and when a step fails, every expected output
that no longer corresponds to the current sources is deleted outright.  A stale
``cases/{i}.out`` is the one artifact this toolkit must never leave behind,
because the judge would grade it as the answer.
"""

from __future__ import annotations

import argparse
import dataclasses
import hashlib
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import threading
import uuid
from collections.abc import Callable, Iterable, Mapping, Sequence
from concurrent.futures import Future, ThreadPoolExecutor
from pathlib import Path
from typing import Any

from . import cases
from . import meta as meta_mod
from .commands import Command, register
from .errors import OutputError

#: Everything this step writes lives under the problem's ``__meta__``, which
#: ``.gitignore`` already covers: the compiled program, the composed signature
#: translation unit, and the dependency cache.  Nothing here is committed.
ARTIFACTS_ROOT = Path("__meta__") / "outputs"

CACHE_FILENAME = "cache.json"

#: Bumped when the cache's meaning changes, so an old file is ignored rather than
#: misread.  A stale cache rebuilds; a misinterpreted one would skip work.
CACHE_VERSION = 1

#: Suffix of the temporary file a case's output is written to before the rename.
PARTIAL_SUFFIX = ".part"

#: Bound on a single case run.  This is a *hang guard*, not a judge limit: DMOJ's
#: ``tl`` for the model solution is seconds, so five minutes is far beyond
#: anything gradable and exists only so a looping solution stops the toolkit
#: instead of hanging it.
CASE_TIMEOUT = 300.0

#: Bound on one compile.  Generous: a large Java or C++ source can take a while,
#: and a compiler that has not finished in ten minutes has stopped making sense.
COMPILE_TIMEOUT = 600.0

#: Upper bound on concurrent case runs.  A run may be a JVM whose heap is the
#: problem's memory limit, so 8 * 256 MiB is a sane ceiling on a laptop;
#: individual runs are short, so the cap costs almost nothing.
MAX_JOBS = 8

#: How much of a tool's diagnostics to show.  The first errors are the root ones.
DIAGNOSTIC_LIMIT = 8000


# ---------------------------------------------------------------------------
# Host mirrors of the DMOJ executors
# ---------------------------------------------------------------------------


@dataclasses.dataclass(frozen=True)
class ToolSpec:
    """The host commands that reproduce one DMOJ executor.

    Mirrors ``dmoj/executors/<EXECUTOR>.py``: ``compiler``/``runtime`` are
    candidate commands tried in order with :func:`shutil.which`, which is what
    ``command_paths`` does inside the judge; ``std`` is the executor's ``std``,
    passed as ``-std=``.
    """

    compiler: tuple[str, ...] = ()
    runtime: tuple[str, ...] = ()
    std: str | None = None


#: One row per executor ``meta.py`` accepts for a model solution.  ``TEXT`` has
#: no row on purpose: the output-only models never compile or run anything, they
#: copy their answer, and that path is taken before this table is consulted.
TOOLSPECS: dict[str, ToolSpec] = {
    "C11": ToolSpec(compiler=("gcc", "cc"), std="c11"),
    "C23": ToolSpec(compiler=("gcc", "cc"), std="c23"),
    "CPP03": ToolSpec(compiler=("g++",), std="c++03"),
    "CPP11": ToolSpec(compiler=("g++",), std="c++11"),
    "CPP14": ToolSpec(compiler=("g++",), std="c++14"),
    "CPP17": ToolSpec(compiler=("g++",), std="c++17"),
    "CPP20": ToolSpec(compiler=("g++",), std="c++20"),
    "CPP23": ToolSpec(compiler=("g++",), std="c++23"),
    "HASK": ToolSpec(compiler=("ghc",)),
    "JAVA": ToolSpec(compiler=("javac",), runtime=("java",)),
    "JAVA8": ToolSpec(compiler=("javac8", "javac"), runtime=("java8", "java")),
    "PY2": ToolSpec(runtime=("python2",)),
    "PY3": ToolSpec(runtime=("python3",)),
    "PYPY3": ToolSpec(runtime=("pypy3",)),
}


@dataclasses.dataclass(frozen=True)
class Tools:
    """A :class:`ToolSpec` resolved against this host."""

    executor: str
    family: str
    std: str | None
    compiler: str | None
    runtime: str | None
    memory: int


def _which(candidates: Sequence[str], executor: str, what: str, language: str) -> str:
    """The first of ``candidates`` present on PATH (or a JDK's ``bin``), else raise.

    ``JAVA_HOME/bin`` is consulted because that is how every JDK distribution and
    every CI image exposes ``javac``/``java`` without putting them on PATH; the
    judge image installs them into ``/usr/bin`` instead, which ``which`` finds.
    """
    directories: list[str | None] = [None]
    if (home := os.environ.get("JAVA_HOME")) is not None:
        directories.append(str(Path(home) / "bin"))
    for directory in directories:
        for candidate in candidates:
            found = (
                shutil.which(candidate)
                if directory is None
                else shutil.which(candidate, path=directory)
            )
            if found is not None:
                return found
    looked_in = "PATH" + (" or $JAVA_HOME/bin" if len(directories) > 1 else "")
    tried = ", ".join(f"`{candidate}`" for candidate in candidates)
    raise OutputError(
        f"no {what} for {language} found in {looked_in} (tried {tried}); the "
        f"{executor} executor of the judge image ships it, so install it on this host "
        f"or run `problemsetting outputs` where it exists"
    )


def resolve_tools(resolved: meta_mod.ResolvedMeta) -> Tools:
    """Resolve the problem's executor into host commands.

    The executor comes from the resolved axes (``solutionlang`` plus an optional
    explicit ``executor:`` override), so a problem that pins ``CPP20`` or
    ``PYPY3`` gets that standard or that interpreter here too.
    """
    executor = resolved.executor
    language = f"a {resolved.solutionlang} model solution"
    spec = TOOLSPECS.get(executor)
    if spec is None:
        raise OutputError(
            f"executor {executor!r} cannot produce expected outputs: this toolkit "
            f"knows no host toolchain for it (valid: {', '.join(sorted(TOOLSPECS))})"
        )
    return Tools(
        executor=executor,
        family=meta_mod.FAMILY_BY_EXT[resolved.solutionlang],
        std=spec.std,
        compiler=(
            _which(spec.compiler, executor, "compiler", language) if spec.compiler else None
        ),
        runtime=(_which(spec.runtime, executor, "runtime", language) if spec.runtime else None),
        memory=resolved.solution_limits.memory,
    )


# Java's public class name decides the file name ``javac`` compiles, so it is read
# the same way the judge reads it (`dmoj/executors/java_executor.py:find_class`).
# Comments and string literals are stripped first, because `public class` inside a
# comment must not fool the search.
_JAVA_COMMENT = re.compile(r"/\*.*?\*/", re.DOTALL | re.UNICODE)
_JAVA_STRING = re.compile(r"'(?:\\.|[^'\\])'|\"(?:\\.|[^\"\\])*\"", re.DOTALL | re.UNICODE)
_JAVA_LINE_COMMENT = re.compile(r"//.*?(?=[\r\n])", re.UNICODE)
_JAVA_CLASS = re.compile(
    r"\bpublic\s+(?:strictfp\s+)?(?:(?:abstract|final)\s+)?(?:strictfp\s+)?class\s+"
    r"([\w$][\w$]*?)\b",
    re.UNICODE,
)
_JAVA_PACKAGE = re.compile(r"\bpackage\s+([^.;]+(?:\.[^.;]+)*?);", re.UNICODE)


def java_class_name(source: Path) -> str:
    """The public class ``javac`` will compile, or an actionable error.

    The judge refuses a Java submission without a public class or with a package
    declaration, and so does this step: a Java model solution is compiled *by
    name*, so guessing a name would compile the wrong file.
    """
    try:
        text = source.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as error:
        raise OutputError(f"{source}: {error}") from error
    stripped = _JAVA_LINE_COMMENT.sub("", _JAVA_STRING.sub("", _JAVA_COMMENT.sub("", text)))
    if (package := _JAVA_PACKAGE.search(stripped)) is not None:
        raise OutputError(
            f"{source}: the model solution declares `package {package.group(1)};`; DMOJ "
            f"rejects a package declaration, and the class is run from the submission "
            f"directory, so the package would not resolve"
        )
    match = _JAVA_CLASS.search(stripped)
    if match is None:
        raise OutputError(
            f"{source}: no public class found; DMOJ compiles a Java submission by its "
            f"public class name, so the model solution needs e.g. "
            f"`public class Solution {{ ... }}`"
        )
    return match.group(1)


# ---------------------------------------------------------------------------
# The build graph
# ---------------------------------------------------------------------------


def md5(path: Path) -> str:
    """Content digest of a file, streamed so a large case does not load whole."""
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "md5").hexdigest()


class Node:
    """One step of the build graph: an input file, a program, or an expected output.

    ``fingerprint`` is ``recipe`` plus the sorted fingerprints of ``deps``, so a
    step is out of date exactly when one of its inputs changed.  The bytes of a
    step's own ``product`` are deliberately absent: a compiled binary is a
    deterministic function of its recipe and its sources, so hashing it would
    only be expensive.  ``product``'s *existence* is checked separately, which is
    what catches a deleted or never-built artifact.
    """

    __slots__ = ("key", "label", "product", "recipe", "deps", "build", "_fingerprint")

    def __init__(
        self,
        *,
        key: str,
        product: Path | None,
        recipe: str,
        label: str | None = None,
        deps: Sequence["Node"] = (),
        build: Callable[[], None] | None = None,
    ) -> None:
        self.key = key
        self.label = label or key
        self.product = product
        self.recipe = recipe
        self.deps = tuple(deps)
        #: ``None`` means "an input file: nothing to build".
        self.build = build
        self._fingerprint: str | None = None

    def fingerprint(self) -> str:
        if self._fingerprint is None:
            material = self.recipe + "\0" + "\0".join(
                sorted(dep.fingerprint() for dep in self.deps)
            )
            self._fingerprint = hashlib.md5(material.encode("utf-8")).hexdigest()
        return self._fingerprint


def _source(problem_dir: Path, path: Path, memo: dict[str, Node]) -> Node:
    """The node for an input file, relative to ``problem_dir``.

    The cache key is relative so that the cache travels with a problem directory
    instead of being invalidated by moving it.
    """
    key = path.relative_to(problem_dir).as_posix()
    node = memo.get(key)
    if node is None:
        node = memo[key] = Node(key=key, product=path, recipe=f"file md5 {md5(path)}")
    return node


def _topological(roots: Iterable[Node]) -> list[Node]:
    """Every node reachable from ``roots``, dependencies before dependents."""
    order: list[Node] = []
    seen: set[str] = set()

    def visit(node: Node) -> None:
        if node.key in seen:
            return
        seen.add(node.key)
        for dep in node.deps:
            visit(dep)
        order.append(node)

    for root in roots:
        visit(root)
    return order


@dataclasses.dataclass(frozen=True)
class Plan:
    """What ``outputs`` will do: the graph, the expected outputs, and the archive.

    ``archive`` is the ``.zip`` ``init.yml`` declares.  It carries a *published*
    copy of every case, and the site deploys the archive rather than the loose
    files, so a stale one would ship the answers this run just rejected.
    """

    nodes: list[Node]
    outputs: list[Node]
    archive: Path | None


# ---------------------------------------------------------------------------
# Planning one model
# ---------------------------------------------------------------------------


def _declared_archive(problem_dir: Path, document: Mapping[str, Any]) -> Path | None:
    """The ``.zip`` ``init.yml`` declares, if it exists on disk.

    The archive is what the site deploys, and DMOJ reads a case's expected answer
    *from the archive when it is present* -- ``ProblemDataManager.open`` prefers
    the loose file but the zip is baked at build time, so a zip left over from a
    previous run still carries those answers even after ``cases/*.out`` were
    deleted.  Tracking it here is what lets a failure discard it too.
    """
    name = document.get("archive")
    if not isinstance(name, str) or not name:
        return None
    path = problem_dir / name
    return path if path.is_file() else None


def _require(problem_dir: Path, name: str, why: str) -> Path:
    path = problem_dir / name
    if not path.is_file():
        raise OutputError(f"{path} not found: {why}")
    return path


def _signature_files(document: Mapping[str, Any], source: str) -> tuple[str, str, bool]:
    """``(entry, header, allow_main)`` from ``init.yml``'s ``signature_grader:``.

    Read from ``init.yml`` rather than from the toolkit's constants so that this
    step composes exactly what the judge will compose, even for a problem that
    renames the header or the entry point.
    """
    handler = document.get("signature_grader")
    if not isinstance(handler, Mapping):
        raise OutputError(
            f"{source}: no `signature_grader:` mapping, but the model grades by "
            f"signature; re-run `problemsetting cases` to regenerate init.yml"
        )
    entry, header = handler.get("entry"), handler.get("header")
    for key, value in (("entry", entry), ("header", header)):
        if not isinstance(value, str) or not value:
            raise OutputError(
                f"{source}: `signature_grader.entry` and `.header` must be file names, "
                f"got {key}: {value!r}"
            )
    return entry, header, bool(handler.get("allow_main", False))


@dataclasses.dataclass(frozen=True)
class SignatureLayout:
    """The three translation units DMOJ's signature build compiles."""

    #: The staging recipe; editing init.yml's mapping must invalidate the stage.
    recipe: str
    #: Staged file names, in ``get_compile_args``'s order.
    names: tuple[str, str, str]
    #: The ``#include`` line the composed submission begins with.
    include: str


def signature_layout(problem_id: str, source_ext: str, entry_name: str, header_name: str) -> SignatureLayout:
    """The three file names ``SignatureGrader`` + ``CLikeExecutor`` produce.

    Both halves have to be reproduced together, because they only make sense as a
    unit: getting either wrong compiles a program the judge never builds.

    ``signature.py:20-24`` composes the submission's text -- ``#include
    "<header>"``, then (unless the problem sets ``allow_main``) a rename of its
    ``main``, then the submission verbatim -- and ``signature.py:26-28`` passes the
    executor ``aux_sources`` of ``{<id>_submission: composed, <header>: header}``
    plus the configured entry as the primary source.

    ``CLikeExecutor`` then decides the *file names*, and this is where it stops
    matching the intuition: ``__init__`` (:33-36) stores ``aux_sources`` and adds
    ``{problem_id + self.ext: entry}`` -- **not** the configured entry name, and
    ``ext`` has no dot -- and ``create_files`` (:41-48) appends ``.<ext>`` to any
    name containing none.  The names are therefore:

    * ``<id>_submission.<ext>`` -- the composed submission;
    * ``<header>`` **unchanged** (it already has a dot, so nothing is appended);
    * ``<id><ext>.<ext>`` -- the entry, renamed after the problem id.

    Verified by instantiating the judge's own executor: for problem ``myproblem``,
    ``C11`` reports ``['myproblem_submission.c', 'signature.hpp', 'myproblemc.c']``
    and ``CPP17`` reports the ``.cpp`` forms.

    Those suffixes are not cosmetic: the compiler dispatches on them, so they
    decide each file's language.  The submission and the entry always agree with
    the executor (both C for ``C11``), which is what makes the symbols line up;
    the header is compiled as whatever its own suffix says (``.hpp`` -> C), and
    that is harmless precisely because a header only declares.
    """
    # `CLikeExecutor.ext` is dotless ('c', 'cpp'), and both derived names paste it
    # in after a dot, so the leading dot of `.c`/`.cpp` is dropped here once.
    ext = source_ext.lstrip(".")
    return SignatureLayout(
        recipe=(
            f"signature compose id={problem_id} source-ext={source_ext} "
            f"judge-entry={entry_name} judge-header={header_name}"
        ),
        names=(f"{problem_id}_submission.{ext}", header_name, f"{problem_id}{ext}.{ext}"),
        include=f'#include "{header_name}"',
    )


def _stage_signature(
    solution: Path,
    header: Path,
    entry: Path,
    allow_main: bool,
    layout: SignatureLayout,
    destination: Path,
) -> None:
    """Write the three staged translation units, byte-for-byte as the judge has them."""
    destination.mkdir(parents=True, exist_ok=True)
    submission_name, header_name, entry_name = layout.names
    prefix = layout.include + "\n"
    if not allow_main:
        prefix += f"#define main main_{uuid.uuid4().hex}\n"
    (destination / submission_name).write_bytes(prefix.encode("utf-8") + solution.read_bytes())
    (destination / header_name).write_bytes(header.read_bytes())
    (destination / entry_name).write_bytes(entry.read_bytes())


def _stage_signature_step(
    solution: Path,
    header: Path,
    entry: Path,
    allow_main: bool,
    layout: SignatureLayout,
    destination: Path,
) -> Callable[[], None]:
    def step() -> None:
        _stage_signature(solution, header, entry, allow_main, layout, destination)

    return step


def _compile_step(argv: Sequence[str], cwd: Path, what: str) -> Callable[[], None]:
    def step() -> None:
        announce(f"$ {shlex.join(argv)}")
        run_tool(argv, cwd=cwd, what=what)

    return step


def _run_step(
    argv: Sequence[str], cwd: Path, input_path: Path, output_path: Path
) -> Callable[[], None]:
    def step() -> None:
        run_case(argv, cwd=cwd, input_path=input_path, output_path=output_path)

    return step


def _copy_step(source: Path, output_path: Path) -> Callable[[], None]:
    def step() -> None:
        copy_case(source, output_path)

    return step


def plan(
    problem_dir: Path,
    resolved: meta_mod.ResolvedMeta,
    document: Mapping[str, Any],
    pairs: Sequence[tuple[str | None, str]],
    artifact_dir: Path,
) -> Plan:
    """Build the graph that produces every expected output ``init.yml`` names."""
    memo: dict[str, Node] = {}
    outputs: list[Node] = []
    archive = _declared_archive(problem_dir, document)

    if resolved.is_output_only:
        # Q11's output-only models: the submission is a text file the judge runs
        # with `cat`, so the expected answer for every case is the model
        # solution itself.  Nothing is compiled and nothing is run.
        solution = _require(
            problem_dir,
            f"solution{resolved.solutionlang}",
            f"the {resolved.model!r} model's expected output is a copy of the model "
            f"solution, and meta.yml declares solutionlang: {resolved.solutionlang}",
        )
        solution_node = _source(problem_dir, solution, memo)
        for _, output_name in pairs:
            product = problem_dir / output_name
            outputs.append(
                Node(
                    key=output_name,
                    product=product,
                    recipe=f"copy {solution_node.key}",
                    deps=(solution_node,),
                    build=_copy_step(solution, product),
                )
            )
        return Plan(nodes=_topological(outputs), outputs=outputs, archive=archive)

    tools = resolve_tools(resolved)
    solution = _require(
        problem_dir,
        f"solution{resolved.solutionlang}",
        f"meta.yml declares solutionlang: {resolved.solutionlang}",
    )
    sources: list[Path] = [solution]
    source_deps: list[Node] = [_source(problem_dir, solution, memo)]
    defines = ["-DONLINE_JUDGE"]

    if resolved.uses_signature:
        init_source = str(problem_dir / cases.INIT_FILENAME)
        entry_name, header_name, allow_main = _signature_files(document, init_source)
        layout = signature_layout(problem_dir.name, resolved.solutionlang, entry_name, header_name)
        entry = _require(
            problem_dir,
            entry_name,
            f"the signature grader compiles `{entry_name}` against the submission "
            f"(init.yml names it as `signature_grader.entry`)",
        )
        header = _require(
            problem_dir,
            header_name,
            f"the signature grader prefixes the submission with `#include "
            f'"{header_name}"` (init.yml names it as `signature_grader.header`)',
        )
        staged = artifact_dir / "signature"
        sources = [staged / name for name in layout.names]
        source_deps = [
            Node(
                key=staged.relative_to(problem_dir).as_posix(),
                product=staged,
                label=f"the signature translation units ({', '.join(layout.names)})",
                recipe=layout.recipe,
                deps=[
                    source_deps[0],
                    _source(problem_dir, header, memo),
                    _source(problem_dir, entry, memo),
                ],
                build=_stage_signature_step(
                    solution, header, entry, allow_main, layout, staged
                ),
            )
        ]
        # The define `SignatureGrader` passes (`signature.py:28`), so a model
        # solution can branch on it exactly as a submission can.
        defines.append("-DSIGNATURE_GRADER")



    program = _program_node(
        problem_dir, resolved, tools, artifact_dir, sources, source_deps, defines, solution
    )

    run_argv_base = _run_argv(problem_dir, tools, program, solution)
    for input_name, output_name in pairs:
        if input_name is None:
            raise OutputError(
                f"{problem_dir / cases.INIT_FILENAME}: case `{output_name}` declares no "
                f"`in:` file, but {resolved.model!r} submissions read stdin; DMOJ would "
                f"grade them against an empty input, so the expected output would be "
                f"wrong.  Re-run `problemsetting cases {problem_dir.name}`"
            )
        input_path = _require(
            problem_dir,
            input_name,
            "init.yml references it as a case input; re-run `problemsetting cases`",
        )
        input_node = _source(problem_dir, input_path, memo)
        product = problem_dir / output_name
        outputs.append(
            Node(
                key=output_name,
                product=product,
                recipe=f"run {shlex.join(run_argv_base)} < {input_name}",
                deps=(program, input_node),
                build=_run_step(run_argv_base, problem_dir, input_path, product),
            )
        )

    return Plan(nodes=_topological(outputs), outputs=outputs, archive=archive)


def _program_node(
    problem_dir: Path,
    resolved: meta_mod.ResolvedMeta,
    tools: Tools,
    artifact_dir: Path,
    sources: Sequence[Path],
    source_deps: Sequence[Node],
    defines: Sequence[str],
    solution: Path,
) -> Node:
    """The node that turns the model solution into something runnable.

    ``sources`` is the translation-unit list in the judge's compile order: just
    the model solution for a normal model, or the composed submission, the header
    and the (executor-extension) entry point for a signature one.
    """
    family = tools.family
    relative = lambda path: path.relative_to(problem_dir).as_posix()  # noqa: E731

    if family == "py":
        assert tools.runtime is not None
        # Python needs no build: the interpreter runs the source, the way the
        # judge's PY3 executor runs its loader script.  The node exists so that
        # every case run depends on the source through one place, and so a change
        # of interpreter invalidates them.
        argv = [tools.runtime, "-BS", relative(solution)]
        return Node(
            key=relative(solution) + "#program",
            product=solution,
            label=f"the model solution run by {tools.executor}",
            recipe=f"interpret {shlex.join(argv)}",
            deps=source_deps,
        )

    if family == "java":
        assert tools.compiler is not None
        # `javac` compiles by class name, so the source is staged under the name
        # its public class declares -- which is what the judge does too.
        class_name = java_class_name(solution)
        root = artifact_dir / "java"
        staged = root / f"{class_name}.java"
        classes = root / "classes"
        argv = [
            tools.compiler,
            "-encoding",
            "UTF-8",
            "-d",
            relative(classes),
            relative(staged),
        ]
        return Node(
            key=relative(classes),
            product=classes,
            label=f"solution{resolved.solutionlang} ({class_name}, {tools.executor})",
            recipe=f"compile {shlex.join(argv)} cwd={problem_dir.name}",
            deps=source_deps,
            build=_java_build(solution, staged, argv, problem_dir),
        )

    assert tools.compiler is not None
    product = artifact_dir / "solution"
    if family == "hs":
        # `HASK.py`'s own command: `ghc -O2 -o <problem> <source>`.  The added
        # `-outputdir` keeps GHC's interface and object files under `__meta__`
        # rather than the problem root; it cannot affect the program.
        argv = [tools.compiler, "-O2", "-outputdir", relative(artifact_dir), "-o"]
        argv += [relative(product), relative(solution)]
    else:
        # The judge's own compile line, flag for flag
        # (`c_like_executor.py:67-79`, `GCCMixin.get_flags`).  Only `-march=` is
        # omitted: it is a tuning flag the judge derives from the container's CPU
        # probe, and it cannot change an answer.
        argv = [tools.compiler, "-Wall", *(relative(path) for path in sources)]
        argv += [*defines, "-O2", "-lm"]
        if tools.std is not None:
            argv += [f"-std={tools.std}"]
        argv += ["-fmax-errors=5", "-s", "-o", relative(product)]
    return Node(
        key=relative(product),
        product=product,
        label=f"solution{resolved.solutionlang} ({tools.executor})",
        recipe=f"compile {shlex.join(argv)} cwd={problem_dir.name}",
        deps=source_deps,
        build=_compile_step(
            argv, problem_dir, f"compiling {relative(solution)} with {tools.executor}"
        ),
    )


def _run_argv(
    problem_dir: Path,
    tools: Tools,
    program: Node,
    solution: Path,
) -> list[str]:
    relative = lambda path: path.relative_to(problem_dir).as_posix()  # noqa: E731
    if tools.family == "py":
        assert tools.runtime is not None
        return [tools.runtime, "-BS", relative(solution)]
    if tools.family == "java":
        assert tools.runtime is not None and program.product is not None
        # The heap and the GC flags are the judge's (`java_executor.py:120-133`);
        # the sandbox agent and the VM-mode flag are deliberately omitted, since
        # they enforce limits rather than affect the program.
        return [
            tools.runtime,
            "-Xss128m",
            f"-Xmx{tools.memory}K",
            "-XX:+UseSerialGC",
            "-cp",
            relative(program.product),
            java_class_name(solution),
        ]
    assert program.product is not None
    return [relative(program.product)]


def _java_build(
    solution: Path, staged: Path, argv: Sequence[str], cwd: Path
) -> Callable[[], None]:
    """Stage the source under its public class name, then run ``javac``.

    The judge writes the submission as ``<class>.java`` before compiling, so the
    staged file is what makes ``javac`` accept a model solution whose file name is
    not its class name.
    """

    def step() -> None:
        staged.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(solution, staged)
        announce(f"$ {shlex.join(argv)}")
        run_tool(argv, cwd=cwd, what=f"compiling {solution} with javac")

    return step


# ---------------------------------------------------------------------------
# Running commands
# ---------------------------------------------------------------------------


def announce(text: str) -> None:
    """Report a step that is about to run: compiles are few and worth seeing."""
    print(f"  {text}", flush=True)


def _diagnostics(result: subprocess.CompletedProcess[bytes]) -> str:
    """A tool's complaints, stderr first, bounded to what a human can read."""
    raw = result.stderr + result.stdout
    text = raw.decode("utf-8", "replace").strip()
    if len(text) > DIAGNOSTIC_LIMIT:
        text = text[:DIAGNOSTIC_LIMIT] + f"\n... ({len(text) - DIAGNOSTIC_LIMIT} more characters)"
    return text


def run_tool(argv: Sequence[str], *, cwd: Path, what: str) -> None:
    """Run a compiler, aborting with its own diagnostics on a non-zero exit."""
    try:
        result = subprocess.run(
            list(argv),
            cwd=cwd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=COMPILE_TIMEOUT,
        )
    except FileNotFoundError as error:
        raise OutputError(f"{what}: {error}") from error
    except subprocess.TimeoutExpired as error:
        raise OutputError(
            f"{what}: still running after {COMPILE_TIMEOUT:g}s; killed.  Check the "
            f"command above by hand"
        ) from error
    if result.returncode != 0:
        raise OutputError(
            f"{what}: exited with status {result.returncode}; the tool said:\n"
            f"{_diagnostics(result) or '(no output)'}"
        )


def run_case(argv: Sequence[str], *, cwd: Path, input_path: Path, output_path: Path) -> None:
    """Run one case, publishing its output only if the run succeeded.

    The output goes to ``<name>.part`` and is renamed on success, so a crash, a
    timeout or a non-zero exit leaves the old file (or nothing) rather than a
    truncated answer that the judge would compare against as if it were correct.
    """
    partial = output_path.with_name(output_path.name + PARTIAL_SUFFIX)
    try:
        with input_path.open("rb") as stdin, partial.open("wb") as stdout:
            result = subprocess.run(
                list(argv),
                cwd=cwd,
                stdin=stdin,
                stdout=stdout,
                stderr=subprocess.PIPE,
                timeout=CASE_TIMEOUT,
            )
        if result.returncode != 0:
            raise OutputError(
                f"the model solution exited with status {result.returncode} on "
                f"{input_path.name}; its output is not the expected answer.  It said:\n"
                f"{result.stderr.decode('utf-8', 'replace').strip() or '(nothing)'}"
            )
        if partial.stat().st_size == 0:
            print(
                f"  warning: the model solution produced no output for {input_path.name}",
                file=sys.stderr,
            )
        partial.replace(output_path)
    except subprocess.TimeoutExpired as error:
        raise OutputError(
            f"the model solution did not finish {input_path.name} within "
            f"{CASE_TIMEOUT:g}s and was killed.  This bound is a hang guard, not a "
            f"judge limit: DMOJ grades with the problem's tl in seconds, so a model "
            f"solution this slow cannot be graded"
        ) from error
    finally:
        partial.unlink(missing_ok=True)


def copy_case(source: Path, output_path: Path) -> None:
    """Output-only models: the expected answer *is* the model solution's text."""
    partial = output_path.with_name(output_path.name + PARTIAL_SUFFIX)
    try:
        shutil.copyfile(source, partial)
        partial.replace(output_path)
    finally:
        partial.unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# The dependency cache
# ---------------------------------------------------------------------------


def read_cache(path: Path) -> dict[str, str]:
    """The recorded fingerprints, or an empty mapping if the cache is unusable.

    A cache that cannot be read is never an error: it is a build artifact, and
    the only consequence of ignoring it is that work is redone.
    """
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(document, dict) or document.get("version") != CACHE_VERSION:
        return {}
    targets = document.get("targets")
    if not isinstance(targets, dict):
        return {}
    return {
        key: value
        for key, value in targets.items()
        if isinstance(key, str) and isinstance(value, str)
    }


def write_cache(path: Path, entries: Mapping[str, str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    document = {"version": CACHE_VERSION, "targets": dict(sorted(entries.items()))}
    path.write_text(json.dumps(document, indent=1) + "\n", encoding="utf-8")


def _up_to_date(node: Node, recorded: Mapping[str, str]) -> bool:
    return (
        node.product is not None
        and node.product.exists()
        and recorded.get(node.key) == node.fingerprint()
    )


# ---------------------------------------------------------------------------
# Executing the graph
# ---------------------------------------------------------------------------


def execute(plan: Plan, cache_path: Path) -> tuple[int, int]:
    """Build what is out of date; return ``(rebuilt, reused)`` expected outputs.

    Dependencies are awaited before a dependent is submitted, so the graph's
    levels become waves in one pool.  On the first failure the run stops, every
    expected output that no longer corresponds to the current sources is deleted,
    and the error is re-raised: the state left behind is either correct or
    obviously incomplete, never quietly wrong.
    """
    recorded = read_cache(cache_path)
    entries: dict[str, str] = dict(recorded)
    #: Only the expected outputs are counted: a compile is one step, not 21, and
    #: the summary's numbers are about what the author asked to be produced.
    wanted = {node.key for node in plan.outputs}
    built: set[str] = set()
    reused: set[str] = set()
    lock = threading.Lock()
    failure: OutputError | None = None
    failed: Node | None = None
    pending: dict[str, tuple[Node, Future[None]]] = {}
    workers = min(os.process_cpu_count() or 1, MAX_JOBS)

    def work(node: Node) -> None:
        assert node.build is not None
        node.build()
        with lock:
            entries[node.key] = node.fingerprint()
            built.add(node.key)

    with ThreadPoolExecutor(max_workers=workers) as pool:
        for node in plan.nodes:
            for dep in node.deps:
                entry = pending.pop(dep.key, None)
                if entry is None:
                    continue
                error = entry[1].exception()
                if error is not None and failure is None:
                    failure, failed = _as_output_error(error), entry[0]
            if failure is not None:
                break
            if _up_to_date(node, recorded):
                entries[node.key] = node.fingerprint()
                if node.key in wanted:
                    reused.add(node.key)
                continue
            if node.build is None:
                entries[node.key] = node.fingerprint()
                continue
            pending[node.key] = (node, pool.submit(work, node))

        # Whatever is still running must settle before the cache and the
        # invalidation below describe the same state.
        for node, future in pending.values():
            error = future.exception()
            if error is not None and failure is None:
                failure, failed = _as_output_error(error), node

    if failure is not None:
        assert failed is not None
        _discard(failed.product)
        entries.pop(failed.key, None)
        removed = _invalidate(plan, recorded, built)
        write_cache(cache_path, entries)
        # The archive is discarded on *any* failure, unconditionally: it is what
        # the site deploys and DMOJ reads a case's answer out of it, so a zip left
        # by the last successful run ships answers that may no longer match the
        # cases on disk.  The condition cannot be "did we delete loose outputs":
        # `cases` deletes an `.out` itself whenever its input changes, so when the
        # generator is retuned and the solution then breaks, `_invalidate` finds
        # nothing to remove and this check would skip the exact case it is for.
        archived = plan.archive is not None
        _discard(plan.archive)
        raise OutputError(
            _failure_report(
                failure, failed, removed, len(plan.outputs), len(built & wanted), archived
            )
        )

    write_cache(cache_path, entries)
    return len(built & wanted), len(reused)


def _discard(product: Path | None) -> None:
    """Remove a step's product, file or directory.

    A Java or signature program node's product is the directory the compiler
    writes into (``javac -d``, the staged signature sources), not a file, so
    ``Path.unlink`` would raise ``IsADirectoryError`` exactly when a rebuild fails
    after one successful run -- leaving the stale expected outputs and archive
    behind, which is the failure this whole path exists to prevent.
    """
    if product is None:
        return
    if product.is_dir():
        shutil.rmtree(product, ignore_errors=True)
    else:
        product.unlink(missing_ok=True)


def _as_output_error(error: BaseException) -> OutputError:
    """Keep an authoring error as an authoring error; let a bug keep its traceback.

    ``OutputError`` is the expected, actionable kind -- a compiler refusing the
    source, a toolchain missing, a case whose solution crashed -- and the CLI
    prints it as ``error: ...``.  Anything else is a bug in the toolkit, so it is
    re-raised with its traceback rather than flattened into a message.
    """
    if isinstance(error, OutputError):
        return error
    raise error


def _invalidate(plan: Plan, recorded: Mapping[str, str], built: set[str]) -> list[str]:
    """Delete every expected output that is not known to be current.

    Only the *outputs* are considered, never the compiler's product: an expected
    output that survives here is one the judge would grade as an answer, while a
    deleted binary merely costs a recompile.
    """
    removed: list[str] = []
    for node in plan.outputs:
        if node.key in built or _up_to_date(node, recorded):
            continue
        if node.product is not None and node.product.exists():
            _discard(node.product)
            removed.append(node.key)
    return removed


def _failure_report(
    failure: OutputError,
    node: Node,
    removed: Sequence[str],
    total: int,
    built: int,
    archived: bool,
) -> str:
    report = (
        f"{failure}\n"
        f"`outputs` stopped at {node.label}, after {built} of {total} expected output(s)."
    )
    if removed:
        shown = ", ".join(removed[:5]) + (", ..." if len(removed) > 5 else "")
        report += (
            f"  {len(removed)} expected output(s) that no longer correspond to the "
            f"sources were deleted ({shown}), so nothing stale can be graded as an "
            f"answer; regenerate them once the failure is fixed."
        )
    if archived:
        report += (
            f"  The archive was discarded too: DMOJ reads each case's answer from it, "
            f"so a zip from the previous run could have shipped answers that no longer "
            f"match the cases.  Re-run `problemsetting build` once the failure is fixed."
        )
    return report


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def add_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("problem", help="problem directory whose expected outputs to produce")


def run(args: argparse.Namespace) -> int:
    return run_outputs(args.problem)


def run_outputs(problem: str) -> int:
    problem_dir = Path.cwd() / problem
    # meta.yml first, like `cases`: the model decides whether there is anything to
    # compile at all.
    _, resolved = meta_mod.load(problem_dir)
    document = cases.load_init(problem_dir)
    pairs = cases.case_pairs(document, str(problem_dir / cases.INIT_FILENAME))

    artifact_dir = problem_dir / ARTIFACTS_ROOT
    artifact_dir.mkdir(parents=True, exist_ok=True)
    graph = plan(problem_dir, resolved, document, pairs, artifact_dir)

    if resolved.is_output_only:
        announce(f"{pairs[0][1].rsplit('/', 1)[0]}: copying the model solution as the answer")
    rebuilt, reused = execute(graph, artifact_dir / CACHE_FILENAME)

    total = len(graph.outputs)
    if rebuilt == 0:
        summary = f"{total} expected output(s) already up to date"
    elif reused == 0:
        summary = f"{total} expected output(s) -> {cases.CASES_DIRNAME}/"
    else:
        summary = (
            f"{rebuilt} of {total} expected output(s) rebuilt, {reused} reused "
            f"-> {cases.CASES_DIRNAME}/"
        )
    print(f"{problem_dir.name}: {summary}")
    return 0


register(
    Command(
        name="outputs",
        help="run the model solution over every case to produce cases/*.out",
        add_arguments=add_arguments,
        run=run,
    )
)

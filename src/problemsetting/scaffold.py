"""``problemsetting new``: scaffold a problem from a shipped model template."""

from __future__ import annotations

import argparse
import shutil
from pathlib import Path

import yaml

from . import judges
from . import meta as meta_mod
from . import templates
from .commands import Command, register
from .errors import ProblemsettingError, ScaffoldError
from .problems import validate_name


def add_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("problem", help="name of the problem to create (also its directory)")
    parser.add_argument(
        "--model",
        "-m",
        default="standard",
        help="model preset to scaffold from (default: standard)",
    )
    parser.add_argument(
        "--solutionlang",
        "-s",
        default=None,
        help="extension of the model solution (default: the template's own)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="replace the target directory if it already exists",
    )


def destination_for(name: str) -> Path:
    """Where ``new`` should put ``name``: the problems root, or cwd (decision Q14).

    Run at a problemset repo root, a problem belongs under that repo's
    ``problems/`` -- which is the directory the pool mounts, so it is where every
    gradeable problem has to live.  Anywhere else the author is working in a
    plain directory (a checkout of the toolkit itself, or a scratch tree), and
    cwd-relative placement is both what they mean and what the tests assert.

    An explicit ``PROBLEMS_ROOT`` names the problems root outright, so ``new``
    obeys it from anywhere: placing the problem under a detected repo while every
    other command resolves against the override would create a problem nobody can
    then grade.

    The two places that count as "at the repo root" are the repo root itself and
    its ``problems/`` directory: both read as "this is where problems go".  A cwd
    deeper inside the tree is left alone rather than silently teleported.
    """
    override = judges.problems_root_override()
    if override is not None:
        return override / name
    detected = judges.problemset_root()
    if detected is not None:
        problems = detected / judges.PROBLEMS_DIRNAME
        cwd = Path.cwd().resolve()
        if cwd in (detected, problems):
            return problems / name
    return Path.cwd() / name


def run(args: argparse.Namespace) -> int:
    name = validate_name(args.problem)
    destination = destination_for(name)

    if destination.exists() and not args.force:
        raise ScaffoldError(
            f"{destination} already exists -- pass --force to replace it, or choose another name"
        )

    source = templates.template_dir(args.model)
    solutionlang = pick_solutionlang(args.solutionlang, args.model)

    # meta.yml is derived from the template's own file so the scaffolding path and
    # the shipped template cannot disagree about keys or defaults.
    with (source / meta_mod.META_FILENAME).open() as handle:
        raw = yaml.safe_load(handle) or {}
    raw[meta_mod.MODEL_KEY] = args.model
    raw[meta_mod.SOLUTIONLANG_KEY] = solutionlang
    authoring = meta_mod.normalize(raw, str(source / meta_mod.META_FILENAME))

    if destination.is_dir():
        shutil.rmtree(destination)
    elif destination.exists():
        # `--force` replaces a problem directory; it never deletes a file the
        # author may have meant to keep under another name.
        raise ScaffoldError(
            f"{destination} is not a directory -- refusing to delete it; "
            f"move it aside first"
        )
    shutil.copytree(source, destination, ignore=shutil.ignore_patterns(*templates.TEMPLATE_IGNORE))

    meta_mod.write(destination, authoring)

    resolved = meta_mod.resolve(authoring)
    print(f"created {name}/ from model {args.model!r}")
    print(f"  solution     solution{solutionlang} lang={resolved.executor}")
    print(f"  limits       {resolved.solution_limits}")
    print("  next steps")
    print(f"    edit generator.py, then           problemsetting cases {name}")
    print(f"    cases + outputs + archive         problemsetting build {name}")
    print(f"    grade the declared submissions    problemsetting verify {name}")
    return 0


def _declared_solutionlang(model: str, shipped: tuple[str, ...]) -> str:
    """The solution extension the template's own ``meta.yml`` declares.

    Read leniently on purpose -- this only picks a *default*, and a scaffold must
    not break because a template is terse or its file is unreadable.  Anything
    short of a usable declaration falls back to the template's only solution, and
    a declaration the template does not actually ship is ignored rather than
    written for: a default that names a file which does not exist is worse than
    an arbitrary one that does.
    """
    path = templates.template_dir(model) / meta_mod.META_FILENAME
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, yaml.YAMLError):
        return shipped[0]
    declared = raw.get(meta_mod.SOLUTIONLANG_KEY) if isinstance(raw, dict) else None
    if isinstance(declared, str) and declared in shipped:
        return declared
    return shipped[0]


def pick_solutionlang(requested: str | None, model: str) -> str:
    """Choose the model solution's extension, defaulting to the template's own.

    "The template's own" is read from the template's ``meta.yml``, not guessed
    from the file list: a template that ships more than one solution declares
    which one it demonstrates (``signature-batched`` ships both ``.c`` and
    ``.cpp`` and declares ``.cpp``), and the extension that *sorts* first is not
    that statement.  A template that declares nothing falls back to its only
    solution, which is the same answer for every single-solution template -- so
    the declaration is a refinement, never a requirement.

    ``--solutionlang`` then selects among the template's solutions.  Asking for a
    language the model allows but the template does not carry has no correct file
    to write, and says so.
    """
    shipped = templates.solution_extensions(model)
    if requested is None:
        return _declared_solutionlang(model, shipped)
    if not requested.startswith("."):
        requested = "." + requested
    if requested not in meta_mod.EXECUTOR_BY_EXT:
        raise ProblemsettingError(
            f"unknown solution language {requested!r}; valid values: "
            f"{', '.join(sorted(meta_mod.EXECUTOR_BY_EXT))}"
        )
    allowed = meta_mod.allowed_extensions(meta_mod.MODELS[model])
    if requested not in allowed:
        raise ProblemsettingError(
            f"model {model!r} cannot use solutionlang {requested!r}; valid values: "
            f"{', '.join(allowed)}"
        )
    if requested not in shipped:
        raise ProblemsettingError(
            f"the {model!r} template ships a model solution only in "
            f"{', '.join(shipped)}, so there is no solution{requested} to write; "
            f"scaffold with the default and add your own solution{requested} plus "
            f"{meta_mod.SOLUTIONLANG_KEY}: {requested} to {meta_mod.META_FILENAME}"
        )
    return requested


register(
    Command(
        name="new",
        help="scaffold a new problem from a model template",
        add_arguments=add_arguments,
        run=run,
    )
)

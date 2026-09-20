"""``problemsetting new``: scaffold a problem from a shipped model template."""

from __future__ import annotations

import argparse
import shutil
from pathlib import Path

import yaml

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


def run(args: argparse.Namespace) -> int:
    name = validate_name(args.problem)
    destination = Path.cwd() / name

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


def pick_solutionlang(requested: str | None, model: str) -> str:
    """Choose the model solution's extension, defaulting to the template's own.

    A template ships one model solution per language it demonstrates -- the
    signature models ship both C and C++ -- so ``--solutionlang`` selects among
    the template's solutions.  Asking for a language the model allows but the
    template does not carry has no correct file to write, and says so.
    """
    shipped = templates.solution_extensions(model)
    if requested is None:
        return shipped[0]
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

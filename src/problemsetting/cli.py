"""Command-line entry point.

``problemsetting <subcommand> [options]``.  Subcommands live one per module
(:mod:`problemsetting.scaffold`, and later ``cases``, ``outputs``, ``verify``,
``stress``, ``judges``); :data:`problemsetting.commands.COMMANDS` lists them for
``--help`` and :func:`main` dispatches on the name.

Expected authoring errors become ``error: ...`` on stderr plus a non-zero exit;
anything else keeps its traceback, because it is a bug in the toolkit.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence

from . import __version__
from . import commands
from .errors import ProblemsettingError

# Importing a subcommand module registers it.  Tickets 02-06 add theirs here --
# one import each, and the dispatcher below never changes.
from . import cases  # noqa: F401  (registers `cases`, `archive`, `build`)
from . import judges  # noqa: F401  (registers `judges`)
from . import outputs  # noqa: F401  (registers `outputs`)
from . import scaffold  # noqa: F401  (registers `new`)
from . import verify  # noqa: F401  (registers `verify`)


def build_parser() -> argparse.ArgumentParser:
    """Assemble the top-level parser from the registry."""
    parser = argparse.ArgumentParser(
        prog="problemsetting",
        description="Scaffold, build and locally judge Polijuez (DMOJ) problems.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    subparsers = parser.add_subparsers(dest="command", metavar="<command>", required=True)

    for name in sorted(commands.COMMANDS):
        command = commands.COMMANDS[name]
        subparser = subparsers.add_parser(name, help=command.help, description=command.help)
        command.add_arguments(subparser)
        subparser.set_defaults(_run=command.run)

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run the CLI; return the process exit status."""
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args._run(args)
    except ProblemsettingError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())

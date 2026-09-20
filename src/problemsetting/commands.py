"""Subcommand registry.

Each subcommand module -- ``scaffold.py`` for ``new`` today, plus ``cases``,
``outputs``, ``verify``, ``stress`` and ``judges`` from later tickets -- calls
:func:`register` at import time, and ``cli.py`` imports each module once.

The registry is what ``--help`` lists and what ``main()`` dispatches on, so
adding a subcommand is a new module plus one import line; the dispatcher itself
never changes.
"""

from __future__ import annotations

import argparse
import dataclasses
from collections.abc import Callable


@dataclasses.dataclass(frozen=True)
class Command:
    """A subcommand: parser configuration plus its entry point."""

    name: str
    help: str
    add_arguments: Callable[[argparse.ArgumentParser], None]
    run: Callable[[argparse.Namespace], int]


COMMANDS: dict[str, Command] = {}


def register(command: Command) -> None:
    """Register ``command``.  A duplicate name is a programming error."""
    if command.name in COMMANDS:
        raise RuntimeError(f"subcommand {command.name!r} is already registered")
    COMMANDS[command.name] = command

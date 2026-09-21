"""Load a problem's author files from source, without touching the filesystem.

Each model template lives in ``src/problemsetting/models/<model>/`` and ships as
package data.  Importing one of its files through ``importlib``'s file loader
writes a ``__pycache__`` directory next to the source -- i.e. *into the shipped
package* -- and, worse, lets a stale bytecode entry shadow a same-second edit.

``problemsetting.cases.load_generator`` already avoids both traps by compiling
the source itself.  This helper exposes the same behaviour for tests, so a test
can inspect a template's ``generator``/``checker`` without leaving anything
behind.  It is deliberately not a production entry point: the toolkit has no
reason to load a module this way.
"""

from __future__ import annotations

import types
from pathlib import Path


def load_module(path: Path, name: str | None = None) -> types.ModuleType:
    """Compile ``path`` and execute it in a fresh module namespace.

    Nothing is written to disk: no ``__pycache__``, no bytecode.  Raises
    ``SyntaxError`` for a malformed file, exactly as an import would.
    """
    path = Path(path)
    module = types.ModuleType(name or f"_problemsetting_test_{path.stem}")
    module.__file__ = str(path)
    code = compile(path.read_text(encoding="utf-8"), str(path), "exec")
    exec(code, module.__dict__)
    return module

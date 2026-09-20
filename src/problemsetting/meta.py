"""``meta.yml``: the authoring-intent schema and preset → axis resolution.

``meta.yml`` is what marks a directory as a problem of this toolkit, and it is
the **only** hand-edited configuration file: ``init.yml`` is generated from it
(``problemsetting cases``) and is never committed.

Schema
------

.. code-block:: yaml

    model: standard          # required: one of the 8 model presets
    solutionlang: .cpp       # required: extension of the model solution
    limits:                  # optional: per-language limits, absolute values
      .cpp: {tl: 2.0, ml: 262144}
    grader: signature        # optional axis override
    io: stdio                # optional axis override
    executor: CPP20          # optional axis override

Per decision Q5/Q10 the model is *not* stored expanded.  A preset plus the
author's overrides is the source of truth, and the axes are re-derived on every
run -- writing the expansion back would silently freeze the preset.

Limits are **absolute** values in DMOJ's units (decision Q26): ``tl`` in
seconds, ``ml`` in **KiB**.  There are no site-side multipliers.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import yaml

from .errors import MetaError

META_FILENAME = "meta.yml"

#: Source extension -> DMOJ executor id used when ``executor:`` is absent.
EXECUTOR_BY_EXT: dict[str, str] = {
    ".c": "C11",
    ".cpp": "CPP17",
    ".hs": "HASK",
    ".java": "JAVA",
    ".py": "PY3",
    ".txt": "TEXT",
}

#: Every DMOJ executor this toolkit will accept as an ``executor:`` override,
#: mapped to the language family it can run.
EXECUTOR_FAMILY: dict[str, str] = {
    "C11": "c",
    "C23": "c",
    "CPP03": "cpp",
    "CPP11": "cpp",
    "CPP14": "cpp",
    "CPP17": "cpp",
    "CPP20": "cpp",
    "CPP23": "cpp",
    "HASK": "hs",
    "JAVA": "java",
    "JAVA8": "java",
    "PY2": "py",
    "PY3": "py",
    "PYPY3": "py",
    "TEXT": "text",
}

FAMILY_BY_EXT: dict[str, str] = {
    ".c": "c",
    ".cpp": "cpp",
    ".hs": "hs",
    ".java": "java",
    ".py": "py",
    ".txt": "text",
}

#: The extension that *names* each language family -- the one ``limits:`` and
#: ``solutionlang:`` keys use.  It is the inverse of :data:`FAMILY_BY_EXT`, stated
#: here rather than derived at each call site so that the two tables cannot
#: disagree: a new family added to :data:`EXECUTOR_FAMILY` without an entry here
#: is caught by the assertion below at import time, not by an unexplained
#: ``StopIteration`` in a grading run.
CANONICAL_EXT: dict[str, str] = {
    family: ext for ext, family in FAMILY_BY_EXT.items()
}

assert set(CANONICAL_EXT) == set(EXECUTOR_FAMILY.values()), (
    "every executor family needs a canonical extension in FAMILY_BY_EXT"
)

#: Defaults per language: 2 s and 256 MiB (262144 KiB), the judge's own defaults.
DEFAULT_TL = 2.0
DEFAULT_ML = 262144


@dataclasses.dataclass(frozen=True)
class Limits:
    """Limits for one language, in DMOJ's units."""

    time: float  # seconds
    memory: int  # KiB

    def __str__(self) -> str:  # pragma: no cover - cosmetic
        return f"tl={self.time}s ml={self.memory}KiB"


# ---------------------------------------------------------------------------
# Axes and presets
# ---------------------------------------------------------------------------

#: Semantic axes -> allowed values (the first is the default).  ``io: file`` is
#: reserved by Q16 and deliberately not implemented yet.
AXES: dict[str, tuple[str, ...]] = {
    "grader": ("standard", "signature"),
    "checker": ("none", "custom"),
    "batch": ("single", "subtasks"),
    "io": ("stdio", "file"),
    "submission": ("program", "text"),
}

#: ``executor`` is an axis too, but its legal values depend on the model and on
#: the model solution's extension, so it is validated by :func:`_check_executor`.
EXECUTOR_AXIS = "executor"

#: Axis -> explanation shown when a reserved-but-unimplemented value is used.
UNSUPPORTED_AXIS_VALUES: dict[tuple[str, str], str] = {
    ("io", "file"): "file-I/O problems are deferred (Q16); the axis is reserved "
    "so that supporting them later is a template, not a format migration",
}

#: The 8 models of Q11/Q25: preset name -> fully expanded semantic axes.
MODELS: dict[str, dict[str, str]] = {
    "standard": {
        "grader": "standard",
        "checker": "none",
        "batch": "single",
        "io": "stdio",
        "submission": "program",
    },
    "batched": {
        "grader": "standard",
        "checker": "none",
        "batch": "subtasks",
        "io": "stdio",
        "submission": "program",
    },
    "custom": {
        "grader": "standard",
        "checker": "custom",
        "batch": "single",
        "io": "stdio",
        "submission": "program",
    },
    "batched-custom": {
        "grader": "standard",
        "checker": "custom",
        "batch": "subtasks",
        "io": "stdio",
        "submission": "program",
    },
    "output-only": {
        "grader": "standard",
        "checker": "none",
        "batch": "single",
        "io": "stdio",
        "submission": "text",
    },
    "output-only-custom": {
        "grader": "standard",
        "checker": "custom",
        "batch": "single",
        "io": "stdio",
        "submission": "text",
    },
    "signature-batched": {
        "grader": "signature",
        "checker": "none",
        "batch": "subtasks",
        "io": "stdio",
        "submission": "program",
    },
    "signature-batched-custom": {
        "grader": "signature",
        "checker": "custom",
        "batch": "subtasks",
        "io": "stdio",
        "submission": "program",
    },
}


LIMITS_KEY = "limits"
MODEL_KEY = "model"
SOLUTIONLANG_KEY = "solutionlang"

#: Every key ``meta.yml`` accepts, in canonical order.
VALID_KEYS: tuple[str, ...] = (
    MODEL_KEY,
    SOLUTIONLANG_KEY,
    *AXES,
    EXECUTOR_AXIS,
    LIMITS_KEY,
)

#: Pre-toolkit spellings, for a helpful error on a stale ``meta.yml``.
RENAMED_KEYS: dict[str, str] = {"problemtype": MODEL_KEY}

#: Per-language default limits, used for any language ``limits:`` does not name.
DEFAULT_LIMITS: dict[str, Limits] = {
    ext: Limits(DEFAULT_TL, DEFAULT_ML) for ext in EXECUTOR_BY_EXT
}


#: Why a model's extension set is narrower than the full table, keyed by the
#: structural fact that narrows it -- the single place the reason is stated, so
#: the error text and the check cannot disagree.
_EXTENSION_RESTRICTIONS: tuple[tuple[tuple[str, str], tuple[str, ...], str], ...] = (
    (
        ("grader", "signature"),
        (".c", ".cpp"),
        "DMOJ's signature grader is C/C++ only",
    ),
    (
        ("submission", "text"),
        (".txt",),
        "output-only submissions are text files",
    ),
)


def extension_rules(axes: Mapping[str, str]) -> tuple[tuple[str, ...], str]:
    """Model-solution extensions a model accepts, and why.

    Returns ``(allowed, reason)``; ``reason`` is empty when the model accepts
    every language, which is the error message's parenthetical.

    Two structural facts live here rather than in a per-model table (the plan is
    explicit that neither is a gap to be closed later):

    * DMOJ's ``is_signature_gradable`` is set on the C and C++ executors only, so
      signature models take ``.c``/``.cpp``;
    * output-only submissions are run by the ``TEXT`` executor, i.e. ``.txt``.
    """
    for (axis, value), allowed, reason in _EXTENSION_RESTRICTIONS:
        if axes[axis] == value:
            return allowed, reason
    return (".c", ".cpp", ".hs", ".java", ".py"), ""


def allowed_extensions(axes: Mapping[str, str]) -> tuple[str, ...]:
    """Convenience view of :func:`extension_rules` for callers that only need the set."""
    return extension_rules(axes)[0]


# ---------------------------------------------------------------------------
# Resolution
# ---------------------------------------------------------------------------


@dataclasses.dataclass(frozen=True)
class ResolvedMeta:
    """``meta.yml`` after preset expansion and validation.

    The named predicates below are the shape queries the other subcommands ask
    of a model -- ``cases`` emits ``checker:``/``signature_grader:`` for
    :attr:`uses_checker`/:attr:`uses_signature`, ``outputs`` copies files instead
    of compiling for :attr:`is_output_only`, and the batch ladder is driven by
    :attr:`is_batched`.  They exist so callers name the fact instead of comparing
    axis strings, and so the fact is stated in one place.
    """

    model: str
    solutionlang: str
    limits: Mapping[str, Limits]
    axes: Mapping[str, str]
    overrides: Mapping[str, str]

    @property
    def executor(self) -> str:
        """DMOJ executor id used for the model solution."""
        return self.axes[EXECUTOR_AXIS]

    @property
    def solution_limits(self) -> Limits:
        """Limits for the model solution's language."""
        return self.limits[self.solutionlang]

    @property
    def uses_checker(self) -> bool:
        """The model needs a custom checker (``checker: checker.py``)."""
        return self.axes["checker"] == "custom"

    @property
    def uses_signature(self) -> bool:
        """The model is graded by ``signature_grader`` (C/C++ only)."""
        return self.axes["grader"] == "signature"

    @property
    def is_output_only(self) -> bool:
        """The submission is a text file, so expected output is produced by copy."""
        return self.axes["submission"] == "text"

    @property
    def is_batched(self) -> bool:
        """The model scores by subtask (one DMOJ batch per subtask)."""
        return self.axes["batch"] == "subtasks"

def _valid(values) -> str:
    return ", ".join(sorted(values))


def _fail(source: str, message: str) -> MetaError:
    return MetaError(f"{source}: {message}")


def _check_keys(raw: Mapping[str, Any], source: str) -> None:
    for key in raw:
        if isinstance(key, str) and key in VALID_KEYS:
            continue
        hint = ""
        if isinstance(key, str) and key in RENAMED_KEYS:
            hint = (
                f" -- this meta.yml uses the pre-toolkit format; rename it to "
                f"{RENAMED_KEYS[key]!r}"
            )
        raise _fail(source, f"unknown key {key!r}{hint}; valid keys: {_valid(VALID_KEYS)}")


def _check_extension(
    value: Any, source: str, what: str, allowed: tuple[str, ...], reason: str = ""
) -> str:
    if not isinstance(value, str):
        raise _fail(source, f"{what} must be a string, got {type(value).__name__}")
    value = value.strip()
    if value not in EXECUTOR_BY_EXT:
        hint = f" (did you mean {'.' + value!r}?)" if "." + value in EXECUTOR_BY_EXT else ""
        raise _fail(source, f"unknown {what} {value!r}{hint}; valid values: {_valid(allowed)}")
    if value not in allowed:
        detail = f" ({reason})" if reason else ""
        raise _fail(
            source,
            f"{what} {value!r} is not valid for this model{detail}; "
            f"valid values: {_valid(allowed)}",
        )
    return value


def _check_axis_values(raw: Mapping[str, Any], source: str) -> dict[str, str]:
    """Validate the semantic axis overrides (everything but ``executor``)."""
    overrides: dict[str, str] = {}
    for axis, values in AXES.items():
        if axis not in raw:
            continue
        value = raw[axis]
        if value not in values:
            raise _fail(
                source, f"unknown value {value!r} for {axis!r}; valid values: {_valid(values)}"
            )
        note = UNSUPPORTED_AXIS_VALUES.get((axis, value))
        if note is not None:
            raise _fail(source, f"{axis}: {value!r} is not supported yet -- {note}")
        overrides[axis] = value
    return overrides


def _check_executor(raw: Mapping[str, Any], source: str, solutionlang: str) -> str | None:
    """Validate an ``executor:`` override against the model solution's language."""
    executor = raw.get(EXECUTOR_AXIS)
    if executor is None:
        return None
    if not isinstance(executor, str):
        raise _fail(source, f"{EXECUTOR_AXIS} must be a string, got {type(executor).__name__}")
    executor = executor.strip()
    if executor not in EXECUTOR_FAMILY:
        raise _fail(
            source,
            f"unknown {EXECUTOR_AXIS} {executor!r}; valid values: {_valid(EXECUTOR_FAMILY)}",
        )
    family = FAMILY_BY_EXT[solutionlang]
    if EXECUTOR_FAMILY[executor] != family:
        valid = [e for e, f in EXECUTOR_FAMILY.items() if f == family]
        raise _fail(
            source,
            f"{EXECUTOR_AXIS} {executor!r} cannot run a {solutionlang} model solution; "
            f"valid executors for {solutionlang}: {_valid(valid)}",
        )
    return executor


def _check_limits(raw: Any, source: str) -> dict[str, Limits]:
    if not isinstance(raw, Mapping):
        raise _fail(source, f"{LIMITS_KEY} must be a mapping of language extension to limits")
    limits: dict[str, Limits] = {}
    for ext, block in raw.items():
        if ext not in EXECUTOR_BY_EXT:
            raise _fail(
                source,
                f"{LIMITS_KEY}: unknown language {ext!r}; valid values: {_valid(EXECUTOR_BY_EXT)}",
            )
        if not isinstance(block, Mapping):
            raise _fail(source, f"{LIMITS_KEY}[{ext}] must be a mapping with tl and ml")
        unknown = set(block) - {"tl", "ml"}
        if unknown:
            raise _fail(
                source,
                f"{LIMITS_KEY}[{ext}]: unknown key {sorted(unknown)[0]!r}; valid keys: ml, tl",
            )
        time = block.get("tl", DEFAULT_TL)
        memory = block.get("ml", DEFAULT_ML)
        if isinstance(time, bool) or not isinstance(time, (int, float)) or time <= 0:
            raise _fail(
                source,
                f"{LIMITS_KEY}[{ext}].tl must be a positive number of seconds, got {time!r}",
            )
        if isinstance(memory, bool) or not isinstance(memory, int) or memory <= 0:
            raise _fail(
                source,
                f"{LIMITS_KEY}[{ext}].ml must be a positive number of KiB, got {memory!r}",
            )
        limits[ext] = Limits(float(time), memory)
    return limits


def normalize(raw: Any, source: str = META_FILENAME) -> dict[str, Any]:
    """Validate ``raw`` and return a canonical authoring dict.

    The result holds the preset and the overrides the author wrote -- never the
    expansion, per Q5/Q10 -- in canonical key order, which is what :func:`dump`
    emits.

    Validation runs against the **effective** axes (preset plus overrides), so an
    override that contradicts the pre-existing keys is an error rather than a
    problem that silently cannot be built: ``model: standard`` with ``.py`` and
    ``grader: signature`` fails here, because DMOJ's signature grader is C/C++.
    """
    if not isinstance(raw, Mapping):
        raise _fail(source, "expected a mapping of keys at the top level")
    _check_keys(raw, source)

    model = raw.get(MODEL_KEY)
    if model is None:
        raise _fail(source, f"missing required key {MODEL_KEY!r}; valid models: {_valid(MODELS)}")
    if not isinstance(model, str) or model not in MODELS:
        raise _fail(source, f"unknown model {model!r}; valid models: {_valid(MODELS)}")

    overrides = _check_axis_values(raw, source)
    allowed, reason = extension_rules({**MODELS[model], **overrides})

    if SOLUTIONLANG_KEY not in raw:
        raise _fail(
            source,
            f"missing required key {SOLUTIONLANG_KEY!r} (e.g. {SOLUTIONLANG_KEY}: .cpp); "
            f"valid values for model {model!r}: {_valid(allowed)}",
        )
    solutionlang = _check_extension(
        raw[SOLUTIONLANG_KEY], source, SOLUTIONLANG_KEY, allowed, reason
    )

    authoring: dict[str, Any] = {MODEL_KEY: model, SOLUTIONLANG_KEY: solutionlang, **overrides}
    executor = _check_executor(raw, source, solutionlang)
    if executor is not None:
        authoring[EXECUTOR_AXIS] = executor
    if LIMITS_KEY in raw:
        authoring[LIMITS_KEY] = {
            ext: {"tl": limits.time, "ml": limits.memory}
            for ext, limits in _check_limits(raw[LIMITS_KEY], source).items()
        }
    return authoring


def resolve(raw: Any, source: str = META_FILENAME) -> ResolvedMeta:
    """Expand the preset in ``raw`` into concrete axes.

    ``raw`` is validated first, so resolution never sees a value it cannot act on.
    """
    authoring = normalize(raw, source)
    model = authoring[MODEL_KEY]
    overrides = {key: authoring[key] for key in AXES if key in authoring}
    axes = {**MODELS[model], **overrides}
    axes[EXECUTOR_AXIS] = authoring.get(EXECUTOR_AXIS) or EXECUTOR_BY_EXT[
        authoring[SOLUTIONLANG_KEY]
    ]

    limits = dict(DEFAULT_LIMITS)
    limits.update(_check_limits(authoring.get(LIMITS_KEY, {}), source))

    return ResolvedMeta(
        model=model,
        solutionlang=authoring[SOLUTIONLANG_KEY],
        limits=limits,
        axes=axes,
        overrides=overrides,
    )


# ---------------------------------------------------------------------------
# Loading and writing
# ---------------------------------------------------------------------------

#: Written at the top of every ``meta.yml`` the toolkit emits.  Kept here so the
#: file ``new`` writes and the file the ``standard`` template ships cannot drift.
HEADER = """\
# meta.yml -- intención de autoría del problema.  Es el único archivo de
# configuración que se edita a mano: init.yml se genera a partir de este.
#
#   model:        preset del problema, uno de los 8 modelos del toolkit.
#   solutionlang: extensión de la solución modelo (.c, .cpp, .hs, .java, .py
#                 y .txt en los modelos output-only).
#   limits:       límites por lenguaje, valores absolutos: tl en segundos y
#                 ml en KiB (la unidad de DMOJ).  Los lenguajes que no
#                 aparezcan usan 2 s / 262144 KiB.
#   grader, checker, batch, io, submission, executor:
#                 overrides opcionales de los ejes del preset.
#
# Los ejes expandidos no se escriben acá: `model:` más los overrides son la
# fuente de verdad y el toolkit los resuelve en cada corrida.
"""


def dump(authoring: Mapping[str, Any]) -> str:
    """Serialise an authoring dict (as returned by :func:`normalize`)."""
    body = yaml.safe_dump(dict(authoring), sort_keys=False, default_flow_style=False)
    return HEADER + body


def load(problem_dir: Path | str) -> tuple[dict[str, Any], ResolvedMeta]:
    """Read ``<problem_dir>/meta.yml``; return the authoring dict and its resolution."""
    problem_dir = Path(problem_dir)
    path = problem_dir / META_FILENAME
    if not path.is_file():
        raise MetaError(
            f"{path}: not found -- this directory is not a problemsetting problem "
            f"(scaffold one with `problemsetting new`)"
        )
    try:
        with path.open() as handle:
            raw = yaml.safe_load(handle)
    except yaml.YAMLError as error:
        # Malformed YAML is an authoring error like any other: report the file and
        # the parser's own complaint, rather than letting PyYAML's traceback escape.
        raise MetaError(f"{path}: not valid YAML: {error}") from error
    if raw is None:
        raise _fail(str(path), "the file is empty")
    return normalize(raw, str(path)), resolve(raw, str(path))


def write(problem_dir: Path | str, authoring: Mapping[str, Any]) -> Path:
    """Write the canonical ``meta.yml`` into ``problem_dir`` and return its path."""
    path = Path(problem_dir) / META_FILENAME
    path.write_text(dump(authoring))
    return path

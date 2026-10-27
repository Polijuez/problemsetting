"""``problemsetting publish``: build a problem and upload its package.

The site consumes a **package**: a zip whose entries sit at the archive root
(ADR 0003).  It carries the manifest the site reads (``problem.yml``,
``schema: 1``), the judge's ``init.yml``, the case archive that ``init.yml``
names, the statement as ``statement.md``, the optional judge files and
``media/...``.

This command runs the same build the toolkit already runs (``cases`` →
``outputs`` → ``archive``), assembles that package from the problem directory,
and uploads it.  The manifest is derived from what the author already declared:
the per-language limits and model come from ``meta.yml``, the statement from
``media/statement.md``; the human title, aliases, group and visibility are
publication data and come from the command line (or, for the token and base URL,
the environment).

Create and replace are distinct operations on the server: without ``--replace``
the package creates a problem and the site assigns its UUID; with ``--replace
<uuid>`` it replaces that problem's current package.  Nothing here parses
``meta.yml`` on the site side.
"""

from __future__ import annotations

import argparse
import dataclasses
import http
import json
import os
import re
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import yaml

from . import __version__
from . import cases
from . import judges
from . import meta as meta_mod
from .commands import Command, register
from .errors import PublishError

#: The manifest, at the package root (ADR 0003; the site's ``MANIFEST_NAME``).
MANIFEST_FILENAME = "problem.yml"

#: The statement is served from the package root, not from ``media/``.
STATEMENT_FILENAME = "statement.md"

MEDIA_DIRNAME = "media"

#: The only manifest schema this toolkit emits or understands.
SUPPORTED_SCHEMA = 1

#: Optional judge files the site accepts at the package root.  The first three
#: are the names ``cases`` emits; ``grader.py`` is accepted for problems that
#: bring their own grader even though no current model emits one.
OPTIONAL_JUDGE_FILES = (
    cases.CHECKER_FILENAME,
    "grader.py",
    cases.SIGNATURE_HEADER,
    cases.SIGNATURE_ENTRY,
)

#: Where the site lives when the author does not say otherwise.  Not a secret:
#: only the token is, and it is never printed.
DEFAULT_API_URL = "https://api.polijuez.ar"

#: The environment is the recommended way to pass the secret: a command-line
#: argument is visible to every process that can list this one's arguments.
API_URL_ENV = "POLIJUEZ_API_URL"
API_TOKEN_ENV = "POLIJUEZ_API_TOKEN"

#: The site caps a package request at 64 MB by default; bounding the response we
#: are willing to buffer keeps a misconfigured proxy from exhausting memory.
MAX_RESPONSE_BYTES = 1 << 20

#: ``ProblemAlias`` on the site: lowercase, digits, ``-`` and ``_``, up to 40.
ALIAS_RE = re.compile(r"[a-z0-9_-]{1,40}\Z")


# ---------------------------------------------------------------------------
# Manifest
# ---------------------------------------------------------------------------


def build_manifest(
    resolved: meta_mod.ResolvedMeta,
    authoring: Mapping[str, Any],
    *,
    title: str,
    group: str,
    visibility: str,
    aliases: Sequence[str] = (),
    types: Sequence[str] = (),
) -> dict[str, Any]:
    """The manifest the site reads, derived from ``meta.yml`` plus publication data.

    Only the languages ``meta.yml`` actually declares get an entry: the site
    applies each entry to every ``Language`` with that extension (ADR 0006), and
    filling in the toolkit's defaults for languages the author never mentioned
    would silently override the site's own defaults.  A problem that declares no
    limits gets its model solution's limit, so the manifest always names at least
    the language the author wrote the solution in.
    """
    title = title.strip()
    if not title:
        raise PublishError("--title must not be empty; it is the problem's name on the site")
    group = group.strip()
    if not group:
        raise PublishError("--group must not be empty; the site files every problem under one")
    visibility = visibility.strip().lower()
    if visibility not in ("public", "private"):
        raise PublishError(f"unknown visibility {visibility!r}; valid values: private, public")

    declared = authoring.get(meta_mod.LIMITS_KEY)
    if declared:
        limits = {
            extension: {
                "tl": float(block["tl"]),
                "ml": int(block["ml"]),
            }
            for extension, block in sorted(declared.items())
        }
    else:
        limits = {
            resolved.solutionlang: {
                "tl": float(resolved.solution_limits.time),
                "ml": int(resolved.solution_limits.memory),
            }
        }

    return {
        "schema": SUPPORTED_SCHEMA,
        "title": title,
        "aliases": _normalize_aliases(aliases),
        "limits": limits,
        "types": _names(types, "type"),
        "group": group,
        "visibility": visibility,
    }


def _normalize_aliases(values: Sequence[str]) -> list[str]:
    aliases: list[str] = []
    for value in values:
        alias = value.strip().lower()
        if not alias:
            raise PublishError("--alias must not be empty")
        if not ALIAS_RE.match(alias):
            raise PublishError(
                f"invalid alias {value!r}: use lowercase letters, digits, '-' and '_', "
                f"at most 40 characters"
            )
        if alias not in aliases:
            aliases.append(alias)
    return aliases


def _names(values: Sequence[str], what: str) -> list[str]:
    names: list[str] = []
    for value in values:
        name = value.strip()
        if not name:
            raise PublishError(f"--{what} must not be empty")
        if name not in names:
            names.append(name)
    return names


def render_manifest(manifest: Mapping[str, Any]) -> bytes:
    """Serialise the manifest as the UTF-8 YAML the site parses."""
    text = yaml.safe_dump(dict(manifest), sort_keys=False, allow_unicode=True)
    return text.encode("utf-8")


# ---------------------------------------------------------------------------
# Package assembly
# ---------------------------------------------------------------------------


def package_files(problem_dir: Path, manifest: Mapping[str, Any]) -> dict[str, bytes]:
    """Every package entry, by name relative to the zip root.

    The names and their placement are the site's contract: no ``meta.yml``, no
    ``cases/``, no submissions, no checksums -- only the root files it accepts and
    ``media/``.
    """
    init_path = problem_dir / cases.INIT_FILENAME
    document = cases.load_init(problem_dir)
    archive_name = cases.declared_archive(document, str(init_path))

    statement_path = problem_dir / MEDIA_DIRNAME / STATEMENT_FILENAME
    if not statement_path.is_file():
        raise PublishError(
            f"{statement_path} not found -- the site requires the statement as "
            f"statement.md at the package root"
        )
    statement = statement_path.read_bytes()
    try:
        statement.decode("utf-8")
    except UnicodeDecodeError as error:
        raise PublishError(f"{statement_path} is not valid UTF-8: {error}") from error

    archive_path = problem_dir / archive_name
    if not archive_path.is_file():
        raise PublishError(
            f"{archive_path} not found -- run `problemsetting build {problem_dir.name}` first"
        )

    files: dict[str, bytes] = {
        MANIFEST_FILENAME: render_manifest(manifest),
        cases.INIT_FILENAME: init_path.read_bytes(),
        STATEMENT_FILENAME: statement,
        archive_name: archive_path.read_bytes(),
    }

    for name in OPTIONAL_JUDGE_FILES:
        path = problem_dir / name
        if path.is_file():
            files[name] = path.read_bytes()

    media_root = problem_dir / MEDIA_DIRNAME
    if media_root.is_dir():
        for path in sorted(media_root.rglob("*")):
            if not path.is_file():
                continue
            relative = path.relative_to(media_root)
            if relative.as_posix() == STATEMENT_FILENAME:
                continue  # the statement travels at the package root
            files[f"{MEDIA_DIRNAME}/{relative.as_posix()}"] = path.read_bytes()

    return files


def assemble_package(problem_dir: Path, manifest: Mapping[str, Any]) -> bytes:
    """Write the package zip and return its bytes.

    The members are staged in a temporary directory so the package goes through
    :func:`problemsetting.cases.write_reproducible_zip`: same pinned timestamps,
    attributes, compression level and member order as the case archive, which
    makes the package a function of the problem's files and nothing else.
    """
    files = package_files(problem_dir, manifest)
    with tempfile.TemporaryDirectory(prefix="problemsetting-package-") as directory:
        root = Path(directory)
        for name, content in files.items():
            target = root / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content)
        package_path = root / "package.zip"
        cases.write_reproducible_zip(
            package_path, [(name, root / name) for name in files]
        )
        return package_path.read_bytes()


# ---------------------------------------------------------------------------
# Upload
# ---------------------------------------------------------------------------


@dataclasses.dataclass(frozen=True)
class PublishReceipt:
    """What the site reported after accepting a package."""

    problem_id: str
    url: str | None
    created: bool
    changed: bool
    cases: int
    files_written: tuple[str, ...]
    media_files: tuple[str, ...]
    aliases_added: tuple[str, ...]
    warnings: tuple[str, ...]


def api_endpoint(base_url: str, problem_id: str | None = None) -> str:
    """The create/replace URL for ``base_url``.

    ``base_url`` is the site's origin (``https://api.polijuez.ar``); a base that
    already names the API prefix is accepted too, so an explicit
    ``https://host/api/v1`` does not turn into ``/api/v1/api/v1``.
    """
    base = base_url.strip().rstrip("/")
    if not base.startswith(("http://", "https://")):
        raise PublishError(
            f"invalid API base URL {base_url!r}: it must start with http:// or https://"
        )
    if not base.endswith("/api/v1"):
        base += "/api/v1"
    endpoint = f"{base}/problems"
    if problem_id is not None:
        endpoint += "/" + urllib.parse.quote(problem_id, safe="")
    return endpoint


def upload_package(
    package: bytes,
    *,
    base_url: str,
    token: str,
    problem_id: str | None = None,
    timeout: float = 60.0,
) -> PublishReceipt:
    """POST (create) or PUT (replace) ``package`` and return the site's summary."""
    endpoint = api_endpoint(base_url, problem_id)
    request = urllib.request.Request(
        endpoint,
        data=package,
        method="PUT" if problem_id is not None else "POST",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/zip",
            "Accept": "application/json",
            "User-Agent": f"problemsetting/{__version__}",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            status = response.status
            raw = _read_response(response)
    except urllib.error.HTTPError as error:
        raise _server_error(error.code, error.reason, _read_response(error)) from error
    except urllib.error.URLError as error:
        raise PublishError(f"could not reach {endpoint}: {error.reason}") from error
    except TimeoutError as error:
        raise PublishError(f"timed out after {timeout:g}s waiting for {endpoint}") from error

    payload = _json_object(raw)
    if payload is None:
        raise PublishError(
            f"the site answered HTTP {status} with something other than a JSON "
            f"publication summary: {_excerpt(raw)}"
        )
    problem = payload.get("problem_id")
    if not isinstance(problem, str) or not problem:
        raise PublishError(
            f"the site answered HTTP {status} without a problem_id: {_excerpt(raw)}"
        )

    return PublishReceipt(
        problem_id=problem,
        url=payload.get("url") if isinstance(payload.get("url"), str) else None,
        created=payload.get("created") is True,
        changed=payload.get("changed") is True,
        cases=payload.get("cases") if isinstance(payload.get("cases"), int) else 0,
        files_written=_string_tuple(payload.get("files_written")),
        media_files=_string_tuple(payload.get("media_files")),
        aliases_added=_string_tuple(payload.get("aliases_added")),
        warnings=_string_tuple(payload.get("warnings")),
    )


def _read_response(response: Any) -> bytes:
    return response.read(MAX_RESPONSE_BYTES + 1)[:MAX_RESPONSE_BYTES]


def _json_object(raw: bytes) -> dict[str, Any] | None:
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _string_tuple(value: Any) -> tuple[str, ...]:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        return ()
    return tuple(value)


def _excerpt(raw: bytes) -> str:
    """A bounded, safe rendering of an unexpected body (never includes headers)."""
    text = raw.decode("utf-8", "replace").strip()
    if not text:
        return "(empty body)"
    return text if len(text) <= 300 else text[:300] + "..."


def _server_error(status: int, reason: str, raw: bytes) -> PublishError:
    """Turn the site's uniform error body into one actionable line.

    The API answers ``{"error": {"code": ..., "file": ..., "reason": ...}}``
    (401 for a bad token, 403 for permission, 422 for an unknown schema, 413 for
    an oversized request, 400 for an invalid package).  Surfacing code, file and
    reason keeps the author from having to read a server log.
    """
    payload = _json_object(raw)
    error = payload.get("error") if payload is not None else None
    if isinstance(error, dict) and isinstance(error.get("reason"), str):
        code = error.get("code") if isinstance(error.get("code"), str) else "error"
        file = error.get("file")
        where = f"{code} [{file}]" if isinstance(file, str) and file else code
        return PublishError(
            f"publish failed (HTTP {status}, {where}): {error['reason']}"
        )
    try:
        phrase = http.HTTPStatus(status).phrase
    except ValueError:
        phrase = reason or "error"
    detail = _excerpt(raw)
    suffix = "" if detail == "(empty body)" else f": {detail}"
    return PublishError(f"publish failed (HTTP {status} {phrase}){suffix}")


# ---------------------------------------------------------------------------
# Command
# ---------------------------------------------------------------------------


def add_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("problem", help="problem directory to build, package and publish")
    parser.add_argument(
        "--title",
        required=True,
        help="the problem's name on the site (required; the directory name is not a title)",
    )
    parser.add_argument(
        "--alias",
        action="append",
        default=[],
        metavar="NAME",
        help="human-readable alias that redirects to the problem (repeatable)",
    )
    parser.add_argument(
        "--group",
        required=True,
        help="problem group the site files it under (created if it does not exist)",
    )
    parser.add_argument(
        "--type",
        action="append",
        default=[],
        metavar="NAME",
        help="problem type, such as math or graphs (repeatable)",
    )
    parser.add_argument(
        "--visibility",
        choices=("public", "private"),
        default="private",
        help="whether the problem is visible to everyone (default: private)",
    )
    parser.add_argument(
        "--replace",
        metavar="UUID",
        default=None,
        help="replace this problem's current package instead of creating a new problem",
    )
    parser.add_argument(
        "--base-url",
        default=None,
        help=f"site origin (or {API_URL_ENV}; default: {DEFAULT_API_URL})",
    )
    parser.add_argument(
        "--token",
        default=None,
        help=f"profile API token (or {API_TOKEN_ENV}; never printed)",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=None,
        help="seed for the generator (default: the generator's own)",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=60.0,
        help="seconds to wait for the site (default: 60)",
    )


def run(args: argparse.Namespace) -> int:
    token = (args.token or os.environ.get(API_TOKEN_ENV) or "").strip()
    if not token:
        raise PublishError(
            f"no API token: pass --token or set {API_TOKEN_ENV} to your profile's "
            f"DMOJ API token"
        )
    base_url = (args.base_url or os.environ.get(API_URL_ENV) or DEFAULT_API_URL).strip()
    problem_dir = judges.resolve_problem(args.problem)

    print(f"==> build {problem_dir.name}")
    if cases.run_build(str(problem_dir), seed=args.seed) != 0:
        raise PublishError(f"build of {problem_dir.name} failed; nothing was uploaded")

    authoring, resolved = meta_mod.load(problem_dir)
    manifest = build_manifest(
        resolved,
        authoring,
        title=args.title,
        group=args.group,
        visibility=args.visibility,
        aliases=args.alias,
        types=args.type,
    )
    package = assemble_package(problem_dir, manifest)

    print(f"==> upload {problem_dir.name} ({len(package)} bytes)")
    receipt = upload_package(
        package,
        base_url=base_url,
        token=token,
        problem_id=args.replace,
        timeout=args.timeout,
    )
    _print_receipt(problem_dir.name, receipt)
    return 0


def _print_receipt(local_name: str, receipt: PublishReceipt) -> None:
    action = "created" if receipt.created else "replaced"
    state = "changed" if receipt.changed else "unchanged"
    print(f"published {local_name} -> {receipt.url or '(no URL reported)'}")
    print(f"  id        {receipt.problem_id}")
    print(f"  action    {action}, {state}")
    print(f"  cases     {receipt.cases}")
    print(f"  files     {', '.join(receipt.files_written) or '-'}")
    print(f"  media     {', '.join(receipt.media_files) or 'none'}")
    print(f"  aliases   {', '.join(receipt.aliases_added) or 'none added'}")
    for warning in receipt.warnings:
        print(f"  warning   {warning}")


register(
    Command(
        name="publish",
        help="build the problem and upload its package to the site",
        add_arguments=add_arguments,
        run=run,
    )
)

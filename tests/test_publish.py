"""``problemsetting publish``: manifest emission, package assembly and upload.

The site's contract is exercised against a local HTTP server carrying the real
zip, not a mocked client: the assertions are on the bytes that would cross the
wire and on the JSON the site answers with.  Every problem here is
``output-only``, so the build needs no compiler and the suite stays fast.
"""

from __future__ import annotations

import dataclasses
import io
import json
import textwrap
import threading
import uuid
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import pytest
import yaml

from problemsetting import cases as cases_mod
from problemsetting import cli
from problemsetting import meta as meta_mod
from problemsetting import publish as publish_mod
from problemsetting.errors import PublishError

GENERATOR = """
    class TestCase:
        def __init__(self, answer):
            self.answer = answer

        def check(self):
            pass

        def write_file(self, file):
            raise AssertionError("an output-only case has no input")

    class Generator:
        def __init__(self, seed=1):
            pass

        def get_cases(self):
            return [TestCase("answer")]

        def get_subtasks(self):
            return [(100, lambda case: True)]
"""

SUBMISSIONS = "submissions:\n  - source: solution.txt\n    verdict: AC\n"

TOKEN = "a" * 48


# ---------------------------------------------------------------------------
# A real HTTP server, on a loopback port the OS picks
# ---------------------------------------------------------------------------


@dataclasses.dataclass
class CapturedRequest:
    method: str
    path: str
    headers: dict[str, str]
    body: bytes


class _Handler(BaseHTTPRequestHandler):
    def do_POST(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler's API
        self._handle()

    def do_PUT(self) -> None:  # noqa: N802
        self._handle()

    def _handle(self) -> None:
        length = int(self.headers.get("Content-Length") or 0)
        captured = CapturedRequest(
            self.command,
            self.path,
            {key.lower(): value for key, value in self.headers.items()},
            self.rfile.read(length),
        )
        self.server.requests.append(captured)
        status, body = self.server.response
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args: Any) -> None:
        pass


@pytest.fixture
def api():
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    server.requests = []
    server.response = (201, b"{}")
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def base_url(server: ThreadingHTTPServer) -> str:
    return f"http://127.0.0.1:{server.server_address[1]}"


def respond(server: ThreadingHTTPServer, status: int, payload: dict[str, Any]) -> None:
    server.response = (status, json.dumps(payload).encode("utf-8"))


def summary(problem_id: str, **overrides: Any) -> dict[str, Any]:
    payload = {
        "problem_id": problem_id,
        "url": f"/problem/{problem_id}",
        "created": True,
        "changed": True,
        "files_written": ["demo.zip", "init.yml"],
        "media_files": ["media/figura.png"],
        "cases": 1,
        "aliases_added": ["suma"],
        "warnings": [],
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# A buildable problem, no compiler required
# ---------------------------------------------------------------------------


def write_problem(root: Path, name: str = "demo") -> Path:
    problem = root / name
    problem.mkdir(parents=True)
    authoring = {
        "model": "output-only",
        "solutionlang": ".txt",
        "limits": {".txt": {"tl": 1.0, "ml": 65536}},
    }
    meta_mod.write(problem, meta_mod.normalize(authoring, f"{name}/meta.yml"))
    (problem / cases_mod.GENERATOR_FILENAME).write_text(textwrap.dedent(GENERATOR))
    (problem / "solution.txt").write_text("answer\n")
    (problem / "submissions.yml").write_text(SUBMISSIONS)
    media = problem / "media"
    media.mkdir()
    (media / "statement.md").write_text("# Demo\n\nPublicá la respuesta.\n")
    (media / "figura.png").write_bytes(b"\x89PNG\r\n\x1a\nfake")
    return problem


def publish(argv: list[str], monkeypatch, cwd: Path) -> int:
    monkeypatch.chdir(cwd)
    return cli.main(["publish", *argv])


# ---------------------------------------------------------------------------
# The round trip
# ---------------------------------------------------------------------------


def test_publish_uploads_the_exact_package_and_reports_the_uuid(
    api, tmp_path: Path, monkeypatch, capsys
) -> None:
    problem = write_problem(tmp_path)
    problem_id = str(uuid.uuid4())
    respond(api, 201, summary(problem_id))

    status = publish(
        [
            "demo",
            "--title", "Suma de dos",
            "--alias", "suma",
            "--alias", "Suma-Vieja",
            "--group", "basico",
            "--type", "math",
            "--visibility", "public",
            "--base-url", base_url(api),
            "--token", TOKEN,
        ],
        monkeypatch,
        tmp_path,
    )

    assert status == 0
    output = capsys.readouterr().out
    assert problem_id in output
    assert "published demo" in output
    assert "created" in output

    assert len(api.requests) == 1
    request = api.requests[0]
    assert request.method == "POST"
    assert request.path == "/api/v1/problems"
    assert request.headers["authorization"] == f"Bearer {TOKEN}"
    assert request.headers["content-type"] == "application/zip"

    package = zipfile.ZipFile(io.BytesIO(request.body))
    assert set(package.namelist()) == {
        publish_mod.MANIFEST_FILENAME,
        cases_mod.INIT_FILENAME,
        publish_mod.STATEMENT_FILENAME,
        "demo.zip",
        "media/figura.png",
    }

    manifest = yaml.safe_load(package.read(publish_mod.MANIFEST_FILENAME))
    assert manifest == {
        "schema": 1,
        "title": "Suma de dos",
        "aliases": ["suma", "suma-vieja"],
        "limits": {".txt": {"tl": 1.0, "ml": 65536}},
        "types": ["math"],
        "group": "basico",
        "visibility": "public",
    }

    # The judge's files are the build's, byte for byte.
    assert package.read(cases_mod.INIT_FILENAME) == (problem / "init.yml").read_bytes()
    assert package.read("demo.zip") == (problem / "demo.zip").read_bytes()
    assert package.read(publish_mod.STATEMENT_FILENAME) == (
        problem / "media" / "statement.md"
    ).read_bytes()
    assert package.read("media/figura.png") == (problem / "media" / "figura.png").read_bytes()

    case_archive = zipfile.ZipFile(io.BytesIO(package.read("demo.zip")))
    assert case_archive.namelist() == ["cases/0.out"]
    assert case_archive.read("cases/0.out") == b"answer\n"

    # Nothing authoring-side leaks into the package.
    assert not any(
        name.startswith(("cases/", "media/statement"))
        or name in {"meta.yml", "submissions.yml", "solution.txt"}
        for name in package.namelist()
        if name != "media/figura.png"
    )


def test_replace_uses_put_on_the_problem_id(
    api, tmp_path: Path, monkeypatch, capsys
) -> None:
    write_problem(tmp_path)
    problem_id = str(uuid.uuid4())
    respond(api, 200, summary(problem_id, created=False, changed=True))

    status = publish(
        [
            "demo",
            "--title", "Suma de dos",
            "--group", "basico",
            "--replace", problem_id,
            "--base-url", base_url(api),
            "--token", TOKEN,
        ],
        monkeypatch,
        tmp_path,
    )

    assert status == 0
    request = api.requests[0]
    assert request.method == "PUT"
    assert request.path == f"/api/v1/problems/{problem_id}"
    output = capsys.readouterr().out
    assert problem_id in output
    assert "replaced" in output


def test_token_and_base_url_can_come_from_the_environment(
    api, tmp_path: Path, monkeypatch, capsys
) -> None:
    write_problem(tmp_path)
    problem_id = str(uuid.uuid4())
    respond(api, 201, summary(problem_id))
    monkeypatch.setenv(publish_mod.API_TOKEN_ENV, TOKEN)
    monkeypatch.setenv(publish_mod.API_URL_ENV, base_url(api))

    status = publish(["demo", "--title", "Suma de dos", "--group", "basico"], monkeypatch, tmp_path)

    assert status == 0
    assert api.requests[0].headers["authorization"] == f"Bearer {TOKEN}"
    assert problem_id in capsys.readouterr().out


# ---------------------------------------------------------------------------
# The site's errors are the author's error messages
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "status,payload,expected",
    [
        (
            401,
            {"error": {"code": "unauthorized", "file": None,
                       "reason": "a Bearer API token is required"}},
            ["HTTP 401", "unauthorized", "a Bearer API token is required"],
        ),
        (
            422,
            {"error": {"code": "unsupported_schema", "file": "problem.yml",
                       "reason": "unknown schema 2 (supported: 1)"}},
            ["HTTP 422", "unsupported_schema", "problem.yml", "unknown schema 2"],
        ),
        (
            413,
            {"error": {"code": "package_too_large", "file": None,
                       "reason": "the request body is 70MB, over the 64MB limit"}},
            ["HTTP 413", "package_too_large", "over the 64MB limit"],
        ),
    ],
)
def test_server_errors_are_surfaced_without_echoing_the_token(
    api, tmp_path: Path, monkeypatch, capsys, status, payload, expected
) -> None:
    write_problem(tmp_path)
    respond(api, status, payload)

    result = publish(
        [
            "demo",
            "--title", "Suma de dos",
            "--group", "basico",
            "--base-url", base_url(api),
            "--token", TOKEN,
        ],
        monkeypatch,
        tmp_path,
    )

    assert result == 1
    captured = capsys.readouterr()
    message = captured.err
    assert message.startswith("error: "), message
    for fragment in expected:
        assert fragment in message
    assert TOKEN not in message
    assert TOKEN not in captured.out


def test_a_missing_token_fails_before_building(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    problem = write_problem(tmp_path)
    monkeypatch.delenv(publish_mod.API_TOKEN_ENV, raising=False)

    result = publish(
        ["demo", "--title", "Suma de dos", "--group", "basico"],
        monkeypatch,
        tmp_path,
    )

    assert result == 1
    message = capsys.readouterr().err
    assert "no API token" in message
    assert publish_mod.API_TOKEN_ENV in message
    # The build only runs after the token is found, so nothing was built.
    assert not (problem / cases_mod.INIT_FILENAME).exists()


def test_an_unexpected_success_body_is_an_error(
    api, tmp_path: Path, monkeypatch, capsys
) -> None:
    write_problem(tmp_path)
    api.response = (201, b"<html>not the API</html>")

    result = publish(
        [
            "demo",
            "--title", "Suma de dos",
            "--group", "basico",
            "--base-url", base_url(api),
            "--token", TOKEN,
        ],
        monkeypatch,
        tmp_path,
    )

    assert result == 1
    message = capsys.readouterr().err
    assert "other than a JSON" in message
    assert "not the API" in message


# ---------------------------------------------------------------------------
# Manifest emission
# ---------------------------------------------------------------------------


def test_manifest_carries_the_declared_limits_title_and_aliases() -> None:
    authoring = meta_mod.normalize(
        {
            "model": "standard",
            "solutionlang": ".cpp",
            "limits": {
                ".cpp": {"tl": 1.5, "ml": 262144},
                ".py": {"tl": 3, "ml": 131072},
            },
        }
    )
    resolved = meta_mod.resolve(authoring)

    manifest = publish_mod.build_manifest(
        resolved,
        authoring,
        title="  Suma de dos  ",
        group=" basico ",
        visibility="PUBLIC",
        aliases=["Suma", "suma", "suma-vieja"],
        types=["math", "math"],
    )

    assert manifest["schema"] == 1
    assert manifest["title"] == "Suma de dos"
    assert manifest["group"] == "basico"
    assert manifest["visibility"] == "public"
    assert manifest["aliases"] == ["suma", "suma-vieja"]
    assert manifest["types"] == ["math"]
    assert manifest["limits"] == {
        ".cpp": {"tl": 1.5, "ml": 262144},
        ".py": {"tl": 3.0, "ml": 131072},
    }
    # The emitted bytes are the contract, not just the dict.
    assert yaml.safe_load(publish_mod.render_manifest(manifest)) == manifest


def test_a_problem_without_limits_gets_its_solution_languages_default() -> None:
    authoring = meta_mod.normalize({"model": "standard", "solutionlang": ".cpp"})
    resolved = meta_mod.resolve(authoring)

    manifest = publish_mod.build_manifest(
        resolved,
        authoring,
        title="Suma",
        group="basico",
        visibility="private",
    )

    assert manifest["limits"] == {
        ".cpp": {
            "tl": meta_mod.DEFAULT_TL,
            "ml": meta_mod.DEFAULT_ML,
        }
    }
    assert manifest["aliases"] == []
    assert manifest["types"] == []


@pytest.mark.parametrize("alias", ["", "con espacio", "a" * 41, "ñandú"])
def test_invalid_aliases_are_refused(alias: str) -> None:
    authoring = meta_mod.normalize({"model": "standard", "solutionlang": ".cpp"})
    with pytest.raises(PublishError, match="alias"):
        publish_mod.build_manifest(
            meta_mod.resolve(authoring),
            authoring,
            title="Suma",
            group="basico",
            visibility="private",
            aliases=[alias],
        )


# ---------------------------------------------------------------------------
# Package assembly, including the optional judge files
# ---------------------------------------------------------------------------


def _write_synthetic_problem(root: Path) -> Path:
    problem = root / "sintetico"
    (problem / "media" / "sub").mkdir(parents=True)
    (problem / cases_mod.INIT_FILENAME).write_text(
        "archive: data.zip\n"
        "checker: checker.py\n"
        "signature_grader: {entry: evaluator.cpp, header: signature.hpp}\n"
        "test_cases:\n"
        "- points: 100\n"
        "  in: 1.in\n"
        "  out: 1.out\n"
    )
    with zipfile.ZipFile(problem / "data.zip", "w") as archive:
        archive.writestr("1.in", "1 2\n")
        archive.writestr("1.out", "3\n")
    (problem / "media" / "statement.md").write_text("# Enunciado\n")
    (problem / "media" / "sub" / "figura.png").write_bytes(b"png")
    for name, content in {
        "checker.py": b"# checker\n",
        "grader.py": b"# grader\n",
        "signature.hpp": b"#pragma once\n",
        "evaluator.cpp": b"int main() {}\n",
    }.items():
        (problem / name).write_bytes(content)
    return problem


def test_package_puts_every_server_entry_at_the_root(tmp_path: Path) -> None:
    problem = _write_synthetic_problem(tmp_path)
    manifest = {
        "schema": 1,
        "title": "Sintético",
        "aliases": [],
        "limits": {".cpp": {"tl": 1.0, "ml": 262144}},
        "types": [],
        "group": "basico",
        "visibility": "private",
    }

    files = publish_mod.package_files(problem, manifest)

    assert set(files) == {
        "problem.yml",
        "init.yml",
        "statement.md",
        "data.zip",
        "checker.py",
        "grader.py",
        "signature.hpp",
        "evaluator.cpp",
        "media/sub/figura.png",
    }
    assert files["statement.md"] == b"# Enunciado\n"
    assert files["media/sub/figura.png"] == b"png"
    assert "media/statement.md" not in files

    package = zipfile.ZipFile(io.BytesIO(publish_mod.assemble_package(problem, manifest)))
    assert set(package.namelist()) == set(files)
    # Same inputs, same bytes: the package is reproducible like the case archive.
    assert publish_mod.assemble_package(problem, manifest) == publish_mod.assemble_package(
        problem, manifest
    )


def test_a_missing_statement_is_refused_before_upload(tmp_path: Path) -> None:
    problem = _write_synthetic_problem(tmp_path)
    (problem / "media" / "statement.md").unlink()
    manifest = {
        "schema": 1,
        "title": "Sintético",
        "aliases": [],
        "limits": {},
        "types": [],
        "group": "basico",
        "visibility": "private",
    }

    with pytest.raises(PublishError, match="statement.md"):
        publish_mod.package_files(problem, manifest)


# ---------------------------------------------------------------------------
# URL construction
# ---------------------------------------------------------------------------


def test_a_base_that_already_names_the_api_prefix_is_not_doubled() -> None:
    assert (
        publish_mod.api_endpoint("https://api.example/api/v1/")
        == "https://api.example/api/v1/problems"
    )
    assert (
        publish_mod.api_endpoint("https://api.example", "abc")
        == "https://api.example/api/v1/problems/abc"
    )


def test_a_base_without_a_scheme_is_refused() -> None:
    with pytest.raises(PublishError, match="http"):
        publish_mod.api_endpoint("api.example")

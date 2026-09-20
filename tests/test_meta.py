"""``meta.yml`` schema and preset → axis resolution."""

from __future__ import annotations

import pytest

from problemsetting import meta
from problemsetting.errors import MetaError


def test_preset_expands_to_axes() -> None:
    resolved = meta.resolve({"model": "standard", "solutionlang": ".cpp"})
    assert resolved.axes == {
        "grader": "standard",
        "checker": "none",
        "batch": "single",
        "io": "stdio",
        "submission": "program",
        "executor": "CPP17",
    }
    # Presets are never stored expanded: with no overrides written, there is
    # nothing to report as an override.
    assert resolved.overrides == {}
    assert resolved.executor == "CPP17"


@pytest.mark.parametrize(
    ("model", "expected"),
    [
        ("standard", {"grader": "standard", "checker": "none", "batch": "single"}),
        ("batched", {"grader": "standard", "checker": "none", "batch": "subtasks"}),
        ("custom", {"grader": "standard", "checker": "custom", "batch": "single"}),
        ("batched-custom", {"grader": "standard", "checker": "custom", "batch": "subtasks"}),
        ("output-only", {"grader": "standard", "checker": "none", "submission": "text"}),
        ("output-only-custom", {"checker": "custom", "submission": "text"}),
        ("signature-batched", {"grader": "signature", "batch": "subtasks"}),
        ("signature-batched-custom", {"grader": "signature", "checker": "custom"}),
    ],
)
def test_every_model_preset_resolves(model: str, expected: dict[str, str]) -> None:
    solutionlang = ".txt" if meta.MODELS[model]["submission"] == "text" else ".cpp"
    resolved = meta.resolve({"model": model, "solutionlang": solutionlang})
    for axis, value in expected.items():
        assert resolved.axes[axis] == value, axis
    assert meta.allowed_extensions(
        {**meta.MODELS[model], **{k: v for k, v in expected.items()}}
    )


def test_axis_override_wins_over_preset() -> None:
    resolved = meta.resolve(
        {"model": "batched", "solutionlang": ".cpp", "checker": "custom"}
    )
    assert resolved.axes["checker"] == "custom"
    assert resolved.overrides == {"checker": "custom"}
    # The preset's other axes survive the override.
    assert resolved.axes["batch"] == "subtasks"
    assert resolved.model == "batched"


def test_executor_override_selects_the_executor() -> None:
    resolved = meta.resolve(
        {"model": "standard", "solutionlang": ".cpp", "executor": "CPP20"}
    )
    assert resolved.executor == "CPP20"
    # The executor is an axis but not a semantic one, so it is not an "override"
    # of the preset (no preset names an executor).
    assert resolved.overrides == {}


def test_normalize_never_writes_the_expansion() -> None:
    authoring = meta.normalize({"model": "batched", "solutionlang": ".py"})
    assert authoring == {"model": "batched", "solutionlang": ".py"}
    assert "grader" not in authoring and "batch" not in authoring
    dumped = meta.dump(authoring)
    assert "model: batched" in dumped
    assert "grader:" not in dumped


def test_limits_are_absolute_in_kib() -> None:
    resolved = meta.resolve(
        {
            "model": "standard",
            "solutionlang": ".java",
            "limits": {".java": {"tl": 4.0, "ml": 524288}},
        }
    )
    assert resolved.limits[".java"] == meta.Limits(4.0, 524288)
    # Unlisted languages fall back to the judge's own defaults.
    assert resolved.limits[".cpp"] == meta.Limits(meta.DEFAULT_TL, meta.DEFAULT_ML)
    assert resolved.solution_limits == meta.Limits(4.0, 524288)


def test_limits_round_trip_through_the_authoring_dict() -> None:
    raw = {
        "model": "standard",
        "solutionlang": ".cpp",
        "limits": {".cpp": {"tl": 1.0, "ml": 262144}},
    }
    authoring = meta.normalize(raw)
    assert authoring["limits"] == {".cpp": {"tl": 1.0, "ml": 262144}}
    assert meta.resolve(authoring).solution_limits == meta.Limits(1.0, 262144)


# ---------------------------------------------------------------------------
# Errors: each must name the offending value and the valid alternatives.
# ---------------------------------------------------------------------------


def test_unknown_model_lists_models() -> None:
    with pytest.raises(MetaError) as excinfo:
        meta.resolve({"model": "wat", "solutionlang": ".cpp"})
    message = str(excinfo.value)
    assert "'wat'" in message
    assert "batched-custom" in message


def test_missing_model_is_rejected() -> None:
    with pytest.raises(MetaError, match="missing required key 'model'"):
        meta.resolve({"solutionlang": ".cpp"})


def test_unknown_language_lists_languages() -> None:
    with pytest.raises(MetaError) as excinfo:
        meta.resolve({"model": "standard", "solutionlang": ".rs"})
    message = str(excinfo.value)
    assert "'.rs'" in message
    assert ".cpp" in message


def test_language_not_valid_for_model_names_the_valid_set() -> None:
    with pytest.raises(MetaError, match="signature grader is C/C\\+\\+ only"):
        meta.resolve({"model": "signature-batched", "solutionlang": ".java"})
    with pytest.raises(MetaError, match="output-only submissions are text files"):
        meta.resolve({"model": "output-only", "solutionlang": ".cpp"})


def test_unknown_axis_value_lists_alternatives() -> None:
    with pytest.raises(MetaError, match="unknown value 'worse'"):
        meta.resolve({"model": "standard", "solutionlang": ".cpp", "checker": "worse"})


def test_reserved_axis_value_says_it_is_not_supported() -> None:
    with pytest.raises(MetaError, match="not supported yet"):
        meta.resolve({"model": "standard", "solutionlang": ".cpp", "io": "file"})


def test_mismatched_executor_override_is_rejected() -> None:
    with pytest.raises(MetaError, match="cannot run a .cpp model solution"):
        meta.resolve({"model": "standard", "solutionlang": ".cpp", "executor": "PY3"})


def test_override_contradicting_the_solution_language_is_rejected() -> None:
    # grader: signature makes the model C/C++-only, so a Python model solution
    # cannot coexist with it.
    with pytest.raises(MetaError, match="signature grader is C/C\\+\\+ only"):
        meta.resolve({"model": "standard", "solutionlang": ".py", "grader": "signature"})


def test_pre_toolkit_key_is_named_in_the_error() -> None:
    with pytest.raises(MetaError, match="problemtype"):
        meta.resolve({"problemtype": "standard", "solutionlang": ".cpp"})


def test_unknown_key_lists_valid_keys() -> None:
    with pytest.raises(MetaError) as excinfo:
        meta.resolve({"model": "standard", "solutionlang": ".cpp", "languages": ["cpp17"]})
    assert "languages" in str(excinfo.value)
    assert "valid keys" in str(excinfo.value)


@pytest.mark.parametrize(
    "raw",
    [
        {"model": "standard", "solutionlang": ".cpp", "limits": {".cpp": {"tl": 0}}},
        {"model": "standard", "solutionlang": ".cpp", "limits": {".cpp": {"ml": -1}}},
        {"model": "standard", "solutionlang": ".cpp", "limits": {".cpp": {"tl": "2"}}},
        {"model": "standard", "solutionlang": ".cpp", "limits": {".cpp": {"seconds": 2}}},
        {"model": "standard", "solutionlang": ".cpp", "limits": {".rs": {"tl": 2}}},
    ],
)
def test_malformed_limits_are_rejected(raw: dict) -> None:
    with pytest.raises(MetaError):
        meta.resolve(raw)


def test_load_reports_a_missing_meta_yml(tmp_path) -> None:
    with pytest.raises(MetaError) as excinfo:
        meta.load(tmp_path)
    assert "meta.yml" in str(excinfo.value)


def test_load_reads_and_resolves(tmp_path) -> None:
    (tmp_path / "meta.yml").write_text("model: standard\nsolutionlang: .cpp\n")
    authoring, resolved = meta.load(tmp_path)
    assert authoring == {"model": "standard", "solutionlang": ".cpp"}
    assert resolved.executor == "CPP17"


def test_write_and_load_round_trip(tmp_path) -> None:
    meta.write(tmp_path, meta.normalize({"model": "custom", "solutionlang": ".cpp"}))
    authoring, resolved = meta.load(tmp_path)
    assert resolved.model == "custom"
    assert resolved.uses_checker
    assert not resolved.is_batched
    assert "model: custom" in (tmp_path / "meta.yml").read_text()

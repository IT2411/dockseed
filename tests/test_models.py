"""Phase 0 tests for core domain models and exceptions."""

import json
from pathlib import Path

import pytest

from dockseed.exceptions import (
    AmbiguityError,
    DockseedError,
    ExitCode,
    OverwriteBlockedError,
    ValidationError,
)
from dockseed.models import (
    CLIOverrides,
    ConfidenceLevel,
    Detection,
    Evidence,
    Framework,
    GenerationResult,
    PackageManager,
    ProjectModel,
)


def test_evidence_immutability_and_sorting() -> None:
    ev1 = Evidence(
        source="pyproject.toml",
        detector="python_version",
        description="Found requires-python >= 3.11",
        confidence=ConfidenceLevel.HIGH,
    )
    ev2 = Evidence(
        source=".python-version",
        detector="python_version",
        description="Found 3.12",
        confidence=ConfidenceLevel.HIGH,
    )

    with pytest.raises(AttributeError):
        ev1.source = "modified"  # type: ignore[misc]

    detection: Detection[str] = Detection(value="3.12", confidence=ConfidenceLevel.HIGH)
    detection.add_evidence(
        source=ev1.source,
        detector=ev1.detector,
        description=ev1.description,
        confidence=ev1.confidence,
    )
    detection.add_evidence(
        source=ev2.source,
        detector=ev2.detector,
        description=ev2.description,
        confidence=ev2.confidence,
    )
    # Adding duplicate evidence should be ignored
    detection.add_evidence(
        source=ev1.source,
        detector=ev1.detector,
        description=ev1.description,
        confidence=ev1.confidence,
    )

    assert len(detection.evidence) == 2
    # ".python-version" sorts lexicographically before "pyproject.toml"
    assert detection.evidence[0].source == ".python-version"
    assert detection.evidence[1].source == "pyproject.toml"


def test_project_model_deterministic_serialization() -> None:
    model = ProjectModel(root=Path("/tmp/my-app"))
    model.python_requirement = Detection(value=">=3.11", confidence=ConfidenceLevel.HIGH)
    model.resolved_python_version = Detection(value="3.12", confidence=ConfidenceLevel.HIGH)
    model.package_manager = Detection(
        value=PackageManager.UV,
        confidence=ConfidenceLevel.HIGH,
        candidates=[PackageManager.UV, PackageManager.PIP],
    )
    model.framework = Detection(value=Framework.FASTAPI, confidence=ConfidenceLevel.HIGH)
    model.entry_point = Detection(
        value=["uvicorn", "app.main:app"], confidence=ConfidenceLevel.HIGH
    )
    model.runtime_dependencies = ["uvicorn", "fastapi", "fastapi"]
    model.system_dependencies = ["gcc", "libpq-dev", "gcc"]
    model.ports = [8000, 8000]
    model.warnings = ["Sample warning"]

    data = model.to_dict()
    assert data["root"] == str(Path("/tmp/my-app"))
    assert data["package_manager"]["value"] == "uv"
    assert data["package_manager"]["candidates"] == ["uv", "pip"]
    assert data["framework"]["value"] == "fastapi"
    assert data["runtime_dependencies"] == ["fastapi", "uvicorn"]
    assert data["system_dependencies"] == ["gcc", "libpq-dev"]
    assert data["ports"] == [8000]

    # Verify JSON serializability
    serialized = json.dumps(data, sort_keys=True)
    assert '"value": "uv"' in serialized


def test_cli_overrides_and_generation_result() -> None:
    overrides = CLIOverrides(
        python_version="3.12",
        package_manager=PackageManager.POETRY,
        entrypoint="app.main:app",
        port=8080,
    )
    assert overrides.python_version == "3.12"
    assert overrides.package_manager == PackageManager.POETRY

    res = GenerationResult(content="FROM python:3.12-slim\n", assumptions=["Assumed port 8000"])
    assert "FROM python:3.12-slim" in res.content
    assert len(res.assumptions) == 1


def test_exceptions_exit_codes() -> None:
    err_general = DockseedError("General failure")
    assert err_general.exit_code == ExitCode.GENERAL_ERROR

    err_custom = DockseedError("Custom failure", exit_code=ExitCode.VALIDATION_FAILED)
    assert err_custom.exit_code == ExitCode.VALIDATION_FAILED

    err_val = ValidationError("Invalid Dockerfile")
    assert err_val.exit_code == ExitCode.VALIDATION_FAILED

    err_amb = AmbiguityError("Multiple entrypoints found")
    assert err_amb.exit_code == ExitCode.AMBIGUITY_UNRESOLVED

    err_ovw = OverwriteBlockedError("Dockerfile already exists")
    assert err_ovw.exit_code == ExitCode.OVERWRITE_BLOCKED

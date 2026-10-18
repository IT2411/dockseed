"""Phase 5 (Environment inspection) and Phase 6 (Build validation) unit tests."""

import subprocess
from pathlib import Path

import pytest

from dockseed.cli import main
from dockseed.exceptions import ExitCode, ValidationError
from dockseed.inference import scan_project
from dockseed.validators import resolve_container_runtime, run_build_validation


def test_environment_inspection_detects_undeclared_packages(tmp_path: Path) -> None:
    # Create a project that declares only fastapi in requirements.txt
    (tmp_path / "requirements.txt").write_text("fastapi\n", encoding="utf-8")
    (tmp_path / "main.py").write_text(
        "from fastapi import FastAPI\napp = FastAPI()\n", encoding="utf-8"
    )

    # Create a fake local .venv containing uvicorn (critical) and pytest (dev/incidental)
    sp = tmp_path / ".venv" / "lib" / "python3.11" / "site-packages"
    uv_dist = sp / "uvicorn-0.30.0.dist-info"
    uv_dist.mkdir(parents=True)
    (uv_dist / "METADATA").write_text("Metadata-Version: 2.1\nName: uvicorn\n", encoding="utf-8")

    # Also test dist-info without METADATA file (fallback to folder name) and Windows Lib path
    win_sp = tmp_path / "venv" / "Lib" / "site-packages"
    pytest_dist = win_sp / "pytest-8.0.0.dist-info"
    pytest_dist.mkdir(parents=True)
    redis_dist = win_sp / "redis-5.0.0.dist-info"
    redis_dist.mkdir(parents=True)

    model = scan_project(tmp_path)

    # Incidental dev package (pytest) is never added to runtime_dependencies or warnings
    assert "pytest" not in model.runtime_dependencies
    assert "uvicorn" not in model.runtime_dependencies
    assert any("missing from project manifests: redis, uvicorn" in w for w in model.warnings)


def test_resolve_container_runtime_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(ValidationError, match="Unsupported container runtime"):
        resolve_container_runtime("invalid_runtime")

    monkeypatch.setattr("shutil.which", lambda _: None)
    with pytest.raises(ValidationError, match="was not found on PATH"):
        resolve_container_runtime("podman")

    with pytest.raises(ValidationError, match="No supported container CLI"):
        resolve_container_runtime(None)


def test_check_build_subprocess_safety_and_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "requirements.txt").write_text("fastapi\nuvicorn\n", encoding="utf-8")
    (tmp_path / "main.py").write_text(
        "from fastapi import FastAPI\napp = FastAPI()\n", encoding="utf-8"
    )
    assert main(["init", "--path", str(tmp_path), "--yes"]) == int(ExitCode.SUCCESS)

    monkeypatch.setattr("shutil.which", lambda name: f"/usr/bin/{name}")

    recorded_calls: list[tuple[list[str], bool]] = []

    def fake_run_success(
        cmd: list[str],
        capture_output: bool = False,
        text: bool = False,
        shell: bool = False,
        check: bool = False,
    ) -> subprocess.CompletedProcess[str]:
        recorded_calls.append((cmd, shell))
        return subprocess.CompletedProcess(cmd, returncode=0, stdout="OK", stderr="")

    monkeypatch.setattr("subprocess.run", fake_run_success)

    code = main(["check", str(tmp_path), "--build", "--runtime", "podman"])
    assert code == int(ExitCode.SUCCESS)
    assert len(recorded_calls) == 2
    assert recorded_calls[0][0][0] == "/usr/bin/podman"
    assert recorded_calls[0][0][1] == "build"
    # Verify shell=False is strictly enforced
    assert recorded_calls[0][1] is False
    assert recorded_calls[1][0][1] == "rmi"
    assert recorded_calls[1][1] is False

    # Simulate build failure (returncode != 0)
    def fake_run_fail(
        cmd: list[str],
        capture_output: bool = False,
        text: bool = False,
        shell: bool = False,
        check: bool = False,
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(cmd, returncode=1, stdout="", stderr="STEP 2: failed")

    monkeypatch.setattr("subprocess.run", fake_run_fail)
    with pytest.raises(ValidationError, match="Container image build failed"):
        run_build_validation(tmp_path)

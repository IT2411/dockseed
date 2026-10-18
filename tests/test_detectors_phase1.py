"""Phase 1 unit tests for Python version, package manager, and native dependency detectors."""

from pathlib import Path

import pytest

from dockseed.detectors import (
    detect_native_dependencies,
    detect_package_manager,
    detect_python_version,
)
from dockseed.detectors.python_version import resolve_compatible_version
from dockseed.exceptions import ValidationError
from dockseed.models import CLIOverrides, ConfidenceLevel, PackageManager, ProjectModel
from dockseed.scanner import discover_project


def test_python_version_spec_operators() -> None:
    assert resolve_compatible_version("*") == ["3.10", "3.11", "3.12", "3.13", "3.14"]
    assert resolve_compatible_version(">3.10,<=3.13,!=3.12") == ["3.11", "3.13"]
    assert resolve_compatible_version("~=3.11.0") == ["3.11"]


def test_python_version_cli_override(tmp_path: Path) -> None:
    ctx = discover_project(tmp_path)
    model = ProjectModel(root=ctx.root)

    detect_python_version(ctx, model, CLIOverrides(python_version="3.13"))
    assert model.resolved_python_version.value == "3.13"
    assert model.resolved_python_version.confidence == ConfidenceLevel.HIGH

    with pytest.raises(ValidationError, match="Invalid Python version"):
        detect_python_version(ctx, model, CLIOverrides(python_version="invalid"))

    with pytest.raises(ValidationError, match="Unsupported Python version"):
        detect_python_version(ctx, model, CLIOverrides(python_version="2.7"))


def test_python_version_resolution_and_conflicts(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "demo"\nrequires-python = ">=3.11,<3.14"\n'
        '[tool.poetry.dependencies]\npython = "^3.11"\n',
        encoding="utf-8",
    )
    (tmp_path / ".python-version").write_text("3.12.4\n", encoding="utf-8")

    ctx = discover_project(tmp_path)
    model = ProjectModel(root=ctx.root)
    detect_python_version(ctx, model)

    assert model.python_requirement.value == ">=3.11,<3.14"
    assert model.resolved_python_version.value == "3.12"
    assert model.resolved_python_version.confidence == ConfidenceLevel.HIGH
    assert not model.python_requirement.conflicts


def test_python_version_non_312_range_and_conflicts(tmp_path: Path) -> None:
    # Range that excludes 3.12 (e.g., >=3.10,<=3.11) chooses highest compatible (3.11)
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nrequires-python = ">=3.10,<=3.11"\n', encoding="utf-8"
    )
    ctx_range = discover_project(tmp_path)
    model_range = ProjectModel(root=ctx_range.root)
    detect_python_version(ctx_range, model_range)
    assert model_range.resolved_python_version.value == "3.11"
    assert model_range.resolved_python_version.confidence == ConfidenceLevel.MEDIUM

    # Conflicting .python-version vs pyproject.toml
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nrequires-python = "==3.11.*"\n', encoding="utf-8"
    )
    (tmp_path / ".python-version").write_text("3.13\n", encoding="utf-8")

    ctx = discover_project(tmp_path)
    model = ProjectModel(root=ctx.root)
    detect_python_version(ctx, model)

    assert len(model.python_requirement.conflicts) == 1
    assert model.resolved_python_version.value == "3.11"

    # Incompatible Python constraint (e.g. <3.9)
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nrequires-python = ">=3.7,<3.9"\n', encoding="utf-8"
    )
    ctx_bad = discover_project(tmp_path)
    with pytest.raises(ValidationError, match="incompatible with supported versions"):
        detect_python_version(ctx_bad, ProjectModel(root=ctx_bad.root))


def test_python_version_tool_versions_runtime_pipfile_and_fallback(tmp_path: Path) -> None:
    # Empty project -> fallback to active interpreter
    ctx_empty = discover_project(tmp_path)
    model_empty = ProjectModel(root=ctx_empty.root)
    detect_python_version(ctx_empty, model_empty)
    assert model_empty.resolved_python_version.confidence == ConfidenceLevel.LOW
    assert model_empty.resolved_python_version.value is not None

    # .tool-versions, runtime.txt, and tilde constraint
    (tmp_path / ".tool-versions").write_text("nodejs 20.0.0\npython ~3.11.0\n", encoding="utf-8")
    (tmp_path / "runtime.txt").write_text("python-3.11.8\n", encoding="utf-8")
    (tmp_path / "Pipfile").write_text('[requires]\npython_version = "3.11"\n', encoding="utf-8")

    ctx = discover_project(tmp_path)
    model = ProjectModel(root=ctx.root)
    detect_python_version(ctx, model)
    assert model.resolved_python_version.value == "3.11"


def test_package_manager_detection_and_conflicts(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "app"\ndependencies = ["fastapi>=0.110.0", "uvicorn[standard]", "git+https://github.com/org/p.git"]\n'
        '[tool.poetry.dependencies]\npython = "^3.11"\npsycopg2 = "^2.9"\n'
        'local_pkg = {path = "../outside_pkg"}\n'
        'git_pkg = {git = "https://github.com/org/repo.git"}\n',
        encoding="utf-8",
    )
    (tmp_path / "poetry.lock").write_text("# lock\n", encoding="utf-8")
    (tmp_path / "requirements.txt").write_text(
        "# comment\n-r requirements/extra.txt\n-r ../outside_reqs.txt\n--index-url https://pypi.org/simple\nredis>=5.0\n",
        encoding="utf-8",
    )
    (tmp_path / "requirements").mkdir()
    # Include circular -r to test visited protection
    (tmp_path / "requirements" / "extra.txt").write_text(
        "-r requirements.txt\ncelery==5.4.0\ngit+https://github.com/org/repo.git\n",
        encoding="utf-8",
    )

    ctx = discover_project(tmp_path)
    model = ProjectModel(root=ctx.root)
    detect_package_manager(ctx, model)
    detect_native_dependencies(model)

    assert model.package_manager.value == PackageManager.POETRY
    assert len(model.package_manager.conflicts) == 1
    assert "fastapi" in model.runtime_dependencies
    assert "uvicorn" in model.runtime_dependencies
    assert "psycopg2" in model.runtime_dependencies
    assert "celery" in model.runtime_dependencies
    assert "git+https" in model.runtime_dependencies
    assert any("outside build context" in b for b in model.blockers)

    # Native dependencies populated for psycopg2 and git+https
    assert model.system_dependencies == ["gcc", "git", "libpq-dev"]
    assert any("psycopg2-binary" in w for w in model.warnings)


def test_package_manager_uv_pdm_hatch_pipenv_and_empty(tmp_path: Path) -> None:
    # 1. Empty directory defaults to PIP with LOW confidence
    ctx_empty = discover_project(tmp_path)
    model_empty = ProjectModel(root=ctx_empty.root)
    detect_package_manager(ctx_empty, model_empty)
    assert model_empty.package_manager.value == PackageManager.PIP
    assert model_empty.package_manager.confidence == ConfidenceLevel.LOW

    # 2. PEP 621 only project -> PIP with MEDIUM confidence
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "pep621-app"\ndependencies = ["flask"]\n', encoding="utf-8"
    )
    ctx_pep = discover_project(tmp_path)
    model_pep = ProjectModel(root=ctx_pep.root)
    detect_package_manager(ctx_pep, model_pep)
    assert model_pep.package_manager.value == PackageManager.PIP
    assert model_pep.package_manager.confidence == ConfidenceLevel.MEDIUM

    # 3. Tool sections for uv, pdm, hatch, poetry (without lockfiles) + Pipfile.lock + pdm.lock
    (tmp_path / "pyproject.toml").write_text(
        "[tool.uv]\n[tool.pdm]\n[tool.hatch]\n[tool.poetry]\n", encoding="utf-8"
    )
    (tmp_path / "hatch.toml").write_text("[envs.default]\n", encoding="utf-8")
    ctx_tools = discover_project(tmp_path)
    model_tools = ProjectModel(root=ctx_tools.root)
    detect_package_manager(ctx_tools, model_tools)
    assert PackageManager.UV in model_tools.package_manager.candidates
    assert PackageManager.PDM in model_tools.package_manager.candidates
    assert PackageManager.HATCH in model_tools.package_manager.candidates
    assert PackageManager.POETRY in model_tools.package_manager.candidates

    # 4. Lockfiles for PDM and Pipenv
    (tmp_path / "pdm.lock").write_text("# pdm\n", encoding="utf-8")
    (tmp_path / "Pipfile.lock").write_text("{}\n", encoding="utf-8")
    (tmp_path / "Pipfile").write_text(
        '[packages]\nflask = "*"\nprivate_pkg = {git = "git+ssh://git@github.com/org/priv.git"}\n'
        'pub_git = {git = "https://github.com/org/pub.git"}\n',
        encoding="utf-8",
    )
    ctx_locks = discover_project(tmp_path)
    model_locks = ProjectModel(root=ctx_locks.root)
    detect_package_manager(ctx_locks, model_locks)
    assert model_locks.package_manager.value == PackageManager.PDM
    assert "git+https" in model_locks.runtime_dependencies
    assert any("SSH Git dependency" in b for b in model_locks.blockers)

    # 5. Explicit override
    model_ovr = ProjectModel(root=ctx_locks.root)
    detect_package_manager(
        ctx_locks, model_ovr, CLIOverrides(package_manager=PackageManager.PIPENV)
    )
    assert model_ovr.package_manager.value == PackageManager.PIPENV

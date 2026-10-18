"""Detector for Python package managers, runtime dependencies, and path/SSH blockers."""

import re
from typing import Any

from dockseed.models import (
    CLIOverrides,
    ConfidenceLevel,
    PackageManager,
    ProjectModel,
)
from dockseed.scanner import ScanContext

REQ_NAME_RE = re.compile(r"^([A-Za-z0-9][A-Za-z0-9._-]*)")


def normalize_pkg_name(name: str) -> str:
    """Normalize a PEP 503 package name to lowercase with hyphens."""
    return re.sub(r"[-_.]+", "-", name.strip()).lower()


def _check_dependency_blocker(raw_spec: str, source: str, model: ProjectModel) -> None:
    """Check a dependency line or specification for containerization blockers."""
    spec = raw_spec.strip()
    if "git+ssh://" in spec or "ssh://git@" in spec or spec.startswith("git@"):
        msg = (
            f"Private SSH Git dependency in {source} ('{spec}') requires SSH keys "
            "during container build."
        )
        if msg not in model.blockers:
            model.blockers.append(msg)

    # Check out-of-context relative paths like ../shared or -e ../foo
    cleaned = re.sub(r"^(?:-e|--editable)\s+", "", spec).strip()
    if cleaned.startswith("../") or cleaned.startswith("..\\") or "/../" in cleaned:
        msg = (
            f"Local path dependency outside build context in {source} ('{spec}') "
            "cannot be accessed by Docker build."
        )
        if msg not in model.blockers:
            model.blockers.append(msg)


def _extract_req_txt_deps(
    ctx: ScanContext, rel_path: str, model: ProjectModel, visited: set[str] | None = None
) -> list[str]:
    """Parse a requirements.txt file and extract normalized package names."""
    if visited is None:
        visited = set()
    if rel_path in visited:
        return []
    visited.add(rel_path)

    content = ctx.read_text_safe(rel_path)
    if not content:
        return []

    deps: list[str] = []
    for raw_line in content.splitlines():
        line = raw_line.split("#", 1)[0].strip()
        if not line:
            continue

        # Handle nested -r / --requirement includes
        if line.startswith(("-r ", "--requirement ")):
            parts = line.split(maxsplit=1)
            if len(parts) == 2:
                inc_path = parts[1].strip()
                if not inc_path.startswith("../") and ctx.has_file(inc_path):
                    deps.extend(_extract_req_txt_deps(ctx, inc_path, model, visited))
                else:
                    _check_dependency_blocker(line, rel_path, model)
            continue

        _check_dependency_blocker(line, rel_path, model)

        if line.startswith("-"):
            continue

        if "git+https://" in line or "git+http://" in line:
            deps.append("git+https")
            continue

        match = REQ_NAME_RE.match(line)
        if match:
            deps.append(normalize_pkg_name(match.group(1)))

    return deps


def _extract_pep621_deps(pyproject: dict[str, Any], model: ProjectModel) -> list[str]:
    """Extract dependencies from [project.dependencies] in pyproject.toml."""
    project_sec = pyproject.get("project", {})
    if not isinstance(project_sec, dict):
        return []
    raw_deps = project_sec.get("dependencies", [])
    if not isinstance(raw_deps, list):
        return []

    deps: list[str] = []
    for item in raw_deps:
        if not isinstance(item, str):
            continue
        _check_dependency_blocker(item, "pyproject.toml", model)
        if "git+https://" in item or "git+http://" in item:
            deps.append("git+https")
        match = REQ_NAME_RE.match(item.strip())
        if match:
            deps.append(normalize_pkg_name(match.group(1)))
    return deps


def _extract_poetry_deps(pyproject: dict[str, Any], model: ProjectModel) -> list[str]:
    """Extract runtime dependencies from [tool.poetry.dependencies] in pyproject.toml."""
    poetry_deps = pyproject.get("tool", {}).get("poetry", {}).get("dependencies", {})
    if not isinstance(poetry_deps, dict):
        return []

    deps: list[str] = []
    for pkg_name, spec in poetry_deps.items():
        norm_name = normalize_pkg_name(str(pkg_name))
        if norm_name == "python":
            continue
        if isinstance(spec, dict):
            path_val = spec.get("path")
            if isinstance(path_val, str):
                _check_dependency_blocker(path_val, "pyproject.toml", model)
            git_val = spec.get("git")
            if isinstance(git_val, str):
                _check_dependency_blocker(git_val, "pyproject.toml", model)
                if git_val.startswith("http"):
                    deps.append("git+https")
        deps.append(norm_name)
    return deps


def _extract_pipfile_deps(ctx: ScanContext, model: ProjectModel) -> list[str]:
    """Extract runtime package names from the [packages] section of a Pipfile."""
    content = ctx.read_text_safe("Pipfile")
    if not content:
        return []

    deps: list[str] = []
    in_packages = False
    for raw_line in content.splitlines():
        line = raw_line.split("#", 1)[0].strip()
        if not line:
            continue
        if line.startswith("[") and line.endswith("]"):
            in_packages = line == "[packages]"
            continue
        if in_packages and "=" in line:
            key, val = line.split("=", 1)
            _check_dependency_blocker(val, "Pipfile", model)
            if "git+https://" in val or "https://" in val and ".git" in val:
                deps.append("git+https")
            deps.append(normalize_pkg_name(key))
    return deps


def detect_package_manager(
    ctx: ScanContext,
    model: ProjectModel,
    overrides: CLIOverrides | None = None,
) -> None:
    """Detect the authoritative package manager and populate runtime_dependencies."""
    candidates: list[tuple[PackageManager, str, str, ConfidenceLevel]] = []

    pyproject = ctx.pyproject_data or {}
    tool_sec = pyproject.get("tool", {}) if isinstance(pyproject, dict) else {}
    build_backend = (
        pyproject.get("build-system", {}).get("build-backend", "")
        if isinstance(pyproject, dict)
        else ""
    )

    # 1. Check lockfiles (Highest confidence)
    if ctx.has_file("uv.lock"):
        candidates.append((PackageManager.UV, "uv.lock", "Found uv lockfile", ConfidenceLevel.HIGH))
    if ctx.has_file("poetry.lock"):
        candidates.append(
            (
                PackageManager.POETRY,
                "poetry.lock",
                "Found Poetry lockfile",
                ConfidenceLevel.HIGH,
            )
        )
    if ctx.has_file("pdm.lock"):
        candidates.append(
            (PackageManager.PDM, "pdm.lock", "Found PDM lockfile", ConfidenceLevel.HIGH)
        )
    if ctx.has_file("Pipfile.lock"):
        candidates.append(
            (
                PackageManager.PIPENV,
                "Pipfile.lock",
                "Found Pipenv lockfile",
                ConfidenceLevel.HIGH,
            )
        )

    # 2. Check tool sections in pyproject.toml / Pipfile / hatch.toml
    if isinstance(tool_sec, dict):
        if "uv" in tool_sec and not any(c[0] == PackageManager.UV for c in candidates):
            candidates.append(
                (
                    PackageManager.UV,
                    "pyproject.toml",
                    "Found [tool.uv] configuration",
                    ConfidenceLevel.MEDIUM,
                )
            )
        if ("poetry" in tool_sec or "poetry" in str(build_backend)) and not any(
            c[0] == PackageManager.POETRY for c in candidates
        ):
            candidates.append(
                (
                    PackageManager.POETRY,
                    "pyproject.toml",
                    "Found [tool.poetry] configuration",
                    ConfidenceLevel.HIGH,
                )
            )
        if "pdm" in tool_sec and not any(c[0] == PackageManager.PDM for c in candidates):
            candidates.append(
                (
                    PackageManager.PDM,
                    "pyproject.toml",
                    "Found [tool.pdm] configuration",
                    ConfidenceLevel.MEDIUM,
                )
            )
        if "hatch" in tool_sec or ctx.has_file("hatch.toml"):
            src = "hatch.toml" if ctx.has_file("hatch.toml") else "pyproject.toml"
            candidates.append(
                (
                    PackageManager.HATCH,
                    src,
                    "Found Hatch configuration",
                    ConfidenceLevel.MEDIUM,
                )
            )

    if ctx.has_file("Pipfile") and not any(c[0] == PackageManager.PIPENV for c in candidates):
        candidates.append(
            (PackageManager.PIPENV, "Pipfile", "Found Pipfile", ConfidenceLevel.MEDIUM)
        )

    # 3. Check requirements.txt and PEP 621 pip
    req_files = [
        f
        for f in ("requirements.txt", "requirements/prod.txt", "requirements/base.txt")
        if ctx.has_file(f)
    ]
    if req_files:
        candidates.append(
            (
                PackageManager.PIP,
                req_files[0],
                f"Found pip requirements manifest '{req_files[0]}'",
                ConfidenceLevel.HIGH,
            )
        )
    elif isinstance(pyproject.get("project"), dict) and not candidates:
        candidates.append(
            (
                PackageManager.PIP,
                "pyproject.toml",
                "Found standard PEP 621 [project] metadata",
                ConfidenceLevel.MEDIUM,
            )
        )

    # Collect runtime dependencies from all available manifests
    deps: list[str] = []
    if pyproject:
        deps.extend(_extract_pep621_deps(pyproject, model))
        deps.extend(_extract_poetry_deps(pyproject, model))
    for rf in req_files:
        deps.extend(_extract_req_txt_deps(ctx, rf, model))
    if ctx.has_file("Pipfile"):
        deps.extend(_extract_pipfile_deps(ctx, model))

    model.runtime_dependencies = sorted(set(deps))

    # Handle explicit CLI override
    if overrides and overrides.package_manager:
        model.package_manager.value = overrides.package_manager
        model.package_manager.confidence = ConfidenceLevel.HIGH
        model.package_manager.add_evidence(
            source="CLI --package-manager",
            detector="package_manager",
            description=f"Explicit package manager override '{overrides.package_manager.value}'",
            confidence=ConfidenceLevel.HIGH,
        )
        return

    if not candidates:
        model.package_manager.value = PackageManager.PIP
        model.package_manager.confidence = ConfidenceLevel.LOW
        model.package_manager.add_evidence(
            source="default",
            detector="package_manager",
            description="No dependency manifest found; defaulting to pip",
            confidence=ConfidenceLevel.LOW,
        )
        return

    # Record all detected candidates and evidence
    unique_managers: list[PackageManager] = []
    for pm, src, desc, conf in candidates:
        model.package_manager.add_evidence(
            source=src,
            detector="package_manager",
            description=desc,
            confidence=conf,
        )
        if pm not in unique_managers:
            unique_managers.append(pm)

    model.package_manager.candidates = unique_managers
    chosen_pm, chosen_src, _, chosen_conf = candidates[0]
    model.package_manager.value = chosen_pm
    model.package_manager.confidence = chosen_conf

    if len(unique_managers) > 1:
        mgr_names = ", ".join(m.value for m in unique_managers)
        conflict_msg = (
            f"Multiple package managers detected ({mgr_names}); "
            f"selected '{chosen_pm.value}' based on {chosen_src}."
        )
        model.package_manager.conflicts.append(conflict_msg)
        model.warnings.append(conflict_msg)

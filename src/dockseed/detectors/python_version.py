"""Detector and resolver for Python runtime version requirements."""

import re
import sys

from dockseed.exceptions import ValidationError
from dockseed.models import CLIOverrides, ConfidenceLevel, ProjectModel
from dockseed.scanner import ScanContext

SUPPORTED_VERSIONS: tuple[str, ...] = ("3.10", "3.11", "3.12", "3.13", "3.14")
DEFAULT_PREFERRED_VERSION: str = "3.12"


def _parse_major_minor(ver_str: str) -> tuple[int, int] | None:
    """Extract (major, minor) tuple from a version string."""
    match = re.search(r"(\d+)\.(\d+)", ver_str.strip())
    if not match:
        return None
    return int(match.group(1)), int(match.group(2))


def _normalize_poetry_constraint(spec: str) -> str:
    """Convert Poetry caret (^) and tilde (~) syntax into standard comparison operators."""
    spec = spec.strip()
    if spec.startswith("^"):
        parsed = _parse_major_minor(spec[1:])
        if parsed:
            major, minor = parsed
            return f">={major}.{minor},<{major + 1}.0"
    if spec.startswith("~"):
        parsed = _parse_major_minor(spec[1:])
        if parsed:
            major, minor = parsed
            return f">={major}.{minor},<{major}.{minor + 1}"
    return spec


def _version_matches_spec(candidate: str, spec_string: str) -> bool:
    """Evaluate if a candidate '3.x' satisfies a comma-separated constraint string."""
    cand_tuple = _parse_major_minor(candidate)
    if not cand_tuple:
        return False

    normalized = _normalize_poetry_constraint(spec_string)
    clauses = [c.strip() for c in normalized.split(",") if c.strip()]

    for clause in clauses:
        if clause == "*":
            continue

        # Wildcard match like 3.11.* or ==3.11.*
        wildcard_match = re.match(r"^(?:==)?\s*(\d+)\.(\d+)\.\*$", clause)
        if wildcard_match:
            req = (int(wildcard_match.group(1)), int(wildcard_match.group(2)))
            if cand_tuple != req:
                return False
            continue

        op_match = re.match(r"^(==|!=|>=|<=|>|<|~=)\s*(\d+)\.(\d+)(?:\.\d+)?$", clause)
        if op_match:
            op, maj_s, min_s = op_match.groups()
            target = (int(maj_s), int(min_s))
            if op in ("==", "~=") and cand_tuple != target:
                return False
            if op == "!=" and cand_tuple == target:
                return False
            if op == ">=" and not (cand_tuple >= target):
                return False
            if op == "<=" and not (cand_tuple <= target):
                return False
            if op == ">" and not (cand_tuple > target):
                return False
            if op == "<" and not (cand_tuple < target):
                return False
            continue

        # Bare version like "3.11" or "3.11.4"
        bare = _parse_major_minor(clause)
        if bare and cand_tuple != bare:
            return False

    return True


def resolve_compatible_version(spec_string: str) -> list[str]:
    """Return all supported Python versions (3.10-3.14) matching the constraint."""
    return [v for v in SUPPORTED_VERSIONS if _version_matches_spec(v, spec_string)]


def _extract_pipfile_python(content: str) -> str | None:
    """Extract python_version or python_full_version from a Pipfile."""
    for line in content.splitlines():
        clean = line.split("#", 1)[0].strip()
        match = re.match(r'^python_(?:full_)?version\s*=\s*["\']([^"\']+)["\']', clean)
        if match:
            return match.group(1).strip()
    return None


def detect_python_version(
    ctx: ScanContext,
    model: ProjectModel,
    overrides: CLIOverrides | None = None,
) -> None:
    """Detect Python version constraints and resolve a concrete base image version."""
    if overrides and overrides.python_version:
        parsed = _parse_major_minor(overrides.python_version)
        if not parsed:
            raise ValidationError(f"Invalid Python version override: '{overrides.python_version}'")
        ver_str = f"{parsed[0]}.{parsed[1]}"
        if ver_str not in SUPPORTED_VERSIONS:
            supported_str = ", ".join(SUPPORTED_VERSIONS)
            raise ValidationError(
                f"Unsupported Python version '{ver_str}'. Supported: {supported_str}"
            )
        model.python_requirement.value = f"=={ver_str}"
        model.python_requirement.confidence = ConfidenceLevel.HIGH
        model.python_requirement.add_evidence(
            source="CLI --python",
            detector="python_version",
            description=f"Explicit Python override '{ver_str}' provided via CLI",
            confidence=ConfidenceLevel.HIGH,
        )
        model.resolved_python_version.value = ver_str
        model.resolved_python_version.confidence = ConfidenceLevel.HIGH
        model.resolved_python_version.add_evidence(
            source="CLI --python",
            detector="python_version",
            description=f"Resolved to '{ver_str}' from explicit CLI override",
            confidence=ConfidenceLevel.HIGH,
        )
        return

    declarations: list[tuple[str, str, ConfidenceLevel]] = []

    # 1. PEP 621 requires-python in pyproject.toml
    if ctx.pyproject_data:
        project_sec = ctx.pyproject_data.get("project", {})
        if isinstance(project_sec, dict):
            req_py = project_sec.get("requires-python")
            if isinstance(req_py, str) and req_py.strip():
                declarations.append(
                    (
                        "pyproject.toml (project.requires-python)",
                        req_py.strip(),
                        ConfidenceLevel.HIGH,
                    )
                )

        # 2. Poetry tool.poetry.dependencies.python
        tool_sec = ctx.pyproject_data.get("tool", {})
        if isinstance(tool_sec, dict):
            poetry_deps = tool_sec.get("poetry", {}).get("dependencies", {})
            if isinstance(poetry_deps, dict):
                poetry_py = poetry_deps.get("python")
                if isinstance(poetry_py, str) and poetry_py.strip():
                    declarations.append(
                        (
                            "pyproject.toml (tool.poetry.dependencies.python)",
                            poetry_py.strip(),
                            ConfidenceLevel.HIGH,
                        )
                    )

    # 3. .python-version
    if ctx.has_file(".python-version"):
        raw = ctx.read_text_safe(".python-version")
        if raw:
            for line in raw.splitlines():
                clean = line.split("#", 1)[0].strip()
                if clean:
                    declarations.append((".python-version", clean, ConfidenceLevel.HIGH))
                    break

    # 4. .tool-versions (asdf / mise)
    if ctx.has_file(".tool-versions"):
        raw = ctx.read_text_safe(".tool-versions")
        if raw:
            for line in raw.splitlines():
                clean = line.split("#", 1)[0].strip()
                if clean.startswith("python "):
                    ver = clean.split(maxsplit=1)[1].strip()
                    declarations.append((".tool-versions", ver, ConfidenceLevel.MEDIUM))
                    break

    # 5. runtime.txt
    if ctx.has_file("runtime.txt"):
        raw = ctx.read_text_safe("runtime.txt")
        if raw:
            for line in raw.splitlines():
                clean = line.strip()
                if clean.startswith("python-"):
                    declarations.append(
                        (
                            "runtime.txt",
                            clean.removeprefix("python-"),
                            ConfidenceLevel.MEDIUM,
                        )
                    )
                    break

    # 6. Pipfile
    if ctx.has_file("Pipfile"):
        raw = ctx.read_text_safe("Pipfile")
        if raw:
            pipfile_py = _extract_pipfile_python(raw)
            if pipfile_py:
                declarations.append(("Pipfile", pipfile_py, ConfidenceLevel.MEDIUM))

    if declarations:
        primary_source, primary_spec, primary_conf = declarations[0]
        model.python_requirement.value = primary_spec
        model.python_requirement.confidence = primary_conf

        compatible_sets: list[set[str]] = []
        for source, spec, conf in declarations:
            model.python_requirement.add_evidence(
                source=source,
                detector="python_version",
                description=f"Declared Python constraint '{spec}'",
                confidence=conf,
            )
            compat = set(resolve_compatible_version(spec))
            compatible_sets.append(compat)

        intersection = set.intersection(*compatible_sets) if compatible_sets else set()

        if len(compatible_sets) > 1 and not intersection:
            conflict_msg = "Conflicting Python version constraints across manifests: " + ", ".join(
                f"{src}='{sp}'" for src, sp, _ in declarations
            )
            model.python_requirement.conflicts.append(conflict_msg)
            model.warnings.append(conflict_msg)
            candidates = sorted(compatible_sets[0])
        else:
            candidates = sorted(intersection)

        if not candidates:
            raise ValidationError(
                f"Python constraint '{primary_spec}' from {primary_source} is incompatible "
                f"with supported versions ({', '.join(SUPPORTED_VERSIONS)})."
            )

        model.resolved_python_version.candidates = candidates
        # Prefer exact match if pinned, else prefer 3.12 if allowed, else highest compatible
        if len(candidates) == 1:
            chosen = candidates[0]
            res_conf = ConfidenceLevel.HIGH
        elif DEFAULT_PREFERRED_VERSION in candidates:
            chosen = DEFAULT_PREFERRED_VERSION
            res_conf = ConfidenceLevel.HIGH
        else:
            chosen = candidates[-1]
            res_conf = ConfidenceLevel.MEDIUM

        model.resolved_python_version.value = chosen
        model.resolved_python_version.confidence = res_conf
        model.resolved_python_version.add_evidence(
            source=primary_source,
            detector="python_version",
            description=f"Resolved '{chosen}' from compatible candidates {candidates}",
            confidence=res_conf,
        )
        return

    # 7. Active interpreter fallback
    active_ver = f"{sys.version_info.major}.{sys.version_info.minor}"
    fallback_ver = active_ver if active_ver in SUPPORTED_VERSIONS else DEFAULT_PREFERRED_VERSION
    model.python_requirement.value = None
    model.python_requirement.confidence = ConfidenceLevel.LOW
    model.resolved_python_version.value = fallback_ver
    model.resolved_python_version.confidence = ConfidenceLevel.LOW
    model.resolved_python_version.add_evidence(
        source="active_interpreter",
        detector="python_version",
        description=f"No explicit Python constraint found; fell back to Python {fallback_ver}",
        confidence=ConfidenceLevel.LOW,
    )
    model.warnings.append(
        f"No explicit Python version requirement found; defaulting to Python {fallback_ver}."
    )

"""Core domain models and typed data structures for Dockseed."""

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Generic, TypeVar

from dockseed.exceptions import ExitCode

T = TypeVar("T")


class ConfidenceLevel(str, Enum):
    """Qualitative confidence levels for detections."""

    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class PackageManager(str, Enum):
    """Supported Python dependency and package managers."""

    PIP = "pip"
    POETRY = "poetry"
    UV = "uv"
    PDM = "pdm"
    HATCH = "hatch"
    PIPENV = "pipenv"


class Framework(str, Enum):
    """Recognized application frameworks and runtime workloads."""

    FASTAPI = "fastapi"
    FLASK = "flask"
    DJANGO = "django"
    STREAMLIT = "streamlit"
    GRADIO = "gradio"
    CELERY = "celery"
    CLI = "cli"
    SCRIPT = "script"
    UNKNOWN = "unknown"


@dataclass(frozen=True, order=True)
class Evidence:
    """Immutable record explaining how a detection was inferred."""

    source: str
    detector: str
    description: str
    confidence: ConfidenceLevel


@dataclass
class Detection(Generic[T]):
    """Represents an inferred project attribute along with its supporting evidence."""

    value: T | None = None
    confidence: ConfidenceLevel = ConfidenceLevel.LOW
    evidence: list[Evidence] = field(default_factory=list)
    conflicts: list[str] = field(default_factory=list)
    candidates: list[T] = field(default_factory=list)

    def add_evidence(
        self,
        source: str,
        detector: str,
        description: str,
        confidence: ConfidenceLevel,
    ) -> None:
        """Append a new piece of evidence and keep the list deterministically sorted."""
        item = Evidence(
            source=source,
            detector=detector,
            description=description,
            confidence=confidence,
        )
        if item not in self.evidence:
            self.evidence.append(item)
            self.evidence.sort()

    def to_dict(self) -> dict[str, Any]:
        """Serialize detection to a JSON-compatible dictionary."""
        val: Any = self.value.value if isinstance(self.value, Enum) else self.value
        cands: list[Any] = [c.value if isinstance(c, Enum) else c for c in self.candidates]
        return {
            "value": val,
            "confidence": self.confidence.value,
            "evidence": [
                {
                    "source": e.source,
                    "detector": e.detector,
                    "description": e.description,
                    "confidence": e.confidence.value,
                }
                for e in sorted(self.evidence)
            ],
            "conflicts": list(self.conflicts),
            "candidates": cands,
        }


@dataclass(frozen=True)
class CLIOverrides:
    """Explicit user overrides passed via CLI flags or API arguments."""

    python_version: str | None = None
    package_manager: PackageManager | None = None
    entrypoint: str | None = None
    port: int | None = None


@dataclass
class ProjectModel:
    """Normalized internal representation of a scanned Python project."""

    root: Path
    python_requirement: Detection[str] = field(default_factory=Detection)
    resolved_python_version: Detection[str] = field(default_factory=Detection)
    package_manager: Detection[PackageManager] = field(default_factory=Detection)
    framework: Detection[Framework] = field(
        default_factory=lambda: Detection(value=Framework.UNKNOWN)
    )
    entry_point: Detection[list[str]] = field(default_factory=Detection)
    runtime_dependencies: list[str] = field(default_factory=list)
    system_dependencies: list[str] = field(default_factory=list)
    ports: list[int] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    blockers: list[str] = field(default_factory=list)
    existing_dockerfile: bool = False
    existing_dockerignore: bool = False

    def to_dict(self) -> dict[str, Any]:
        """Serialize the complete project model into a deterministic dictionary."""
        return {
            "root": str(self.root),
            "python_requirement": self.python_requirement.to_dict(),
            "resolved_python_version": self.resolved_python_version.to_dict(),
            "package_manager": self.package_manager.to_dict(),
            "framework": self.framework.to_dict(),
            "entry_point": self.entry_point.to_dict(),
            "runtime_dependencies": sorted(set(self.runtime_dependencies)),
            "system_dependencies": sorted(set(self.system_dependencies)),
            "ports": sorted(set(self.ports)),
            "warnings": list(self.warnings),
            "blockers": list(self.blockers),
            "existing_dockerfile": self.existing_dockerfile,
            "existing_dockerignore": self.existing_dockerignore,
        }


@dataclass(frozen=True)
class GenerationResult:
    """Output returned by Dockerfile and .dockerignore generators."""

    content: str
    assumptions: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


__all__ = [
    "CLIOverrides",
    "ConfidenceLevel",
    "Detection",
    "Evidence",
    "ExitCode",
    "Framework",
    "GenerationResult",
    "PackageManager",
    "ProjectModel",
]

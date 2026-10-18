"""Dockseed — Automated, deterministic Dockerfile generator for Python projects."""

from dockseed.exceptions import (
    AmbiguityError,
    DockseedError,
    OverwriteBlockedError,
    ValidationError,
)
from dockseed.inference import format_scan_report, scan_project
from dockseed.models import (
    CLIOverrides,
    ConfidenceLevel,
    Detection,
    Evidence,
    ExitCode,
    Framework,
    GenerationResult,
    PackageManager,
    ProjectModel,
)

__version__ = "0.1.0"

__all__ = [
    "__version__",
    "AmbiguityError",
    "CLIOverrides",
    "ConfidenceLevel",
    "Detection",
    "DockseedError",
    "Evidence",
    "ExitCode",
    "Framework",
    "GenerationResult",
    "OverwriteBlockedError",
    "PackageManager",
    "ProjectModel",
    "ValidationError",
    "format_scan_report",
    "scan_project",
]

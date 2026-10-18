"""Dockseed — Automated, deterministic Dockerfile generator for Python projects."""

from dockseed.exceptions import (
    AmbiguityError,
    DockseedError,
    OverwriteBlockedError,
    ValidationError,
)
from dockseed.generators import generate_dockerfile, generate_dockerignore
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
from dockseed.validators import ValidationReport, validate_dockerfile

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
    "ValidationReport",
    "format_scan_report",
    "generate_dockerfile",
    "generate_dockerignore",
    "scan_project",
    "validate_dockerfile",
]

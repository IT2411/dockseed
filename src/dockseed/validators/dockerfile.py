"""Static consistency and security validator for Dockerfile and .dockerignore."""

import json
import re
from dataclasses import dataclass, field

from dockseed.models import ProjectModel


@dataclass
class ValidationReport:
    """Results of static Dockerfile and .dockerignore validation."""

    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def is_valid(self) -> bool:
        """Return True if zero blocking errors were found."""
        return len(self.errors) == 0


def _join_continuation_lines(raw_text: str) -> list[str]:
    """Join backslash-continued Dockerfile lines into logical instructions."""
    logical_lines: list[str] = []
    buffer = ""
    for raw_line in raw_text.splitlines():
        stripped = raw_line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped.endswith("\\"):
            buffer += stripped[:-1].strip() + " "
        else:
            buffer += stripped
            logical_lines.append(buffer.strip())
            buffer = ""
    if buffer:
        logical_lines.append(buffer.strip())
    return logical_lines


def validate_dockerfile(
    dockerfile_content: str,
    model: ProjectModel,
    dockerignore_content: str | None = None,
) -> ValidationReport:
    """Validate Dockerfile structure, base image, COPY sources, USER, and .dockerignore."""
    report = ValidationReport()
    instructions = _join_continuation_lines(dockerfile_content)

    has_from = False
    has_workdir = False
    has_cmd_or_entrypoint = False
    has_non_root_user = False

    for inst in instructions:
        parts = inst.split(maxsplit=1)
        if not parts:
            continue
        keyword = parts[0].upper()
        arg = parts[1].strip() if len(parts) > 1 else ""

        if keyword == "FROM":
            has_from = True
            # Check base image version alignment if python:<ver> is used
            match = re.search(r"python:(\d+\.\d+)", arg)
            if (
                match
                and model.resolved_python_version.value
                and match.group(1) != model.resolved_python_version.value
            ):
                report.warnings.append(
                    f"Dockerfile base image Python version ({match.group(1)}) differs from "
                    f"resolved project version ({model.resolved_python_version.value})."
                )

        elif keyword == "WORKDIR":
            has_workdir = True

        elif keyword == "USER":
            if arg and arg.lower() not in ("root", "0"):
                has_non_root_user = True

        elif keyword == "COPY":
            # Strip flags like --from=... or --chown=...
            tokens = [t for t in arg.split() if not t.startswith("--")]
            has_from_flag = any(t.startswith("--from=") for t in arg.split())
            if not has_from_flag and len(tokens) >= 2:
                sources = tokens[:-1]
                for src in sources:
                    if src in (".", "./"):
                        continue
                    clean_src = src.rstrip("/")
                    target_path = model.root / clean_src
                    if not target_path.exists():
                        report.errors.append(
                            f"COPY instruction references missing path in project: '{src}'"
                        )

        elif keyword in ("CMD", "ENTRYPOINT"):
            has_cmd_or_entrypoint = True
            if not (arg.startswith("[") and arg.endswith("]")):
                report.warnings.append(
                    f"{keyword} instruction uses shell form instead of JSON exec array: '{inst}'"
                )
            else:
                try:
                    parsed_cmd = json.loads(arg)
                    if not isinstance(parsed_cmd, list) or not parsed_cmd:
                        report.errors.append(
                            f"{keyword} JSON array must be a non-empty list of strings."
                        )
                except json.JSONDecodeError:
                    report.errors.append(
                        f"{keyword} instruction contains invalid JSON array: '{arg}'"
                    )

    if not has_from:
        report.errors.append("Dockerfile is missing a required FROM instruction.")
    if not has_workdir:
        report.warnings.append("Dockerfile does not define a WORKDIR instruction.")
    if not has_cmd_or_entrypoint:
        report.errors.append("Dockerfile is missing a startup instruction (CMD or ENTRYPOINT).")
    if not has_non_root_user:
        report.warnings.append(
            "Dockerfile does not switch to a non-root USER before running the application."
        )

    # Validate .dockerignore if provided
    if dockerignore_content is not None:
        ignore_lines = {
            line.strip()
            for line in dockerignore_content.splitlines()
            if line.strip() and not line.strip().startswith("#")
        }
        if ".env" not in ignore_lines:
            report.errors.append(".dockerignore does not exclude '.env' secret files.")
        if not any(v in ignore_lines for v in (".venv", ".venv/", "venv", "venv/")):
            report.warnings.append(
                ".dockerignore does not exclude local virtual environments ('.venv/')."
            )

        # Ensure README.md is not excluded if referenced by pyproject.toml
        if (model.root / "pyproject.toml").is_file() and "README.md" in ignore_lines:
            report.errors.append(
                ".dockerignore excludes 'README.md', which may break pyproject.toml package builds."
            )

    return report

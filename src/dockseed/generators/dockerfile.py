"""Deterministic, layer-cached, non-root Dockerfile generator."""

import json

from dockseed.exceptions import ValidationError
from dockseed.models import (
    Framework,
    GenerationResult,
    PackageManager,
    ProjectModel,
)


def _file_exists(model: ProjectModel, rel_posix: str) -> bool:
    """Check if a relative file exists in the project root."""
    return (model.root / rel_posix).is_file()


def _render_dependency_steps(
    model: ProjectModel, pm: PackageManager, include_comments: bool
) -> tuple[list[str], bool]:
    """Return dependency install lines and whether a post-COPY install is needed."""
    lines: list[str] = []
    needs_post_copy_install = False

    has_pyproject = _file_exists(model, "pyproject.toml")
    has_readme = _file_exists(model, "README.md")

    if pm == PackageManager.UV:
        if include_comments:
            lines.append("# Install uv package manager and project dependencies")
        lines.append("COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/")
        manifest_files = ["pyproject.toml"]
        if _file_exists(model, "uv.lock"):
            manifest_files.append("uv.lock")
            sync_cmd = "RUN uv sync --frozen --no-install-project --no-dev"
        else:
            sync_cmd = "RUN uv sync --no-install-project --no-dev"
        if has_pyproject:
            lines.append(f"COPY {' '.join(manifest_files)} ./")
            lines.append(sync_cmd)
            needs_post_copy_install = True
    elif pm == PackageManager.POETRY:
        if include_comments:
            lines.append("# Install Poetry and project runtime dependencies")
        lines.append("RUN pip install --no-cache-dir poetry")
        manifest_files = ["pyproject.toml"]
        if _file_exists(model, "poetry.lock"):
            manifest_files.append("poetry.lock")
        if has_pyproject:
            lines.append(f"COPY {' '.join(manifest_files)} ./")
            lines.append("RUN poetry install --no-interaction --no-ansi --no-root --only main")
            if model.framework.value == Framework.CLI:
                needs_post_copy_install = True
    elif pm == PackageManager.PDM:
        if include_comments:
            lines.append("# Install PDM and project runtime dependencies")
        lines.append("RUN pip install --no-cache-dir pdm")
        manifest_files = ["pyproject.toml"]
        if _file_exists(model, "pdm.lock"):
            manifest_files.append("pdm.lock")
        if has_pyproject:
            lines.append(f"COPY {' '.join(manifest_files)} ./")
            lines.append("RUN pdm install --check --prod --no-editable --no-self")
            if model.framework.value == Framework.CLI:
                needs_post_copy_install = True
    elif pm == PackageManager.PIPENV:
        if include_comments:
            lines.append("# Install Pipenv and system-wide runtime dependencies")
        lines.append("RUN pip install --no-cache-dir pipenv")
        manifest_files = []
        if _file_exists(model, "Pipfile"):
            manifest_files.append("Pipfile")
        if _file_exists(model, "Pipfile.lock"):
            manifest_files.append("Pipfile.lock")
            install_cmd = "RUN pipenv install --system --deploy"
        else:
            install_cmd = "RUN pipenv install --system"
        if manifest_files:
            lines.append(f"COPY {' '.join(manifest_files)} ./")
            lines.append(install_cmd)
    else:
        # PIP or HATCH
        req_file: str | None = None
        for candidate in ("requirements.txt", "requirements/prod.txt", "requirements/base.txt"):
            if _file_exists(model, candidate):
                req_file = candidate
                break

        if req_file:
            if include_comments:
                lines.append(f"# Install dependencies from {req_file} (cached layer)")
            if "/" in req_file:
                lines.append("COPY requirements/ ./requirements/")
            else:
                lines.append(f"COPY {req_file} ./")
            lines.append(f"RUN pip install --no-cache-dir -r {req_file}")
        elif has_pyproject and (
            model.runtime_dependencies or model.framework.value == Framework.CLI
        ):
            if include_comments:
                lines.append("# Install project dependencies from pyproject.toml")
            copy_list = ["pyproject.toml"]
            if has_readme:
                copy_list.append("README.md")
            lines.append(f"COPY {' '.join(copy_list)} ./")
            needs_post_copy_install = True

    return lines, needs_post_copy_install


def generate_dockerfile(
    model: ProjectModel,
    include_comments: bool = True,
) -> GenerationResult:
    """Generate a deterministic, layer-cached, non-root Dockerfile from a ProjectModel."""
    py_ver = model.resolved_python_version.value or "3.12"
    pm = model.package_manager.value or PackageManager.PIP
    fw = model.framework.value or Framework.UNKNOWN
    entrypoint = model.entry_point.value

    if not entrypoint:
        raise ValidationError(
            "Cannot generate Dockerfile without a resolved entry point. "
            "Provide '--entrypoint <cmd>' to specify the startup command."
        )

    assumptions: list[str] = []
    warnings: list[str] = list(model.warnings)
    lines: list[str] = ["# syntax=docker/dockerfile:1"]

    # 1. Base Image
    if include_comments:
        ev = model.resolved_python_version.evidence
        src_note = f" (from {ev[0].source})" if ev else ""
        lines.append(f"# Base image selected for Python {py_ver}{src_note}")
    lines.append(f"FROM python:{py_ver}-slim")
    lines.append("")

    # 2. Environment Variables
    if include_comments:
        lines.append("# Set standard Python container environment variables")
    env_vars = [
        "PYTHONDONTWRITEBYTECODE=1",
        "PYTHONUNBUFFERED=1",
        "PIP_NO_CACHE_DIR=1",
        "PIP_DISABLE_PIP_VERSION_CHECK=1",
    ]
    if pm == PackageManager.UV:
        env_vars.append("UV_NO_CACHE=1")
        env_vars.append("UV_COMPILE_BYTECODE=1")
        env_vars.append('PATH="/app/.venv/bin:$PATH"')
    elif pm == PackageManager.POETRY:
        env_vars.append("POETRY_VIRTUALENVS_CREATE=false")
    elif pm == PackageManager.PDM:
        env_vars.append('PATH="/app/.venv/bin:$PATH"')

    env_formatted = " \\\n    ".join(env_vars)
    lines.append(f"ENV {env_formatted}")
    lines.append("")

    # 3. Working Directory
    lines.append("WORKDIR /app")
    lines.append("")

    # 4. System Dependencies (apt-get)
    if model.system_dependencies:
        if include_comments:
            lines.append("# Install required native system dependencies")
        pkgs = " \\\n    ".join(model.system_dependencies)
        lines.append(
            "RUN apt-get update && apt-get install -y --no-install-recommends \\\n"
            f"    {pkgs} \\\n"
            "    && rm -rf /var/lib/apt/lists/*"
        )
        lines.append("")

    # 5. Dependency Installation (Layer Cached)
    dep_lines, needs_post_copy = _render_dependency_steps(model, pm, include_comments)
    if dep_lines:
        lines.extend(dep_lines)
        lines.append("")

    # 6. Create Non-Root User & Copy Source Code
    if include_comments:
        lines.append("# Create non-root user and copy application source files")
    lines.append("RUN useradd --create-home --shell /bin/bash appuser")
    lines.append("COPY --chown=appuser:appuser . .")

    if needs_post_copy:
        if pm == PackageManager.UV:
            lines.append(
                "RUN uv sync --frozen --no-dev"
                if _file_exists(model, "uv.lock")
                else "RUN uv sync --no-dev"
            )
        elif pm == PackageManager.POETRY:
            lines.append("RUN poetry install --no-interaction --no-ansi --only main")
        elif pm == PackageManager.PDM:
            lines.append("RUN pdm install --check --prod --no-editable")
        else:
            lines.append("RUN pip install --no-cache-dir .")
    lines.append("")

    # 7. Django Static Files Note
    if fw == Framework.DJANGO and include_comments:
        lines.append("# Optional: Uncomment to collect static files if STATIC_ROOT is configured")
        lines.append("# RUN python manage.py collectstatic --noinput")
        lines.append("")

    # 8. Switch to Non-Root User
    lines.append("USER appuser")
    lines.append("")

    # 9. Expose Port
    if model.ports:
        for port in model.ports:
            if include_comments:
                lines.append(f"# Expose port for {fw.value} application")
            lines.append(f"EXPOSE {port}")
        lines.append("")

    # 10. Startup Command (Exec Form)
    if include_comments:
        lines.append("# Run application using exec-form for proper SIGTERM signal handling")
    cmd_json = json.dumps(entrypoint)
    lines.append(f"CMD {cmd_json}")

    content = "\n".join(lines) + "\n"
    return GenerationResult(content=content, assumptions=assumptions, warnings=warnings)

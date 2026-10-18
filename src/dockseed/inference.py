"""Orchestration pipeline for scanning a Python project and formatting reports."""

import json
import shlex
from pathlib import Path

from dockseed.detectors import (
    detect_entrypoint,
    detect_framework,
    detect_native_dependencies,
    detect_package_manager,
    detect_python_version,
    scan_python_sources,
)
from dockseed.environment import inspect_environment
from dockseed.models import CLIOverrides, ProjectModel
from dockseed.scanner import discover_project


def scan_project(
    path: Path = Path("."),
    overrides: CLIOverrides | None = None,
) -> ProjectModel:
    """Execute the deterministic detection pipeline and return a normalized ProjectModel."""
    ctx = discover_project(path)
    model = ProjectModel(root=ctx.root)
    model.existing_dockerfile = ctx.has_file("Dockerfile")
    model.existing_dockerignore = ctx.has_file(".dockerignore")

    # Stage 1: Python version and runtime constraints
    detect_python_version(ctx, model, overrides)

    # Stage 2: Package manager, runtime dependencies, and path/SSH blockers
    detect_package_manager(ctx, model, overrides)

    # Stage 3: Native apt system dependencies
    detect_native_dependencies(model)

    # Stage 4: Static AST inspection for frameworks and entrypoints
    ast_infos = scan_python_sources(ctx)
    detect_framework(ctx, model, ast_infos)
    detect_entrypoint(ctx, model, ast_infos, overrides)

    # Stage 5: Optional local virtual-environment cross-check
    inspect_environment(model)

    # Merge any scanner warnings
    for w in ctx.warnings:
        if w not in model.warnings:
            model.warnings.append(w)

    return model


def format_scan_report(model: ProjectModel, output_format: str = "text") -> str:
    """Format a ProjectModel as either a human-readable text report or JSON string."""
    if output_format == "json":
        return json.dumps(model.to_dict(), indent=2, sort_keys=True)

    lines: list[str] = [
        "Dockseed — Python Project Analysis",
        "",
        f"Project root: {model.root}",
        "",
        "Detections:",
        "  Language: Python",
    ]

    py_req = model.python_requirement.value or "unspecified"
    py_res = model.resolved_python_version.value or "unknown"
    py_conf = model.resolved_python_version.confidence.value
    lines.append(f"  Python version: {py_res} (requirement: {py_req}, confidence: {py_conf})")

    pm_val = model.package_manager.value.value if model.package_manager.value else "unknown"
    pm_conf = model.package_manager.confidence.value
    lines.append(f"  Package manager: {pm_val} (confidence: {pm_conf})")

    fw_val = model.framework.value.value if model.framework.value else "unknown"
    fw_conf = model.framework.confidence.value
    lines.append(f"  Framework: {fw_val} (confidence: {fw_conf})")

    if model.entry_point.value:
        ep_str = shlex.join(model.entry_point.value)
        ep_conf = model.entry_point.confidence.value
        lines.append(f"  Entry point: {ep_str} (confidence: {ep_conf})")
    else:
        lines.append("  Entry point: unresolved (confidence: low)")

    if model.ports:
        ports_str = ", ".join(str(p) for p in model.ports)
        lines.append(f"  Application port(s): {ports_str}")

    if model.system_dependencies:
        sys_str = ", ".join(model.system_dependencies)
        lines.append(f"  System packages: {sys_str}")

    if model.blockers:
        lines.append("")
        lines.append("Blockers:")
        for b in model.blockers:
            lines.append(f"  - {b}")

    if model.warnings:
        lines.append("")
        lines.append("Warnings:")
        for w in model.warnings:
            lines.append(f"  - {w}")

    return "\n".join(lines)

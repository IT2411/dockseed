"""Command-line interface for Dockseed."""

import argparse
import shlex
import sys
from collections.abc import Sequence
from pathlib import Path

from dockseed import __version__
from dockseed.exceptions import (
    AmbiguityError,
    DockseedError,
    ExitCode,
    OverwriteBlockedError,
    ValidationError,
)
from dockseed.generators import generate_dockerfile, generate_dockerignore
from dockseed.inference import format_scan_report, scan_project
from dockseed.models import (
    CLIOverrides,
    ConfidenceLevel,
    PackageManager,
    ProjectModel,
)
from dockseed.validators import validate_dockerfile
from dockseed.writer import write_project_files


def build_parser() -> argparse.ArgumentParser:
    """Construct and return the CLI argument parser."""
    parser = argparse.ArgumentParser(
        prog="dockseed",
        description="Inspect Python projects and generate deterministic Dockerfiles.",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )

    subparsers = parser.add_subparsers(dest="command", required=False)

    # --- dockseed scan ---
    scan_parser = subparsers.add_parser(
        "scan",
        help="Analyze a project without writing files.",
    )
    scan_parser.add_argument(
        "path",
        nargs="?",
        type=Path,
        default=Path("."),
        help="Path to the Python project root (default: current directory).",
    )
    scan_parser.add_argument(
        "--format",
        choices=["text", "json"],
        default="text",
        dest="output_format",
        help="Output format for the scan report (default: text).",
    )

    # --- dockseed init ---
    init_parser = subparsers.add_parser(
        "init",
        help="Generate Dockerfile and .dockerignore for a project.",
    )
    init_parser.add_argument(
        "--path",
        type=Path,
        default=Path("."),
        help="Path to the Python project root (default: current directory).",
    )
    init_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print planned changes without writing files.",
    )
    init_parser.add_argument(
        "--yes",
        "-y",
        action="store_true",
        help="Accept safe defaults without prompting (fails on critical ambiguities).",
    )
    init_parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Explicitly authorize replacing existing Dockerfile and .dockerignore.",
    )
    init_parser.add_argument(
        "--comments",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Include explanatory inline comments in generated Dockerfile (default: True).",
    )
    init_parser.add_argument(
        "--python",
        type=str,
        default=None,
        dest="python_version",
        help="Explicitly override the target Python version (e.g., 3.12).",
    )
    init_parser.add_argument(
        "--package-manager",
        type=str,
        choices=[pm.value for pm in PackageManager],
        default=None,
        help="Explicitly override the detected package manager.",
    )
    init_parser.add_argument(
        "--entrypoint",
        type=str,
        default=None,
        help="Explicitly override the startup command or application entrypoint.",
    )
    init_parser.add_argument(
        "--port",
        type=int,
        default=None,
        help="Explicitly override the exposed application port.",
    )

    # --- dockseed check ---
    check_parser = subparsers.add_parser(
        "check",
        help="Validate an existing Dockerfile or project configuration.",
    )
    check_parser.add_argument(
        "path",
        nargs="?",
        type=Path,
        default=Path("."),
        help="Path to the Python project root (default: current directory).",
    )
    check_parser.add_argument(
        "--build",
        action="store_true",
        help="Opt-in build validation using an installed container CLI.",
    )
    check_parser.add_argument(
        "--runtime",
        choices=["docker", "podman", "nerdctl"],
        default=None,
        help="Container runtime to use with --build (auto-detected if omitted).",
    )

    return parser


def _prompt_choice(prompt_text: str, options: list[str]) -> int:
    """Prompt the user in an interactive terminal to choose an option index (0-based)."""
    print(prompt_text)
    for idx, opt in enumerate(options, start=1):
        print(f"  [{idx}] {opt}")
    while True:
        raw = input(f"Select an option [1-{len(options)}] (default: 1): ").strip()
        if not raw:
            return 0
        if raw.isdigit():
            choice = int(raw)
            if 1 <= choice <= len(options):
                return choice - 1
        print(f"Please enter a number between 1 and {len(options)}.")


def _resolve_ambiguities(
    model: ProjectModel,
    overrides: CLIOverrides,
    interactive: bool,
) -> None:
    """Resolve critical ambiguities via interactive prompts or fail fast with exit code 3."""
    if model.blockers:
        blocker_list = "\n  - ".join(model.blockers)
        raise ValidationError(f"Critical containerization blockers detected:\n  - {blocker_list}")

    # 1. Conflicting Python constraints
    if model.python_requirement.conflicts and not overrides.python_version:
        cands = model.resolved_python_version.candidates or ["3.12"]
        if not interactive:
            raise AmbiguityError(
                f"{model.python_requirement.conflicts[0]} "
                "Re-run with '--python <version>' (e.g., --python 3.12) to resolve."
            )
        idx = _prompt_choice(
            "Conflicting Python version constraints found. Select target Python version:",
            cands,
        )
        model.resolved_python_version.value = cands[idx]
        model.resolved_python_version.confidence = ConfidenceLevel.HIGH

    # 2. Competing package managers with lockfiles
    if len(model.package_manager.candidates) > 1 and not overrides.package_manager:
        pm_cands = [m.value for m in model.package_manager.candidates]
        if not interactive:
            raise AmbiguityError(
                f"Multiple package managers detected ({', '.join(pm_cands)}). "
                "Re-run with '--package-manager <name>' to resolve."
            )
        idx = _prompt_choice(
            "Multiple package managers detected. Select authoritative package manager:",
            pm_cands,
        )
        model.package_manager.value = model.package_manager.candidates[idx]
        model.package_manager.confidence = ConfidenceLevel.HIGH

    # 3. Multiple candidate entrypoints
    if len(model.entry_point.candidates) > 1 and not overrides.entrypoint:
        ep_cands = [shlex.join(c) for c in model.entry_point.candidates]
        if not interactive:
            raise AmbiguityError(
                f"Multiple plausible entry points detected ({', '.join(ep_cands)}). "
                "Re-run with '--entrypoint \"<command>\"' to resolve."
            )
        idx = _prompt_choice(
            "Multiple entry points detected. Select application startup command:",
            ep_cands,
        )
        model.entry_point.value = model.entry_point.candidates[idx]
        model.entry_point.confidence = ConfidenceLevel.HIGH

    # 4. Missing entrypoint altogether
    if not model.entry_point.value:
        if not interactive:
            raise AmbiguityError(
                "Could not infer an application entry point automatically. "
                "Re-run with '--entrypoint \"<command>\"' to specify how the application starts."
            )
        raw_cmd = input(
            "Could not infer startup command. Enter startup command (e.g., python main.py): "
        ).strip()
        if not raw_cmd:
            raise AmbiguityError("No startup command provided.")
        model.entry_point.value = shlex.split(raw_cmd)
        model.entry_point.confidence = ConfidenceLevel.HIGH


def _handle_init(args: argparse.Namespace) -> int:
    """Execute the `dockseed init` workflow."""
    pm_override = PackageManager(args.package_manager) if args.package_manager else None
    overrides = CLIOverrides(
        python_version=args.python_version,
        package_manager=pm_override,
        entrypoint=args.entrypoint,
        port=args.port,
    )

    model = scan_project(args.path, overrides=overrides)

    # Check overwrite policy early before prompting if not a dry-run
    dockerfile_path = model.root / "Dockerfile"
    if not args.dry_run and not args.overwrite and dockerfile_path.exists():
        raise OverwriteBlockedError(
            f"'{dockerfile_path}' already exists. Pass '--overwrite' to replace it."
        )

    is_tty = sys.stdin.isatty()
    interactive = is_tty and not args.yes

    _resolve_ambiguities(model, overrides, interactive=interactive)

    df_res = generate_dockerfile(model, include_comments=args.comments)
    di_res = generate_dockerignore(model)

    # Validate generated files statically before writing
    val_report = validate_dockerfile(df_res.content, model, di_res.content)
    if not val_report.is_valid:
        err_msg = "\n  - ".join(val_report.errors)
        raise ValidationError(f"Generated configuration failed static validation:\n  - {err_msg}")

    print(format_scan_report(model, output_format="text"))
    print("")
    print("Planned configuration:")
    print(f"  Base image: python:{model.resolved_python_version.value}-slim")
    print("  Runtime user: appuser (non-root)")
    if model.entry_point.value:
        print(f"  Startup command: {shlex.join(model.entry_point.value)}")

    if args.dry_run:
        print("\n--- Dockerfile (dry-run) ---")
        print(df_res.content, end="")
        print("--- .dockerignore (dry-run) ---")
        print(di_res.content, end="")
        return int(ExitCode.SUCCESS)

    if interactive:
        ans = input("\nProceed with creating files? [Y/n]: ").strip().lower()
        if ans not in ("", "y", "yes"):
            print("Aborted by user.")
            return int(ExitCode.SUCCESS)

    written = write_project_files(
        model.root,
        df_res.content,
        di_res.content,
        overwrite=args.overwrite,
    )
    for p in written:
        print(f"Created {p.name}")
    print("\nReview the generated files before building the image.")
    return int(ExitCode.SUCCESS)


def _handle_check(args: argparse.Namespace) -> int:
    """Execute the `dockseed check` workflow."""
    model = scan_project(args.path)
    dockerfile_path = model.root / "Dockerfile"
    dockerignore_path = model.root / ".dockerignore"

    if not dockerfile_path.is_file():
        raise ValidationError(
            f"No Dockerfile found at '{dockerfile_path}'. Run 'dockseed init' first."
        )

    df_content = dockerfile_path.read_text(encoding="utf-8")
    di_content = (
        dockerignore_path.read_text(encoding="utf-8") if dockerignore_path.is_file() else None
    )

    report = validate_dockerfile(df_content, model, di_content)
    for w in report.warnings:
        print(f"Warning: {w}")

    if not report.is_valid:
        for e in report.errors:
            print(f"Validation error: {e}", file=sys.stderr)
        raise ValidationError("Dockerfile validation failed.")

    print("Static Dockerfile validation passed.")
    return int(ExitCode.SUCCESS)


def main(argv: Sequence[str] | None = None) -> int:
    """Main entry point for the dockseed CLI."""
    parser = build_parser()
    args = parser.parse_args(argv)

    if not args.command:
        parser.print_help()
        return int(ExitCode.SUCCESS)

    try:
        if args.command == "scan":
            model = scan_project(args.path)
            print(format_scan_report(model, output_format=args.output_format))
            return int(ExitCode.SUCCESS)
        if args.command == "init":
            return _handle_init(args)
        if args.command == "check":
            return _handle_check(args)
        return int(ExitCode.SUCCESS)  # pragma: no cover
    except DockseedError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return int(exc.exit_code)
    except Exception as exc:  # pragma: no cover
        print(f"Unexpected error: {exc}", file=sys.stderr)
        return int(ExitCode.GENERAL_ERROR)


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())

"""Command-line interface for Dockseed."""

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from dockseed import __version__
from dockseed.exceptions import DockseedError, ExitCode
from dockseed.inference import format_scan_report, scan_project
from dockseed.models import PackageManager


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

        # init and check handlers will be wired in Phases 3-4
        print(f"dockseed {args.command}: command skeleton initialized.")
        return int(ExitCode.SUCCESS)
    except DockseedError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return int(exc.exit_code)
    except Exception as exc:  # pragma: no cover
        print(f"Unexpected error: {exc}", file=sys.stderr)
        return int(ExitCode.GENERAL_ERROR)


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())

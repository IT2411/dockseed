"""Phase 0 tests for the CLI argument parser and entry point skeleton."""

import subprocess
import sys

import pytest

from dockseed import __version__
from dockseed.cli import main
from dockseed.exceptions import ExitCode


def test_cli_no_arguments_prints_help(capsys: pytest.CaptureFixture[str]) -> None:
    code = main([])
    captured = capsys.readouterr()
    assert code == int(ExitCode.SUCCESS)
    assert "usage: dockseed" in captured.out


def test_cli_version(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc_info:
        main(["--version"])
    assert exc_info.value.code == 0
    captured = capsys.readouterr()
    assert __version__ in captured.out


def test_cli_subcommands_parse_correctly(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["scan", ".", "--format", "json"]) == int(ExitCode.SUCCESS)
    assert main(
        [
            "init",
            "--dry-run",
            "--yes",
            "--overwrite",
            "--no-comments",
            "--python",
            "3.12",
            "--package-manager",
            "uv",
            "--entrypoint",
            "app.main:app",
            "--port",
            "8000",
        ]
    ) == int(ExitCode.SUCCESS)
    assert main(["check", "--build", "--runtime", "podman"]) == int(ExitCode.SUCCESS)


def test_main_module_execution() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "dockseed", "--version"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0
    assert __version__ in result.stdout

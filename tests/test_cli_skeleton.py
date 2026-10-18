"""Tests for the CLI argument parser, help output, and module entry point."""

import subprocess
import sys
from pathlib import Path

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


def test_cli_subcommands_end_to_end_smoke(tmp_path: Path) -> None:
    (tmp_path / "requirements.txt").write_text("fastapi\nuvicorn\n", encoding="utf-8")
    (tmp_path / "main.py").write_text(
        "from fastapi import FastAPI\napp = FastAPI()\n", encoding="utf-8"
    )

    assert main(["scan", str(tmp_path), "--format", "json"]) == int(ExitCode.SUCCESS)
    assert main(
        [
            "init",
            "--path",
            str(tmp_path),
            "--yes",
            "--no-comments",
            "--python",
            "3.12",
            "--package-manager",
            "pip",
            "--entrypoint",
            "main:app",
            "--port",
            "8000",
        ]
    ) == int(ExitCode.SUCCESS)
    assert main(["check", str(tmp_path)]) == int(ExitCode.SUCCESS)


def test_main_module_execution() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "dockseed", "--version"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0
    assert __version__ in result.stdout

"""Phase 4 tests for CLI init, check, exit codes 0-4, ambiguity prompts, and atomic writes."""

import io
from pathlib import Path

import pytest

from dockseed.cli import main
from dockseed.exceptions import DockseedError, ExitCode
from dockseed.writer import write_text_atomic


def test_init_dry_run_and_overwrite_protection(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (tmp_path / "requirements.txt").write_text("fastapi\nuvicorn\n", encoding="utf-8")
    (tmp_path / "main.py").write_text(
        "from fastapi import FastAPI\napp = FastAPI()\n", encoding="utf-8"
    )

    # 1. Dry-run prints Dockerfile and writes nothing
    code_dry = main(["init", "--path", str(tmp_path), "--dry-run"])
    assert code_dry == int(ExitCode.SUCCESS)
    assert not (tmp_path / "Dockerfile").exists()
    assert "--- Dockerfile (dry-run) ---" in capsys.readouterr().out

    # 2. Normal headless init with --yes writes Dockerfile and .dockerignore
    code_init = main(["init", "--path", str(tmp_path), "--yes"])
    assert code_init == int(ExitCode.SUCCESS)
    assert (tmp_path / "Dockerfile").is_file()
    assert (tmp_path / ".dockerignore").is_file()

    # 3. Running init again without --overwrite returns ExitCode.OVERWRITE_BLOCKED (4)
    code_blocked = main(["init", "--path", str(tmp_path), "--yes"])
    assert code_blocked == int(ExitCode.OVERWRITE_BLOCKED)

    # 4. Running init with --overwrite succeeds (0)
    code_ovr = main(["init", "--path", str(tmp_path), "--yes", "--overwrite"])
    assert code_ovr == int(ExitCode.SUCCESS)


def test_init_headless_ambiguities_exit_code_3(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # 1. Empty project (missing entrypoint) with --yes -> ExitCode 3
    code_no_ep = main(["init", "--path", str(tmp_path), "--yes"])
    assert code_no_ep == int(ExitCode.AMBIGUITY_UNRESOLVED)
    assert "--entrypoint" in capsys.readouterr().err

    # 2. Multiple entrypoints (FastAPI + Celery) with --yes -> ExitCode 3
    (tmp_path / "requirements.txt").write_text("fastapi\nuvicorn\ncelery\n", encoding="utf-8")
    (tmp_path / "api.py").write_text(
        "from fastapi import FastAPI\napp = FastAPI()\n", encoding="utf-8"
    )
    (tmp_path / "worker.py").write_text(
        "from celery import Celery\ncelery_app = Celery('w')\n", encoding="utf-8"
    )
    code_multi_ep = main(["init", "--path", str(tmp_path), "--yes"])
    assert code_multi_ep == int(ExitCode.AMBIGUITY_UNRESOLVED)

    # 3. Multiple package managers (uv.lock + poetry.lock) with --yes -> ExitCode 3
    (tmp_path / "uv.lock").write_text("# uv\n", encoding="utf-8")
    (tmp_path / "poetry.lock").write_text("# poetry\n", encoding="utf-8")
    code_multi_pm = main(["init", "--path", str(tmp_path), "--yes"])
    assert code_multi_pm == int(ExitCode.AMBIGUITY_UNRESOLVED)

    # 4. Conflicting Python constraints with --yes -> ExitCode 3
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nrequires-python = "==3.11.*"\n', encoding="utf-8"
    )
    (tmp_path / ".python-version").write_text("3.13\n", encoding="utf-8")
    code_py_conf = main(["init", "--path", str(tmp_path), "--yes"])
    assert code_py_conf == int(ExitCode.AMBIGUITY_UNRESOLVED)

    # 5. Blocker dependency -> ExitCode 2 (ValidationError)
    (tmp_path / "requirements.txt").write_text("-e ../outside_dir\n", encoding="utf-8")
    code_blocker = main(["init", "--path", str(tmp_path), "--yes"])
    assert code_blocker == int(ExitCode.VALIDATION_FAILED)


def test_init_interactive_tty_prompts(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nrequires-python = "==3.11.*"\n', encoding="utf-8"
    )
    (tmp_path / ".python-version").write_text("3.13\n", encoding="utf-8")
    (tmp_path / "uv.lock").write_text("# uv\n", encoding="utf-8")
    (tmp_path / "poetry.lock").write_text("# poetry\n", encoding="utf-8")
    (tmp_path / "api.py").write_text(
        "from fastapi import FastAPI\napp = FastAPI()\n", encoding="utf-8"
    )
    (tmp_path / "worker.py").write_text(
        "from celery import Celery\ncelery_app = Celery('w')\n", encoding="utf-8"
    )

    # Simulate interactive TTY choosing invalid option first ("99"), then defaults, then "y"
    fake_stdin = io.StringIO("99\n1\n2\n1\ny\n")
    monkeypatch.setattr("sys.stdin", fake_stdin)
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)

    code = main(["init", "--path", str(tmp_path)])
    assert code == int(ExitCode.SUCCESS)
    assert (tmp_path / "Dockerfile").is_file()

    # Simulate user aborting at confirmation prompt ("n")
    fake_abort = io.StringIO("1\n1\n1\nn\n")
    monkeypatch.setattr("sys.stdin", fake_abort)
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    code_abort = main(["init", "--path", str(tmp_path), "--overwrite"])
    assert code_abort == int(ExitCode.SUCCESS)


def test_init_interactive_missing_entrypoint_prompt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "requirements.txt").write_text("requests\n", encoding="utf-8")

    # 1. User enters custom command interactively
    fake_stdin = io.StringIO("python -m http.server 8000\ny\n")
    monkeypatch.setattr("sys.stdin", fake_stdin)
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)

    code = main(["init", "--path", str(tmp_path)])
    assert code == int(ExitCode.SUCCESS)
    assert 'CMD ["python", "-m", "http.server", "8000"]' in (tmp_path / "Dockerfile").read_text(
        encoding="utf-8"
    )

    # 2. User enters empty string when asked for startup command -> AmbiguityError (3)
    fake_empty = io.StringIO("\n")
    monkeypatch.setattr("sys.stdin", fake_empty)
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    code_empty = main(["init", "--path", str(tmp_path), "--overwrite"])
    assert code_empty == int(ExitCode.AMBIGUITY_UNRESOLVED)


def test_check_command_and_atomic_write_error(tmp_path: Path) -> None:
    # Check when no Dockerfile exists -> ExitCode.VALIDATION_FAILED (2)
    assert main(["check", str(tmp_path)]) == int(ExitCode.VALIDATION_FAILED)

    # Check when invalid Dockerfile exists -> ExitCode.VALIDATION_FAILED (2)
    (tmp_path / "Dockerfile").write_text("USER root\nCMD echo hi\n", encoding="utf-8")
    assert main(["check", str(tmp_path)]) == int(ExitCode.VALIDATION_FAILED)

    # Atomic write error when parent directory does not exist
    with pytest.raises(DockseedError, match="Failed to write file"):
        write_text_atomic(tmp_path / "nonexistent_dir" / "Dockerfile", "FROM python:3.12\n")

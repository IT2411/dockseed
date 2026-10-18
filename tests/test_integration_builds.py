"""Opt-in integration tests that build real container images when Docker/Podman is available."""

import shutil
from pathlib import Path

import pytest

from dockseed.cli import main
from dockseed.exceptions import ExitCode


@pytest.mark.integration
def test_real_container_build_basic_script(tmp_path: Path) -> None:
    if not (shutil.which("docker") or shutil.which("podman")):
        pytest.skip("Neither docker nor podman is available on PATH.")

    (tmp_path / ".python-version").write_text("3.11\n", encoding="utf-8")
    (tmp_path / "main.py").write_text(
        'if __name__ == "__main__":\n    print("Hello from container")\n',
        encoding="utf-8",
    )

    assert main(["init", "--path", str(tmp_path), "--yes"]) == int(ExitCode.SUCCESS)
    assert main(["check", str(tmp_path), "--build"]) == int(ExitCode.SUCCESS)

"""Phase 1 tests for project discovery, symlink safety, and manifest loading."""

from pathlib import Path

import pytest

from dockseed.exceptions import ValidationError
from dockseed.scanner import discover_project


def test_discover_nonexistent_or_file_path(tmp_path: Path) -> None:
    with pytest.raises(ValidationError, match="does not exist"):
        discover_project(tmp_path / "missing")

    file_path = tmp_path / "somefile.txt"
    file_path.write_text("hello", encoding="utf-8")
    with pytest.raises(ValidationError, match="not a directory"):
        discover_project(file_path)


def test_discover_excludes_irrelevant_dirs_and_protects_dotenv(tmp_path: Path) -> None:
    (tmp_path / ".venv").mkdir()
    (tmp_path / ".venv" / "ignored.py").write_text("x = 1", encoding="utf-8")
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git" / "config").write_text("x = 1", encoding="utf-8")
    (tmp_path / "pkg.egg-info").mkdir()
    (tmp_path / "pkg.egg-info" / "PKG-INFO").write_text("x = 1", encoding="utf-8")

    (tmp_path / ".env").write_text("SECRET_KEY=supersecret", encoding="utf-8")
    (tmp_path / ".env.production").write_text("DB_PASS=secret", encoding="utf-8")
    (tmp_path / ".env.example").write_text("SECRET_KEY=changeme", encoding="utf-8")

    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "main.py").write_text("print('hi')", encoding="utf-8")

    ctx = discover_project(tmp_path)

    assert ctx.has_dotenv is True
    assert ctx.has_file("app/main.py")
    assert ctx.has_file(".env.example")
    assert not ctx.has_file(".env")
    assert not ctx.has_file(".env.production")
    assert not ctx.has_file(".venv/ignored.py")
    assert not ctx.has_file(".git/config")

    # Attempting to read .env directly via read_text_safe must raise ValueError
    with pytest.raises(ValueError, match="strictly prohibited"):
        ctx.read_text_safe(".env")
    with pytest.raises(ValueError, match="strictly prohibited"):
        ctx.read_text_safe(".env.production")

    assert ctx.read_text_safe(".env.example") == "SECRET_KEY=changeme"
    assert ctx.read_text_safe("nonexistent.txt") is None


def test_discover_rejects_external_symlinks(tmp_path: Path) -> None:
    outside_dir = tmp_path / "outside"
    outside_dir.mkdir()
    outside_file = outside_dir / "secret.txt"
    outside_file.write_text("outside secret", encoding="utf-8")

    project_dir = tmp_path / "project"
    project_dir.mkdir()
    (project_dir / "main.py").write_text("x = 1", encoding="utf-8")

    # Create symlinks pointing outside project root
    (project_dir / "ext_file.txt").symlink_to(outside_file)
    (project_dir / "ext_dir").symlink_to(outside_dir)
    (project_dir / "broken_link.txt").symlink_to(outside_dir / "does_not_exist.txt")

    ctx = discover_project(project_dir)

    assert ctx.has_file("main.py")
    assert not ctx.has_file("ext_file.txt")
    assert not ctx.has_file("ext_dir/secret.txt")
    assert any("outside project root" in w for w in ctx.warnings)
    assert ctx.read_text_safe("../outside/secret.txt") is None


def test_discover_invalid_pyproject_toml(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text("[project\nname = 'broken'", encoding="utf-8")
    with pytest.raises(ValidationError, match="Invalid TOML"):
        discover_project(tmp_path)

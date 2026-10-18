"""Safe, deterministic filesystem discovery and manifest loading for Dockseed."""

import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from dockseed.exceptions import ValidationError

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover
    import tomli as tomllib

EXCLUDED_DIRS: frozenset[str] = frozenset(
    {
        ".git",
        ".hg",
        ".svn",
        ".venv",
        "venv",
        "env",
        "__pycache__",
        ".pytest_cache",
        ".ruff_cache",
        ".mypy_cache",
        ".tox",
        ".nox",
        "node_modules",
        "build",
        "dist",
        "htmlcov",
        ".eggs",
    }
)


@dataclass
class ScanContext:
    """Holds discovered project files and parsed root manifests without executing code."""

    root: Path
    files: list[Path] = field(default_factory=list)
    pyproject_data: dict[str, Any] | None = None
    warnings: list[str] = field(default_factory=list)
    has_dotenv: bool = False

    def has_file(self, relative_posix: str) -> bool:
        """Return True if a relative POSIX path exists in the discovered files."""
        target = Path(relative_posix)
        return target in self.files

    def read_text_safe(self, relative_posix: str) -> str | None:
        """Read a UTF-8 text file safely inside the project root, forbidding .env files."""
        name = Path(relative_posix).name
        if name == ".env" or (
            name.startswith(".env.") and not name.endswith((".example", ".template", ".sample"))
        ):
            raise ValueError("Reading secret .env files is strictly prohibited.")

        full_path = (self.root / relative_posix).resolve()
        if not full_path.is_relative_to(self.root):
            self.warnings.append(
                f"Skipped reading '{relative_posix}': resolves outside project root."
            )
            return None

        if not full_path.is_file():
            return None

        try:
            return full_path.read_text(encoding="utf-8")
        except OSError as exc:
            self.warnings.append(f"Could not read '{relative_posix}': {exc}")
            return None


def discover_project(path: Path) -> ScanContext:
    """Traverse a project directory deterministically and load pyproject.toml if present."""
    if not path.exists():
        raise ValidationError(f"Project path does not exist: {path}")
    if not path.is_dir():
        raise ValidationError(f"Project path is not a directory: {path}")

    root = path.resolve()
    ctx = ScanContext(root=root)
    discovered: list[Path] = []

    for current_root, dirs, files in os.walk(root, topdown=True, followlinks=False):
        current_path = Path(current_root)

        # Filter and sort directories in-place for deterministic traversal
        kept_dirs: list[str] = []
        for d in sorted(dirs):
            if d in EXCLUDED_DIRS or d.endswith(".egg-info"):
                continue
            dir_path = current_path / d
            if dir_path.is_symlink():
                try:
                    resolved_dir = dir_path.resolve()
                    if not resolved_dir.is_relative_to(root):
                        rel = dir_path.relative_to(root).as_posix()
                        ctx.warnings.append(
                            f"Ignored symlinked directory outside project root: {rel}"
                        )
                        continue
                except OSError:
                    continue
            kept_dirs.append(d)
        dirs[:] = kept_dirs

        for f in sorted(files):
            file_path = current_path / f
            rel_path = file_path.relative_to(root)

            if file_path.is_symlink():
                try:
                    resolved_file = file_path.resolve()
                    if not resolved_file.is_relative_to(root):
                        ctx.warnings.append(
                            f"Ignored symlinked file outside project root: {rel_path.as_posix()}"
                        )
                        continue
                except OSError:
                    ctx.warnings.append(f"Ignored broken symlink: {rel_path.as_posix()}")
                    continue

            if f == ".env" or (
                f.startswith(".env.") and not f.endswith((".example", ".template", ".sample"))
            ):
                ctx.has_dotenv = True
                continue

            discovered.append(rel_path)

    ctx.files = sorted(discovered, key=lambda p: p.as_posix())

    if ctx.has_file("pyproject.toml"):
        raw_toml = ctx.read_text_safe("pyproject.toml")
        if raw_toml is not None:
            try:
                ctx.pyproject_data = tomllib.loads(raw_toml)
            except tomllib.TOMLDecodeError as exc:
                raise ValidationError(f"Invalid TOML in pyproject.toml: {exc}") from exc

    return ctx

"""Safe, atomic file operations and overwrite protection for Dockseed."""

import os
import tempfile
from pathlib import Path

from dockseed.exceptions import DockseedError, OverwriteBlockedError


def write_text_atomic(target: Path, content: str) -> None:
    """Write text to target path atomically using a temporary file in the same directory."""
    parent = target.parent.resolve()
    fd: int | None = None
    tmp_path: Path | None = None
    try:
        fd, raw_tmp = tempfile.mkstemp(
            prefix=f".{target.name}.",
            suffix=".tmp",
            dir=str(parent),
            text=True,
        )
        tmp_path = Path(raw_tmp)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            fd = None
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_path, target)
    except OSError as exc:
        if fd is not None:  # pragma: no cover
            os.close(fd)
        if tmp_path is not None and tmp_path.exists():
            tmp_path.unlink(missing_ok=True)
        raise DockseedError(f"Failed to write file '{target}': {exc}") from exc


def write_project_files(
    root: Path,
    dockerfile_content: str,
    dockerignore_content: str,
    overwrite: bool = False,
) -> list[Path]:
    """Write Dockerfile and .dockerignore safely, respecting overwrite policy."""
    dockerfile_path = root / "Dockerfile"
    dockerignore_path = root / ".dockerignore"

    if not overwrite and dockerfile_path.exists():
        raise OverwriteBlockedError(
            f"'{dockerfile_path}' already exists. Pass '--overwrite' to replace it."
        )

    written: list[Path] = []
    write_text_atomic(dockerfile_path, dockerfile_content)
    written.append(dockerfile_path)

    # Preserve existing .dockerignore unless --overwrite is explicitly passed
    if overwrite or not dockerignore_path.exists():
        write_text_atomic(dockerignore_path, dockerignore_content)
        written.append(dockerignore_path)

    return written

"""Safe local virtual-environment inspection for dependency mismatch diagnostics."""

from pathlib import Path

from dockseed.detectors.package_manager import normalize_pkg_name
from dockseed.models import ProjectModel

CRITICAL_RUNTIME_PACKAGES: frozenset[str] = frozenset(
    {
        "fastapi",
        "flask",
        "django",
        "streamlit",
        "gradio",
        "celery",
        "uvicorn",
        "gunicorn",
        "granian",
        "daphne",
        "psycopg2",
        "psycopg2-binary",
        "mysqlclient",
        "redis",
        "sqlalchemy",
        "pydantic",
    }
)


def _find_project_site_packages(root: Path) -> list[Path]:
    """Locate site-packages directories inside project-local virtual environments."""
    site_dirs: list[Path] = []
    for venv_name in (".venv", "venv", "env"):
        venv_dir = root / venv_name
        if not venv_dir.is_dir() or venv_dir.is_symlink():
            continue
        # POSIX: .venv/lib/python3.x/site-packages
        lib_dir = venv_dir / "lib"
        if lib_dir.is_dir():
            for py_dir in sorted(lib_dir.glob("python*")):
                sp = py_dir / "site-packages"
                if sp.is_dir():
                    site_dirs.append(sp)
        # Windows: .venv/Lib/site-packages
        win_sp = venv_dir / "Lib" / "site-packages"
        if win_sp.is_dir():
            site_dirs.append(win_sp)
    return site_dirs


def discover_venv_packages(root: Path) -> set[str]:
    """Read installed package names from local .venv dist-info directories safely."""
    installed: set[str] = set()
    for sp_dir in _find_project_site_packages(root):
        for dist_info in sorted(sp_dir.glob("*.dist-info")):
            meta_file = dist_info / "METADATA"
            if meta_file.is_file():
                try:
                    for line in meta_file.read_text(encoding="utf-8", errors="ignore").splitlines():
                        if line.startswith("Name:"):
                            pkg_name = line.split(":", 1)[1].strip()
                            if pkg_name:
                                installed.add(normalize_pkg_name(pkg_name))
                            break
                except OSError:  # pragma: no cover
                    continue
            else:
                # Fallback to parsing <name>-<version>.dist-info folder name
                stem = dist_info.name.removesuffix(".dist-info")
                parts = stem.split("-", 1)
                if parts[0]:
                    installed.add(normalize_pkg_name(parts[0]))
    return installed


def inspect_environment(model: ProjectModel) -> None:
    """Compare local virtual environment packages against declared runtime_dependencies."""
    installed_in_venv = discover_venv_packages(model.root)
    if not installed_in_venv:
        return

    declared = set(model.runtime_dependencies)
    undeclared_critical = sorted((installed_in_venv & CRITICAL_RUNTIME_PACKAGES) - declared)

    if undeclared_critical:
        pkg_list = ", ".join(undeclared_critical)
        warn_msg = (
            f"Local virtual environment has runtime package(s) installed that are "
            f"missing from project manifests: {pkg_list}."
        )
        if warn_msg not in model.warnings:
            model.warnings.append(warn_msg)

"""Heuristic mapping from Python packages to Debian (-slim) apt system packages."""

from dockseed.models import ProjectModel

# Deterministic mapping of normalized Python package names to Debian apt-get packages
NATIVE_APT_MAPPING: dict[str, tuple[str, ...]] = {
    "psycopg2": ("gcc", "libpq-dev"),
    "mysqlclient": ("build-essential", "default-libmysqlclient-dev", "pkg-config"),
    "opencv-python": ("libgl1", "libglib2.0-0"),
    "opencv-contrib-python": ("libgl1", "libglib2.0-0"),
    "pyaudio": ("gcc", "portaudio19-dev"),
    "python-ldap": ("gcc", "libldap2-dev", "libsasl2-dev"),
    "xmlsec": ("gcc", "libxml2-dev", "libxmlsec1-dev", "libxmlsec1-openssl", "pkg-config"),
    "pycairo": ("gcc", "libcairo2-dev", "pkg-config"),
    "weasyprint": ("libpango-1.0-0", "libharfbuzz0b", "libpangoft2-1.0-0"),
    "git+https": ("git",),
}


def detect_native_dependencies(model: ProjectModel) -> None:
    """Populate model.system_dependencies based on declared runtime_dependencies."""
    apt_packages: set[str] = set()

    for pkg in model.runtime_dependencies:
        if pkg in NATIVE_APT_MAPPING:
            apt_packages.update(NATIVE_APT_MAPPING[pkg])

        if pkg == "psycopg2":
            tip = (
                "Package 'psycopg2' requires compiling from source ('gcc', 'libpq-dev'); "
                "consider 'psycopg2-binary' for smaller images."
            )
            if tip not in model.warnings:
                model.warnings.append(tip)

    model.system_dependencies = sorted(apt_packages)

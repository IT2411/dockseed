"""Detectors for Python version, package managers, native deps, frameworks, and entrypoints."""

from dockseed.detectors.native_deps import detect_native_dependencies
from dockseed.detectors.package_manager import detect_package_manager
from dockseed.detectors.python_version import detect_python_version

__all__ = [
    "detect_native_dependencies",
    "detect_package_manager",
    "detect_python_version",
]

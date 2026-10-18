"""Detectors for Python version, package managers, native deps, frameworks, and entrypoints."""

from dockseed.detectors.entrypoint import detect_entrypoint
from dockseed.detectors.framework import (
    PythonFileASTInfo,
    analyze_python_file,
    detect_framework,
    scan_python_sources,
)
from dockseed.detectors.native_deps import detect_native_dependencies
from dockseed.detectors.package_manager import detect_package_manager
from dockseed.detectors.python_version import detect_python_version

__all__ = [
    "PythonFileASTInfo",
    "analyze_python_file",
    "detect_entrypoint",
    "detect_framework",
    "detect_native_dependencies",
    "detect_package_manager",
    "detect_python_version",
    "scan_python_sources",
]

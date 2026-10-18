"""Static and build validators for Dockseed configurations."""

from dockseed.validators.dockerfile import ValidationReport, validate_dockerfile

__all__ = [
    "ValidationReport",
    "validate_dockerfile",
]

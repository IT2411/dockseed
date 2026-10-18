"""Custom exception hierarchy and CLI exit code mappings for Dockseed."""

from enum import IntEnum


class ExitCode(IntEnum):
    """Standardized CLI exit codes per Dockseed SRS."""

    SUCCESS = 0
    GENERAL_ERROR = 1
    VALIDATION_FAILED = 2
    AMBIGUITY_UNRESOLVED = 3
    OVERWRITE_BLOCKED = 4


class DockseedError(Exception):
    """Base exception for all known Dockseed errors."""

    exit_code: ExitCode = ExitCode.GENERAL_ERROR

    def __init__(self, message: str, exit_code: ExitCode | None = None) -> None:
        super().__init__(message)
        if exit_code is not None:
            self.exit_code = exit_code


class ValidationError(DockseedError):
    """Raised when static or build validation fails, or a project is invalid."""

    exit_code = ExitCode.VALIDATION_FAILED


class AmbiguityError(DockseedError):
    """Raised when a critical ambiguity cannot be resolved in headless/non-TTY mode."""

    exit_code = ExitCode.AMBIGUITY_UNRESOLVED


class OverwriteBlockedError(DockseedError):
    """Raised when target output files exist and --overwrite was not provided."""

    exit_code = ExitCode.OVERWRITE_BLOCKED

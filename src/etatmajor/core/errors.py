"""Exception hierarchy of the ETAT-MAJOR platform.

All errors raised by the platform inherit from :class:`EtatMajorError` so that
operator interfaces and CI pipelines can distinguish platform faults from
unexpected bugs.
"""

from __future__ import annotations


class EtatMajorError(Exception):
    """Base class of every error raised by the platform."""


class ConfigurationError(EtatMajorError):
    """Raised when a configuration file or object is invalid."""


class DataValidationError(EtatMajorError):
    """Raised when a market data dataset is malformed or inconsistent.

    The exception carries the list of individual problems so that an operator
    can fix the source file in a single pass.
    """

    def __init__(self, message: str, issues: list[str] | None = None) -> None:
        super().__init__(message)
        self.issues: list[str] = list(issues or [])


class RiskRejected(EtatMajorError):
    """Raised when the risk authority refuses an operation."""

    def __init__(self, message: str, reason: str = "") -> None:
        super().__init__(message)
        self.reason = reason


class ExecutionError(EtatMajorError):
    """Raised when the execution layer cannot honour a valid request."""


class StrategyError(EtatMajorError):
    """Raised when a strategy violates the strategy contract."""

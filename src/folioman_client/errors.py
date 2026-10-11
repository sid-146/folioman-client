"""Exception hierarchy for the Folioman client.

Keep exceptions focused, practical, and small.
"""

from __future__ import annotations

from typing import Any


class FoliomanError(Exception):
    """Base exception for all Folioman client errors."""


class FoliomanAuthError(FoliomanError):
    """Raised when authentication fails (invalid credentials, expired/rejected token refresh)."""


class FoliomanNotFoundError(FoliomanError):
    """Raised when the requested resource is not found."""


class FoliomanParseError(FoliomanError):
    """Raised when statement parsing fails or document shape is unsupported."""


class FoliomanPasswordError(FoliomanParseError):
    """Raised when the PDF password is wrong or missing."""


class FoliomanFeedError(FoliomanError):
    """Raised when an external market price feed fails."""


class FoliomanDatabaseError(FoliomanError):
    """Raised when a database connection or integrity constraint fails."""


class FernetKeyUnavailable(FoliomanError):
    """Raised when no valid Fernet key can be resolved for PAN encryption."""


class FoliomanAPIError(FoliomanError):
    """Raised when the Folioman API returns an error response (HTTP 4xx/5xx).

    Attributes:
        status_code: The HTTP status code returned by the server.
        response_data: Parsed response payload or raw error details, if available.
    """

    def __init__(
        self,
        message: str,
        status_code: int,
        response_data: Any | None = None,
    ) -> None:
        """Initialize FoliomanAPIError with message, status code, and optional payload.

        Args:
            message: Human-readable description of the error.
            status_code: HTTP response status code (e.g., 400, 500).
            response_data: Deserialized JSON payload or raw text error from the server.
        """
        super().__init__(message)
        self.status_code = status_code
        self.response_data = response_data

    def __str__(self) -> str:
        base = super().__str__()
        if self.response_data:
            return f"[{self.status_code}] {base} - {self.response_data}"
        return f"[{self.status_code}] {base}"


__all__ = [
    "FoliomanError",
    "FoliomanAuthError",
    "FoliomanNotFoundError",
    "FoliomanParseError",
    "FoliomanPasswordError",
    "FoliomanFeedError",
    "FoliomanDatabaseError",
    "FernetKeyUnavailable",
    "FoliomanAPIError",
]

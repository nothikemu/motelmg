"""Application exception hierarchy.

Services raise these exceptions with messages that are safe to show to end
users. The UI layer catches ``MotelError`` subclasses and displays the message;
anything else is treated as an unexpected error and logged with a traceback.
"""

from __future__ import annotations


class MotelError(Exception):
    """Base class for all expected, user-facing errors."""

    title = "Unable to complete action"

    def __init__(self, message: str, *, details: str | None = None):
        super().__init__(message)
        self.message = message
        self.details = details

    def __str__(self) -> str:  # pragma: no cover - trivial
        return self.message


class ValidationError(MotelError):
    """Input failed validation. ``field_errors`` maps form keys to messages."""

    title = "Please check the information entered"

    def __init__(self, message: str | None = None, *, field: str | None = None,
                 field_errors: dict[str, str] | None = None):
        errors = dict(field_errors or {})
        if field and message:
            errors.setdefault(field, message)
        if not message:
            message = next(iter(errors.values()), "Invalid input.")
        super().__init__(message)
        self.field_errors = errors


class NotFoundError(MotelError):
    title = "Not found"


class ConflictError(MotelError):
    """The action conflicts with the current state (e.g. double booking)."""

    title = "Conflict"


class PermissionDenied(MotelError):
    title = "Permission required"


class AuthenticationError(MotelError):
    title = "Sign-in failed"


class DatabaseError(MotelError):
    title = "Database error"

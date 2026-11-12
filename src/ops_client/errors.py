"""Errors raised by the client. Callers catch `OpsError` or a specific subclass."""

from __future__ import annotations


class OpsError(Exception):
    """Base class for every error this package raises on purpose."""


class AuthError(OpsError):
    """401: no token, a wrong token, or no token configured."""


class NotFoundError(OpsError):
    """404."""


class ValidationError(OpsError):
    """422: the request was rejected as invalid."""


class ConflictError(OpsError):
    """409: the version is stale (or the transition is not allowed). Never retried.

    `current` is the stored row, `error` the API's reason (e.g. "version_conflict").
    """

    def __init__(self, message: str, current: dict | None = None, error: str = "") -> None:
        super().__init__(message)
        self.current = current
        self.error = error


class RateLimitError(OpsError):
    """429 after all retries were used."""


class ServerError(OpsError):
    """5xx or a connection error after all retries were used."""


class IncompleteWindowError(OpsError):
    """A window returned fewer unique ids than the API's `meta.count` on 3 reads."""

    def __init__(self, window: tuple[str, str], expected: int, got: int) -> None:
        super().__init__(
            f"window {window[0]}..{window[1]}: expected {expected} rows, got {got}"
        )
        self.window = window
        self.expected = expected
        self.got = got

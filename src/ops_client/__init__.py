"""Client for the ops-console mock PSA API."""

from .client import OpsClient
from .errors import (
    AuthError,
    ConflictError,
    IncompleteWindowError,
    NotFoundError,
    OpsError,
    RateLimitError,
    ServerError,
    ValidationError,
)
from .models import Approval, Project, Task, TimeEntry, User

__version__ = "0.1.0"

__all__ = [
    "Approval",
    "AuthError",
    "ConflictError",
    "IncompleteWindowError",
    "NotFoundError",
    "OpsClient",
    "OpsError",
    "Project",
    "RateLimitError",
    "ServerError",
    "Task",
    "TimeEntry",
    "User",
    "ValidationError",
    "__version__",
]

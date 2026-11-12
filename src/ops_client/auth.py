"""Token lookup: keyring first, then the environment. The token is never printed or logged."""

from __future__ import annotations

import os

import keyring
from keyring.errors import KeyringError

from .errors import AuthError

SERVICE = "ops-console"
USERNAME = "api_token"
ENV_VAR = "OPS_API_TOKEN"


def get_token() -> str:
    """keyring("ops-console", "api_token"), then env OPS_API_TOKEN, else AuthError.

    A machine with no keyring backend (CI, containers) raises a KeyringError; that is treated
    as "not in keyring" so the environment variable still works.
    """
    try:
        token = keyring.get_password(SERVICE, USERNAME)
    except KeyringError:
        token = None
    if token:
        return token
    token = os.environ.get(ENV_VAR)
    if token:
        return token
    raise AuthError(f"no token: set it in keyring ({SERVICE}/{USERNAME}) or env {ENV_VAR}")

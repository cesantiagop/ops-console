"""One request with retries. Rules: docs/adr/0003-reading-changing-data.md section 4."""

from __future__ import annotations

import logging
import random
import time
from collections.abc import Callable
from typing import Any

import httpx

from .errors import (
    AuthError,
    ConflictError,
    NotFoundError,
    RateLimitError,
    ServerError,
    ValidationError,
)

log = logging.getLogger("ops_client")

MAX_WAIT = 30


def _detail(response: httpx.Response) -> str:
    try:
        body = response.json()
    except ValueError:
        return response.text[:200]
    if isinstance(body, dict):
        return str(body.get("detail") or body.get("error") or body)[:200]
    return str(body)[:200]


def _retry_after(response: httpx.Response) -> int:
    try:
        return int(response.headers.get("Retry-After") or 1)
    except ValueError:
        return 1


def request(
    http: httpx.Client,
    method: str,
    path: str,
    *,
    token: str,
    params: dict[str, Any] | None = None,
    json: dict[str, Any] | None = None,
    max_retries: int = 5,
    sleep: Callable[[float], None] = time.sleep,
    rng: random.Random | None = None,
) -> dict:
    """Send one request and return the parsed JSON body, or raise a mapped error.

    429 waits Retry-After (cap 30 s). 5xx and transport errors back off exponentially with
    jitter. 401/404/409/422 raise at once. Retry log lines carry no headers.
    """
    rng = rng or random.Random()
    headers = {"Authorization": f"Bearer {token}"}
    attempt = 0
    while True:
        status = 0
        try:
            response = http.request(method, path, params=params, json=json, headers=headers)
            status = response.status_code
        except httpx.TransportError:
            response = None

        if response is not None and status < 400:
            return response.json()
        if response is not None:
            if status == 401:
                raise AuthError(_detail(response))
            if status == 404:
                raise NotFoundError(_detail(response))
            if status == 422:
                raise ValidationError(_detail(response))
            if status == 409:
                body = response.json()
                raise ConflictError(
                    f"conflict: {body.get('error', 'conflict')}",
                    current=body.get("current"),
                    error=body.get("error", ""),
                )

        rate_limited = status == 429
        retryable = rate_limited or status >= 500 or response is None
        if not retryable:
            raise ServerError(f"unexpected status {status}: {_detail(response)}")
        if attempt >= max_retries:
            if rate_limited:
                raise RateLimitError(f"rate limited after {max_retries} retries")
            raise ServerError(f"server error (status {status or 'no response'}) after retries")

        if rate_limited:
            wait: float = min(_retry_after(response), MAX_WAIT)
        else:
            wait = min(0.5 * 2**attempt, MAX_WAIT) * (0.5 + rng.random())
        attempt += 1
        log.info(
            "retry %s %s status=%s attempt=%d wait=%.2f",
            method, path, status or "transport-error", attempt, wait,
        )
        sleep(wait)

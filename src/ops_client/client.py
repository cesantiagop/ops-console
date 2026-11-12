"""OpsClient: the facade over the mock PSA API."""

from __future__ import annotations

import random
import time
from collections.abc import Callable, Iterator
from datetime import date
from typing import Any

import httpx

from . import auth, paging
from . import http as http_mod
from .models import MODELS, Approval, Project, _Row


class OpsClient:
    """Typed, retrying, drift-safe client. The token is never in `repr` or logs."""

    def __init__(
        self,
        base_url: str = "http://127.0.0.1:8000",
        token: str | None = None,
        http: httpx.Client | None = None,
        max_retries: int = 5,
        sleep: Callable[[float], None] = time.sleep,
        rng: random.Random | None = None,
    ) -> None:
        self.base_url = base_url
        self._token = token if token is not None else auth.get_token()
        self._http = http if http is not None else httpx.Client(base_url=base_url, timeout=30)
        self.max_retries = max_retries
        self._sleep = sleep
        self._rng = rng

    def __repr__(self) -> str:
        return f"OpsClient(base_url={self.base_url!r})"

    # -- plumbing ----------------------------------------------------------------------------

    def _call(self, method: str, path: str, **kwargs: Any) -> dict:
        return http_mod.request(
            self._http, method, path, token=self._token, max_retries=self.max_retries,
            sleep=self._sleep, rng=self._rng, **kwargs,
        )

    def _fetch(self, resource: str, params: dict[str, Any]) -> dict:
        return self._call("GET", f"/v1/{resource}", params=params)

    @staticmethod
    def _model(resource: str) -> type[_Row]:
        try:
            return MODELS[resource]
        except KeyError:
            raise ValueError(
                f"unknown resource {resource!r}; use one of {', '.join(MODELS)}"
            ) from None

    # -- reads -------------------------------------------------------------------------------

    def health(self) -> dict:
        return self._call("GET", "/v1/health")

    def get(self, resource: str, id: int) -> _Row:
        model = self._model(resource)
        body = self._call("GET", f"/v1/{resource}/{id}")
        return model(**body["results"][0])

    def list(self, resource: str, **filters: Any) -> Iterator[_Row]:
        """All pages, per_page=200, order id:asc."""
        model = self._model(resource)
        params = {**filters, "order": "id:asc"}
        for envelope in paging.iter_pages(self._fetch, resource, params):
            for row in envelope["results"]:
                yield model(**row)

    def extract(
        self, resource: str, start: date, end: date, window_days: int = 7
    ) -> list[_Row]:
        """Drift-proof full read over `created_between` windows (ADR 0003). Sorted by id."""
        model = self._model(resource)
        if start > end:
            raise ValueError("start must not be after end")
        rows = paging.read_windowed(self._fetch, resource, start, end, window_days)
        return [model(**row) for row in rows]

    # -- writes ------------------------------------------------------------------------------

    def patch_project(self, id: int, version: int, **changes: Any) -> Project:
        body = self._call("PATCH", f"/v1/projects/{id}", json={"version": version, **changes})
        return Project(**body["results"][0])

    def approve(self, id: int, version: int, approver_id: int) -> Approval:
        return self._decide("approve", id, version, approver_id)

    def reject(self, id: int, version: int, approver_id: int) -> Approval:
        return self._decide("reject", id, version, approver_id)

    def _decide(self, action: str, id: int, version: int, approver_id: int) -> Approval:
        body = self._call(
            "POST", f"/v1/approvals/{id}/{action}",
            json={"version": version, "approver_id": approver_id},
        )
        return Approval(**body["results"][0])

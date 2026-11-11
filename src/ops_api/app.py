"""The mock PSA API. Conventions: docs/adr/0002-mock-api-conventions.md."""

import hmac
import random
import sqlite3
from collections.abc import Iterator
from datetime import date
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Request
from fastapi import Body as FastAPIBody
from fastapi.responses import JSONResponse

from . import __version__, queries
from .db import connect, now_iso


def _envelope(rows: list[dict], meta: dict) -> dict:
    return {"results": rows, "meta": meta}


def _single(row: dict) -> dict:
    return _envelope([row], {"count": 1, "page": 1, "per_page": 1, "page_count": 1})


def _conflict(error: str, current: dict | None) -> JSONResponse:
    return JSONResponse({"error": error, "current": current}, status_code=409)


def _unprocessable(message: str) -> HTTPException:
    return HTTPException(status_code=422, detail=message)


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _check_version(body: dict) -> int:
    if not _is_int(body.get("version")):
        raise _unprocessable("version (integer) is required")
    return body["version"]


def _check_project_changes(changes: dict) -> None:
    unknown = sorted(set(changes) - set(queries.PROJECT_PATCH_COLUMNS))
    if unknown:
        raise _unprocessable(f"fields not allowed: {', '.join(unknown)}")
    if not changes:
        raise _unprocessable("no fields to change")
    if "name" in changes and not (isinstance(changes["name"], str) and changes["name"].strip()):
        raise _unprocessable("name must be a non-empty string")
    if "status" in changes and changes["status"] not in queries.PROJECT_STATUSES:
        raise _unprocessable(f"status must be one of {', '.join(queries.PROJECT_STATUSES)}")
    if "budget_cents" in changes and not (
        _is_int(changes["budget_cents"]) and changes["budget_cents"] >= 0
    ):
        raise _unprocessable("budget_cents must be a non-negative integer (cents)")
    if changes.get("end_date") is not None:
        try:
            date.fromisoformat(str(changes["end_date"]))
        except ValueError:
            raise _unprocessable("end_date must be YYYY-MM-DD or null") from None
        if not isinstance(changes["end_date"], str) or len(changes["end_date"]) != 10:
            raise _unprocessable("end_date must be YYYY-MM-DD or null")


def create_app(
    db_path: str | Path,
    token: str,
    chaos_rows: int = 0,
    fault_rate: float = 0.0,
    rng_seed: int = 0,
) -> FastAPI:
    """Build the API. `chaos_rows` and `fault_rate` switch on fault injection (off by default)."""
    app = FastAPI(title="ops-console mock PSA API", version=__version__)
    rng = random.Random(rng_seed)

    def get_conn() -> Iterator[sqlite3.Connection]:
        conn = connect(db_path)
        try:
            yield conn
        finally:
            conn.close()

    def guard(request: Request) -> None:
        """Auth first, then the random 429."""
        header = request.headers.get("Authorization", "")
        scheme, _, supplied = header.partition(" ")
        if scheme.lower() != "bearer" or not hmac.compare_digest(
            supplied.encode(), token.encode()
        ):
            raise HTTPException(
                status_code=401, detail="missing or wrong token",
                headers={"WWW-Authenticate": "Bearer"},
            )
        if fault_rate > 0 and rng.random() < fault_rate:
            raise HTTPException(
                status_code=429, detail="rate limit (injected)", headers={"Retry-After": "1"}
            )

    @app.get("/v1/health")
    def health() -> dict:
        return {"status": "ok", "version": __version__}

    Conn = Annotated[sqlite3.Connection, Depends(get_conn)]
    Body = Annotated[dict, FastAPIBody()]

    v1 = APIRouter(prefix="/v1", dependencies=[Depends(guard)])

    def known(resource: str) -> str:
        if resource not in queries.FILTERS:
            raise HTTPException(status_code=404, detail=f"unknown resource '{resource}'")
        return resource

    @v1.get("/{resource}")
    def list_resource(
        resource: str, request: Request, conn: Conn
    ) -> dict:
        known(resource)
        try:
            query = queries.parse_list_query(resource, dict(request.query_params))
        except queries.QueryError as exc:
            raise _unprocessable(str(exc)) from None
        if resource == "time_entries" and chaos_rows > 0:
            ids = [r[0] for r in conn.execute("SELECT id FROM time_entries ORDER BY id")]
            picked = rng.sample(ids, min(chaos_rows, len(ids)))
            queries.touch_rows(conn, resource, picked, now_iso())
        rows, meta = queries.list_rows(conn, resource, query)
        return _envelope(rows, meta)

    @v1.get("/{resource}/{row_id}")
    def get_resource(
        resource: str, row_id: int, conn: Conn
    ) -> dict:
        row = queries.get_row(conn, known(resource), row_id)
        if row is None:
            raise HTTPException(status_code=404, detail=f"{resource} {row_id} not found")
        return _single(row)

    @v1.patch("/projects/{row_id}")
    def patch_project(
        row_id: int, body: Body, conn: Conn
    ):
        version = _check_version(body)
        changes = {k: v for k, v in body.items() if k != "version"}
        _check_project_changes(changes)
        current = queries.get_row(conn, "projects", row_id)
        if current is None:
            raise HTTPException(status_code=404, detail=f"projects {row_id} not found")
        if not queries.update_row(conn, "projects", row_id, version, changes, now_iso()):
            current = queries.get_row(conn, "projects", row_id)
            return _conflict("version_conflict", current)
        return _single(queries.get_row(conn, "projects", row_id))

    def decide(row_id: int, body: dict, conn: sqlite3.Connection, status: str):
        version = _check_version(body)
        approver_id = body.get("approver_id")
        if not _is_int(approver_id):
            raise _unprocessable("approver_id (integer) is required")
        if queries.get_row(conn, "users", approver_id) is None:
            raise _unprocessable(f"approver_id {approver_id} is not a user")
        current = queries.get_row(conn, "approvals", row_id)
        if current is None:
            raise HTTPException(status_code=404, detail=f"approvals {row_id} not found")
        if current["version"] != version:
            return _conflict("version_conflict", current)
        if current["status"] != "submitted":
            return _conflict("invalid_transition", current)
        now = now_iso()
        changes = {"status": status, "approver_id": approver_id, "decided_at": now}
        if not queries.update_row(conn, "approvals", row_id, version, changes, now):
            current = queries.get_row(conn, "approvals", row_id)
            return _conflict("version_conflict", current)
        return _single(queries.get_row(conn, "approvals", row_id))

    @v1.post("/approvals/{row_id}/approve")
    def approve(row_id: int, body: Body, conn: Conn):
        return decide(row_id, body, conn, "approved")

    @v1.post("/approvals/{row_id}/reject")
    def reject(row_id: int, body: Body, conn: Conn):
        return decide(row_id, body, conn, "rejected")

    app.include_router(v1)
    return app


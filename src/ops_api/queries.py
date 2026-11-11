"""SQL builders. Column and order names come from whitelists; values are always bound parameters."""

from __future__ import annotations

import math
import sqlite3
from dataclasses import dataclass, field
from datetime import date, datetime

from .db import TABLES, iso_z

DEFAULT_PER_PAGE = 50
MAX_PER_PAGE = 200

ORDER_FIELDS = ("id", "created_at", "updated_at")
ORDER_DIRS = {"asc": "ASC", "desc": "DESC"}

# Which list filters apply to which resource.
FILTERS = {
    "users": {"ids", "created_between", "updated_since"},
    "projects": {"ids", "created_between", "updated_since", "status"},
    "tasks": {"ids", "created_between", "updated_since", "project_id"},
    "time_entries": {
        "ids", "created_between", "updated_since", "user_id", "project_id", "date_between",
    },
    "approvals": {
        "ids", "created_between", "updated_since", "user_id", "status", "date_between",
    },
}
# The column that `date_between` filters.
DATE_COLUMN = {"time_entries": "date_performed", "approvals": "week_start"}
PAGING_PARAMS = {"page", "per_page", "order"}

# PATCH /projects whitelist.
PROJECT_PATCH_COLUMNS = ("name", "status", "budget_cents", "end_date")
PROJECT_STATUSES = ("active", "on_hold", "closed")


class QueryError(ValueError):
    """A bad request parameter; the API turns it into a 422."""


@dataclass
class ListQuery:
    where: list[str] = field(default_factory=list)
    args: list = field(default_factory=list)
    order_sql: str = "id ASC"
    page: int = 1
    per_page: int = DEFAULT_PER_PAGE


def check_resource(resource: str) -> str:
    if resource not in TABLES:
        raise LookupError(resource)
    return resource


def _int(name: str, value: str) -> int:
    try:
        return int(value)
    except ValueError:
        raise QueryError(f"{name} must be an integer") from None


def _date(name: str, value: str) -> str:
    try:
        return date.fromisoformat(value).isoformat()
    except ValueError:
        raise QueryError(f"{name} must be YYYY-MM-DD") from None


def _date_range(name: str, value: str) -> tuple[str, str]:
    start, sep, end = value.partition(":")
    if not sep:
        raise QueryError(f"{name} must be YYYY-MM-DD:YYYY-MM-DD")
    return _date(name, start), _date(name, end)


def _timestamp(name: str, value: str) -> str:
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        raise QueryError(f"{name} must be an ISO 8601 timestamp") from None
    if parsed.tzinfo is None:
        raise QueryError(f"{name} must carry a timezone (use Z for UTC)")
    return iso_z(parsed)


def _parse_order(value: str) -> str:
    name, sep, direction = value.partition(":")
    direction = direction if sep else "asc"
    if name not in ORDER_FIELDS or direction not in ORDER_DIRS:
        raise QueryError("order must be <id|created_at|updated_at>:<asc|desc>")
    sql_dir = ORDER_DIRS[direction]
    # id as tie-breaker keeps paging deterministic.
    return f"id {sql_dir}" if name == "id" else f"{name} {sql_dir}, id {sql_dir}"


def parse_list_query(resource: str, params: dict[str, str]) -> ListQuery:
    """Validate query parameters for a list call and turn them into SQL pieces."""
    allowed = FILTERS[resource]
    for key in params:
        if key not in allowed and key not in PAGING_PARAMS:
            raise QueryError(f"unknown or inapplicable parameter '{key}' for {resource}")

    query = ListQuery()
    query.page = _int("page", params.get("page", "1"))
    query.per_page = _int("per_page", params.get("per_page", str(DEFAULT_PER_PAGE)))
    if query.page < 1:
        raise QueryError("page must be >= 1")
    if not 1 <= query.per_page <= MAX_PER_PAGE:
        raise QueryError(f"per_page must be between 1 and {MAX_PER_PAGE}")
    query.order_sql = _parse_order(params.get("order", "id:asc"))

    if "ids" in params:
        ids = [_int("ids", part) for part in params["ids"].split(",")]
        query.where.append(f"id IN ({', '.join('?' for _ in ids)})")
        query.args.extend(ids)
    if "created_between" in params:
        start, end = _date_range("created_between", params["created_between"])
        query.where.append("substr(created_at, 1, 10) BETWEEN ? AND ?")
        query.args.extend([start, end])
    if "updated_since" in params:
        query.where.append("updated_at >= ?")
        query.args.append(_timestamp("updated_since", params["updated_since"]))
    if "date_between" in params:
        start, end = _date_range("date_between", params["date_between"])
        query.where.append(f"{DATE_COLUMN[resource]} BETWEEN ? AND ?")
        query.args.extend([start, end])
    for name in ("user_id", "project_id"):
        if name in params:
            query.where.append(f"{name} = ?")
            query.args.append(_int(name, params[name]))
    if "status" in params:
        query.where.append("status = ?")
        query.args.append(params["status"])
    return query


def list_rows(conn: sqlite3.Connection, resource: str, query: ListQuery) -> tuple[list[dict], dict]:
    """Run a list query. Returns (rows, meta)."""
    resource = check_resource(resource)  # table name only ever comes from TABLES
    where = f" WHERE {' AND '.join(query.where)}" if query.where else ""
    count = conn.execute(f"SELECT COUNT(*) FROM {resource}{where}", query.args).fetchone()[0]
    offset = (query.page - 1) * query.per_page
    rows = conn.execute(
        f"SELECT * FROM {resource}{where} ORDER BY {query.order_sql} LIMIT ? OFFSET ?",
        [*query.args, query.per_page, offset],
    ).fetchall()
    meta = {
        "count": count,
        "page": query.page,
        "per_page": query.per_page,
        "page_count": math.ceil(count / query.per_page),
    }
    return [dict(row) for row in rows], meta


def get_row(conn: sqlite3.Connection, resource: str, row_id: int) -> dict | None:
    resource = check_resource(resource)
    row = conn.execute(f"SELECT * FROM {resource} WHERE id = ?", [row_id]).fetchone()
    return dict(row) if row else None


def update_row(
    conn: sqlite3.Connection, resource: str, row_id: int, version: int, changes: dict, now: str
) -> bool:
    """Apply `changes` if the stored version still equals `version`. True if a row changed.

    Column names are checked against the whitelist for the resource; values are bound.
    """
    resource = check_resource(resource)
    allowed = {
        "projects": PROJECT_PATCH_COLUMNS,
        "approvals": ("status", "approver_id", "decided_at"),
    }
    columns = allowed.get(resource, ())
    if not changes or any(column not in columns for column in changes):
        raise QueryError("column not allowed")
    assignments = ", ".join(f"{column} = ?" for column in changes)
    cursor = conn.execute(
        f"UPDATE {resource} SET {assignments}, updated_at = ?, version = version + 1 "
        "WHERE id = ? AND version = ?",
        [*changes.values(), now, row_id, version],
    )
    conn.commit()
    return cursor.rowcount == 1


def touch_rows(conn: sqlite3.Connection, resource: str, ids: list[int], now: str) -> None:
    """Chaos: new updated_at and version + 1 for the given rows."""
    resource = check_resource(resource)
    conn.executemany(
        f"UPDATE {resource} SET updated_at = ?, version = version + 1 WHERE id = ?",
        [(now, row_id) for row_id in ids],
    )
    conn.commit()

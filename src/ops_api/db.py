"""SQLite schema and connection helpers. Stdlib sqlite3 only: the SQL stays visible."""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from pathlib import Path

# Tables in dependency order (parents first).
TABLES = ("users", "projects", "tasks", "time_entries", "approvals")

_COMMON = """
    id         INTEGER PRIMARY KEY,
    created_at TEXT    NOT NULL,
    updated_at TEXT    NOT NULL,
    version    INTEGER NOT NULL DEFAULT 1"""

SCHEMA = f"""
CREATE TABLE users ({_COMMON},
    name            TEXT    NOT NULL,
    email           TEXT    NOT NULL,
    title           TEXT    NOT NULL,
    department      TEXT    NOT NULL,
    active          INTEGER NOT NULL CHECK (active IN (0, 1)),
    cost_rate_cents INTEGER NOT NULL,
    bill_rate_cents INTEGER NOT NULL
);

CREATE TABLE projects ({_COMMON},
    code         TEXT    NOT NULL UNIQUE,
    name         TEXT    NOT NULL,
    client       TEXT    NOT NULL,
    status       TEXT    NOT NULL CHECK (status IN ('active', 'on_hold', 'closed')),
    budget_cents INTEGER NOT NULL,
    start_date   TEXT    NOT NULL,
    end_date     TEXT
);

CREATE TABLE tasks ({_COMMON},
    project_id     INTEGER NOT NULL REFERENCES projects (id),
    name           TEXT    NOT NULL,
    budget_minutes INTEGER NOT NULL
);

CREATE TABLE time_entries ({_COMMON},
    user_id         INTEGER NOT NULL REFERENCES users (id),
    project_id      INTEGER NOT NULL REFERENCES projects (id),
    task_id         INTEGER NOT NULL REFERENCES tasks (id),
    date_performed  TEXT    NOT NULL,
    minutes         INTEGER NOT NULL,
    billable        INTEGER NOT NULL CHECK (billable IN (0, 1)),
    cost_rate_cents INTEGER NOT NULL,
    notes           TEXT    NOT NULL
);

CREATE TABLE approvals ({_COMMON},
    user_id      INTEGER NOT NULL REFERENCES users (id),
    week_start   TEXT    NOT NULL,
    status       TEXT    NOT NULL CHECK (status IN ('submitted', 'approved', 'rejected')),
    approver_id  INTEGER REFERENCES users (id),
    submitted_at TEXT    NOT NULL,
    decided_at   TEXT
);

CREATE INDEX ix_time_entries_user ON time_entries (user_id);
CREATE INDEX ix_time_entries_project ON time_entries (project_id);
CREATE INDEX ix_time_entries_date ON time_entries (date_performed);
CREATE INDEX ix_tasks_project ON tasks (project_id);
CREATE INDEX ix_approvals_user ON approvals (user_id);
"""


def connect(path: str | Path) -> sqlite3.Connection:
    """Open a connection with dict-like rows and foreign keys on."""
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def create_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)


def iso_z(moment: datetime) -> str:
    """Format a datetime as ISO 8601 UTC with a trailing Z (seconds precision)."""
    return moment.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def now_iso() -> str:
    """Real clock, as an ISO UTC timestamp. Used by writes, never by the seed."""
    return iso_z(datetime.now(UTC))

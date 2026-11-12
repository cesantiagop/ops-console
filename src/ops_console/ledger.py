"""Append-only audit ledger in SQLite (ADR 0004 step 6).

Triggers reject every UPDATE and DELETE on `run_rows`, every DELETE on `runs`, and any UPDATE on
`runs` except `finished_at`, the counters and `status`, and only while the run is `running`.
"""

from __future__ import annotations

import getpass
import json
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from types import TracebackType

DEFAULT_PATH = Path("data") / "ledger.db"
MODES = ("dry_run", "apply", "undo")
OUTCOMES = ("applied", "no_change", "conflict", "error", "dry_run", "cancelled")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    run_id        TEXT PRIMARY KEY,
    started_at    TEXT NOT NULL,
    finished_at   TEXT,
    mode          TEXT NOT NULL CHECK (mode IN ('dry_run', 'apply', 'undo')),
    source_file   TEXT NOT NULL,
    source_sha256 TEXT NOT NULL,
    actor         TEXT NOT NULL,
    n_changes     INTEGER NOT NULL DEFAULT 0,
    n_applied     INTEGER NOT NULL DEFAULT 0,
    n_conflict    INTEGER NOT NULL DEFAULT 0,
    n_error       INTEGER NOT NULL DEFAULT 0,
    n_no_change   INTEGER NOT NULL DEFAULT 0,
    status        TEXT NOT NULL CHECK (status IN ('running', 'done', 'cancelled', 'failed'))
);
CREATE TABLE IF NOT EXISTS run_rows (
    id             INTEGER PRIMARY KEY,
    run_id         TEXT NOT NULL REFERENCES runs (run_id),
    ts             TEXT NOT NULL,
    resource       TEXT NOT NULL,
    row_id         INTEGER NOT NULL,
    row_key        TEXT NOT NULL,
    field          TEXT,
    old_value      TEXT,
    new_value      TEXT,
    version_before INTEGER,
    version_after  INTEGER,
    outcome        TEXT NOT NULL
        CHECK (outcome IN ('applied', 'no_change', 'conflict', 'error', 'dry_run', 'cancelled')),
    message        TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS run_rows_by_run ON run_rows (run_id);

CREATE TRIGGER IF NOT EXISTS run_rows_no_update BEFORE UPDATE ON run_rows
BEGIN SELECT RAISE(ABORT, 'ledger is append-only: run_rows cannot be updated'); END;
CREATE TRIGGER IF NOT EXISTS run_rows_no_delete BEFORE DELETE ON run_rows
BEGIN SELECT RAISE(ABORT, 'ledger is append-only: run_rows cannot be deleted'); END;
CREATE TRIGGER IF NOT EXISTS runs_no_delete BEFORE DELETE ON runs
BEGIN SELECT RAISE(ABORT, 'ledger is append-only: runs cannot be deleted'); END;
CREATE TRIGGER IF NOT EXISTS runs_finish_only BEFORE UPDATE ON runs
WHEN OLD.status <> 'running'
    OR NEW.run_id IS NOT OLD.run_id
    OR NEW.started_at IS NOT OLD.started_at
    OR NEW.mode IS NOT OLD.mode
    OR NEW.source_file IS NOT OLD.source_file
    OR NEW.source_sha256 IS NOT OLD.source_sha256
    OR NEW.actor IS NOT OLD.actor
    OR NEW.n_changes IS NOT OLD.n_changes
    OR NEW.n_no_change IS NOT OLD.n_no_change
BEGIN SELECT RAISE(ABORT, 'ledger is append-only: only a running run can be finished'); END;
"""


class LedgerError(Exception):
    """Unknown or ambiguous run id."""


@dataclass(frozen=True)
class Run:
    run_id: str
    started_at: str
    finished_at: str | None
    mode: str
    source_file: str
    source_sha256: str
    actor: str
    n_changes: int
    n_applied: int
    n_conflict: int
    n_error: int
    n_no_change: int
    status: str


@dataclass(frozen=True)
class RunRow:
    id: int
    run_id: str
    ts: str
    resource: str
    row_id: int
    row_key: str
    field: str | None
    old_value: str | None  # JSON text
    new_value: str | None  # JSON text
    version_before: int | None
    version_after: int | None
    outcome: str
    message: str


def _now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def default_actor() -> str:
    try:
        return getpass.getuser()
    except (OSError, KeyError, ImportError):  # no user name in a bare container
        return "unknown"


class Ledger:
    def __init__(self, path: str | Path = DEFAULT_PATH, actor: str | None = None) -> None:
        """`actor` overrides the OS user name for every run (demo mode uses `demo-user`)."""
        self.path = Path(path)
        self.actor = actor
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.path)
        self._conn.execute("PRAGMA foreign_keys = ON")
        self._conn.executescript(_SCHEMA)

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> Ledger:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()

    # -- write -------------------------------------------------------------------------------

    def start_run(
        self,
        mode: str,
        source_file: str,
        source_sha256: str,
        n_changes: int,
        n_no_change: int,
        actor: str | None = None,
    ) -> str:
        if mode not in MODES:
            raise ValueError(f"mode must be one of {', '.join(MODES)}")
        run_id = uuid.uuid4().hex
        with self._conn:
            self._conn.execute(
                "INSERT INTO runs (run_id, started_at, mode, source_file, source_sha256, actor,"
                " n_changes, n_no_change, status) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'running')",
                (run_id, _now(), mode, source_file, source_sha256,
                 actor or self.actor or default_actor(),
                 n_changes, n_no_change),
            )
        return run_id

    def record(
        self,
        run_id: str,
        resource: str,
        row_id: int,
        row_key: str,
        outcome: str,
        field: str | None = None,
        old: object = None,
        new: object = None,
        version_before: int | None = None,
        version_after: int | None = None,
        message: str = "",
    ) -> None:
        with self._conn:
            self._conn.execute(
                "INSERT INTO run_rows (run_id, ts, resource, row_id, row_key, field, old_value,"
                " new_value, version_before, version_after, outcome, message)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (run_id, _now(), resource, row_id, row_key, field,
                 None if field is None else json.dumps(old),
                 None if field is None else json.dumps(new),
                 version_before, version_after, outcome, message),
            )

    def finish_run(self, run_id: str, status: str) -> None:
        """Close a running run; the counters come from its rows (distinct rows per outcome)."""
        counts = self.outcome_counts(run_id)
        with self._conn:
            self._conn.execute(
                "UPDATE runs SET finished_at = ?, status = ?, n_applied = ?, n_conflict = ?,"
                " n_error = ? WHERE run_id = ?",
                (_now(), status, counts.get("applied", 0), counts.get("conflict", 0),
                 counts.get("error", 0), run_id),
            )

    # -- read --------------------------------------------------------------------------------

    def outcome_counts(self, run_id: str) -> dict[str, int]:
        """Distinct project rows per outcome (a row with 3 fields counts once)."""
        cur = self._conn.execute(
            "SELECT outcome, COUNT(DISTINCT row_id) FROM run_rows WHERE run_id = ?"
            " GROUP BY outcome",
            (run_id,),
        )
        return dict(cur.fetchall())

    def runs(self, limit: int = 10) -> list[Run]:
        cur = self._conn.execute(
            "SELECT * FROM runs ORDER BY started_at DESC, rowid DESC LIMIT ?", (limit,)
        )
        return [Run(*row) for row in cur.fetchall()]

    def resolve_run_id(self, text: str) -> str:
        """A full run id, or a prefix that matches exactly one run."""
        text = text.strip().lower()
        if not text:
            raise LedgerError("No run id given.")
        cur = self._conn.execute(
            "SELECT run_id FROM runs WHERE run_id LIKE ? ESCAPE '\\'",
            (text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%",),
        )
        found = [r[0] for r in cur.fetchall()]
        if not found:
            raise LedgerError(f"No run with id {text!r}.")
        if len(found) > 1 and text not in found:
            raise LedgerError(f"{text!r} matches {len(found)} runs; type more of the id.")
        return text if text in found else found[0]

    def run(self, run_id: str) -> Run:
        full = self.resolve_run_id(run_id)
        cur = self._conn.execute("SELECT * FROM runs WHERE run_id = ?", (full,))
        return Run(*cur.fetchone())

    def run_rows(self, run_id: str) -> list[RunRow]:
        cur = self._conn.execute(
            "SELECT * FROM run_rows WHERE run_id = ? ORDER BY id", (self.resolve_run_id(run_id),)
        )
        return [RunRow(*row) for row in cur.fetchall()]

    # -- raw access for tests and the audit trail --------------------------------------------

    def execute(self, sql: str, *args: object) -> sqlite3.Cursor:
        """Run any SQL; the triggers still apply. Used to prove the ledger refuses edits."""
        with self._conn:
            return self._conn.execute(sql, args)

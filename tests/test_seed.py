import hashlib
import sqlite3
from datetime import date

from ops_api.db import TABLES
from ops_api.seed import build_db


def _digest(path) -> str:
    conn = sqlite3.connect(path)
    sha = hashlib.sha256()
    for table in TABLES:
        for row in conn.execute(f"SELECT * FROM {table} ORDER BY id"):
            sha.update(repr(row).encode())
    conn.close()
    return sha.hexdigest()


def test_seed_is_deterministic(tmp_path):
    counts_a = build_db(tmp_path / "a.db", seed=42)
    counts_b = build_db(tmp_path / "b.db", seed=42)
    counts_c = build_db(tmp_path / "c.db", seed=7)
    assert counts_a == counts_b
    assert _digest(tmp_path / "a.db") == _digest(tmp_path / "b.db")
    assert _digest(tmp_path / "a.db") != _digest(tmp_path / "c.db")
    assert counts_a["users"] == 40
    assert counts_a["projects"] == 25
    assert counts_c["users"] == 40


def test_data_integrity(base_db):
    conn = sqlite3.connect(base_db)
    mismatched = conn.execute(
        "SELECT COUNT(*) FROM time_entries t JOIN tasks k ON k.id = t.task_id "
        "WHERE k.project_id != t.project_id"
    ).fetchone()[0]
    assert mismatched == 0

    minutes = [r[0] for r in conn.execute("SELECT minutes FROM time_entries")]
    assert minutes
    assert all(m % 15 == 0 and 15 <= m <= 600 for m in minutes)

    weeks = [date.fromisoformat(r[0]) for r in conn.execute("SELECT week_start FROM approvals")]
    assert weeks
    assert all(w.weekday() == 0 for w in weeks)

    emails = [r[0] for r in conn.execute("SELECT email FROM users")]
    assert all(e.endswith(("@example.com", "@example.org", "@example.net")) for e in emails)
    assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
    conn.close()

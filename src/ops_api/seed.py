"""Deterministic synthetic seed: Faker and random.Random are both seeded, no wall clock."""

from __future__ import annotations

import random
import re
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from faker import Faker

from .db import TABLES, connect, create_schema, iso_z

NOW = datetime(2026, 7, 1, tzinfo=UTC)  # the fixed "now" of the synthetic world
FIRST_DAY = date(2026, 1, 5)  # a Monday
LAST_DAY = date(2026, 6, 26)  # a Friday, inclusive

N_USERS = 40
N_PROJECTS = 25
DEPARTMENTS = ("Delivery", "Platform", "Insights", "Advisory", "Creative", "Operations")
TITLES = ("Analyst", "Consultant", "Engineer", "Designer", "Associate", "Lead", "Coordinator")
DOMAINS = ("example.com", "example.org", "example.net")
TASK_NAMES = ("Discovery", "Design", "Build", "Review", "Testing", "Handover", "Management")
PROJECT_KINDS = ("Rollout", "Migration", "Audit", "Redesign", "Pilot", "Rebuild")
NOTES = (
    "",
    "Weekly sync",
    "Drafted deliverable",
    "Reviewed feedback",
    "Prepared status update",
    "Fixed defects",
    "Workshop prep",
    "Client call",
)


def _stamps(rng: random.Random, created: datetime) -> tuple[str, str, int]:
    """Return (created_at, updated_at, version); about 10 % of rows were edited later."""
    updated, version = created, 1
    if rng.random() < 0.10:
        updated = min(created + timedelta(seconds=rng.randint(3600, 5 * 86400)), NOW)
        version = 2
    return iso_z(created), iso_z(updated), version


def _random_moment(rng: random.Random, day: date) -> datetime:
    start = datetime(day.year, day.month, day.day, tzinfo=UTC)
    return start + timedelta(seconds=rng.randint(0, 86399))


def _working_days() -> list[date]:
    days = []
    day = FIRST_DAY
    while day <= LAST_DAY:
        if day.weekday() < 5:
            days.append(day)
        day += timedelta(days=1)
    return days


def _slug(text: str) -> str:
    return re.sub(r"[^a-z]", "", text.lower())


def _insert(conn, table: str, columns: tuple[str, ...], rows: list[tuple]) -> None:
    marks = ", ".join("?" for _ in columns)
    conn.executemany(f"INSERT INTO {table} ({', '.join(columns)}) VALUES ({marks})", rows)


def _make_users(fake: Faker, rng: random.Random) -> list[tuple]:
    rows = []
    for i in range(1, N_USERS + 1):
        first, last = fake.first_name(), fake.last_name()
        email = f"{_slug(first)}.{_slug(last)}{i}@{rng.choice(DOMAINS)}"
        cost = 500 * rng.randint(8, 19) * 10  # 40.00 .. 95.00 per hour, in cents
        bill = cost * rng.randint(140, 200) // 100
        created = _random_moment(rng, date(2025, 1, 1) + timedelta(days=rng.randint(0, 300)))
        created_at, updated_at, version = _stamps(rng, created)
        rows.append((
            created_at, updated_at, version, f"{first} {last}", email, rng.choice(TITLES),
            rng.choice(DEPARTMENTS), 1 if rng.random() < 0.9 else 0, cost, bill,
        ))
    return rows


def _make_projects(fake: Faker, rng: random.Random) -> list[tuple]:
    rows = []
    for i in range(1, N_PROJECTS + 1):
        status = rng.choices(("active", "on_hold", "closed"), weights=(70, 15, 15))[0]
        start = date(2025, 6, 1) + timedelta(days=rng.randint(0, 200))
        end = None
        if status == "closed":
            end = date(2026, 3, 1) + timedelta(days=rng.randint(0, 120))
        elif rng.random() < 0.5:
            end = date(2026, 9, 1) + timedelta(days=rng.randint(0, 200))
        created_at, updated_at, version = _stamps(rng, _random_moment(rng, start))
        rows.append((
            created_at, updated_at, version, f"PRJ-{i:04d}",
            f"{fake.word().title()} {rng.choice(PROJECT_KINDS)}", fake.company(), status,
            rng.randint(50, 500) * 100_000, start.isoformat(), end.isoformat() if end else None,
        ))
    return rows


def _make_tasks(rng: random.Random, project_rows: list[tuple]) -> list[tuple]:
    rows = []
    for project_id, project in enumerate(project_rows, start=1):
        for name in rng.sample(TASK_NAMES, rng.randint(3, 6)):
            created_at, updated_at, version = _stamps(
                rng, datetime.fromisoformat(project[0]) + timedelta(hours=rng.randint(0, 48))
            )
            budget = rng.randint(40, 400) * 60
            rows.append((created_at, updated_at, version, project_id, name, budget))
    return rows


def _make_time_entries(
    rng: random.Random, user_rows: list[tuple], project_rows: list[tuple], task_rows: list[tuple]
) -> list[tuple]:
    tasks_by_project: dict[int, list[int]] = {}
    for task_id, task in enumerate(task_rows, start=1):
        tasks_by_project.setdefault(task[3], []).append(task_id)
    active_projects = [i for i, p in enumerate(project_rows, start=1) if p[6] == "active"]
    active_users = [(i, u) for i, u in enumerate(user_rows, start=1) if u[7] == 1]

    rows = []
    for day in _working_days():
        for user_id, user in active_users:
            todays = rng.sample(active_projects, rng.randint(1, 3))
            for _ in range(rng.randint(5, 6)):
                project_id = rng.choice(todays)
                task_id = rng.choice(tasks_by_project[project_id])
                steps = rng.randint(1, 16) if rng.random() < 0.9 else rng.randint(17, 40)
                created = _random_moment(rng, day + timedelta(days=rng.randint(0, 3)))
                created_at, updated_at, version = _stamps(rng, created)
                rows.append((
                    created_at, updated_at, version, user_id, project_id, task_id,
                    day.isoformat(), 15 * steps, 1 if rng.random() < 0.85 else 0,
                    user[8], rng.choice(NOTES),
                ))
    return rows


def _make_approvals(rng: random.Random, user_rows: list[tuple]) -> list[tuple]:
    n_weeks = (LAST_DAY - FIRST_DAY).days // 7 + 1
    rows = []
    for week in range(n_weeks):
        week_start = FIRST_DAY + timedelta(weeks=week)
        for user_id in range(1, len(user_rows) + 1):
            submitted = _random_moment(rng, week_start + timedelta(days=4)) + timedelta(
                seconds=rng.randint(0, 3 * 86400)
            )
            status = "submitted"
            if week < n_weeks - 3 and rng.random() > 0.05:
                status = "approved" if rng.random() < 0.9 else "rejected"
            approver_id = decided = None
            updated, version = submitted, 1
            if status != "submitted":
                approver_id = rng.choice([i for i in range(1, len(user_rows) + 1) if i != user_id])
                decided = submitted + timedelta(seconds=rng.randint(3600, 3 * 86400))
                updated, version = decided, 2
            rows.append((
                iso_z(submitted), iso_z(updated), version, user_id, week_start.isoformat(),
                status, approver_id, iso_z(submitted), iso_z(decided) if decided else None,
            ))
    return rows


COMMON = ("created_at", "updated_at", "version")
COLUMNS = {
    "users": COMMON + ("name", "email", "title", "department", "active", "cost_rate_cents",
                       "bill_rate_cents"),
    "projects": COMMON + ("code", "name", "client", "status", "budget_cents", "start_date",
                          "end_date"),
    "tasks": COMMON + ("project_id", "name", "budget_minutes"),
    "time_entries": COMMON + ("user_id", "project_id", "task_id", "date_performed", "minutes",
                              "billable", "cost_rate_cents", "notes"),
    "approvals": COMMON + ("user_id", "week_start", "status", "approver_id", "submitted_at",
                           "decided_at"),
}


def build_db(path: str | Path, seed: int = 42) -> dict[str, int]:
    """Drop and rebuild the database at `path`. Returns row counts per table."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.unlink(missing_ok=True)

    fake = Faker()
    fake.seed_instance(seed)
    rng = random.Random(seed)

    users = _make_users(fake, rng)
    projects = _make_projects(fake, rng)
    tasks = _make_tasks(rng, projects)
    entries = _make_time_entries(rng, users, projects, tasks)
    approvals = _make_approvals(rng, users)
    data = {
        "users": users, "projects": projects, "tasks": tasks,
        "time_entries": entries, "approvals": approvals,
    }

    conn = connect(path)
    try:
        create_schema(conn)
        for table in TABLES:
            _insert(conn, table, COLUMNS[table], data[table])
        conn.commit()
    finally:
        conn.close()
    return {table: len(data[table]) for table in TABLES}

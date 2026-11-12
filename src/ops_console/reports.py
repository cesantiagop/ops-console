"""Pure report functions over client models. No I/O, no rich.

Money is integer cents, time is integer minutes. Division happens once, at the end, and rounds
half-up. Nothing here uses float arithmetic.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date, timedelta

from ops_client import Approval, Project, Task, TimeEntry, User

NA = "n/a"
MAX_WEEKS = 12
DEFAULT_SPAN_DAYS = 27  # blank end date = start + 27 days (four full weeks from a Monday)


# -- number formatting ---------------------------------------------------------------------------


def div_half_up(numerator: int, denominator: int) -> int:
    """Integer division rounded half-up (halves go away from zero). Denominator must be > 0."""
    if denominator <= 0:
        raise ValueError("denominator must be positive")
    sign = -1 if numerator < 0 else 1
    return sign * ((abs(numerator) * 2 + denominator) // (denominator * 2))


def cost_cents(entries: Iterable[TimeEntry]) -> int:
    """Labor cost: sum of minutes * cost_rate_cents as integers, / 60 once, half-up."""
    return div_half_up(sum(e.minutes * e.cost_rate_cents for e in entries), 60)


def dollars(cents: int) -> str:
    """`$1,234.56` from integer cents (no float)."""
    sign = "-" if cents < 0 else ""
    whole, part = divmod(abs(cents), 100)
    return f"{sign}${whole:,}.{part:02d}"


def hours_text(minutes: int) -> str:
    """Hours with 1 decimal, from minutes, half-up."""
    tenths = div_half_up(minutes * 10, 60)
    sign = "-" if tenths < 0 else ""
    whole, part = divmod(abs(tenths), 10)
    return f"{sign}{whole}.{part}"


def percent_text(part: int, whole: int) -> str:
    """`part / whole` as a percent with 1 decimal, or "n/a" when `whole` is zero."""
    if whole == 0:
        return NA
    tenths = div_half_up(part * 1000, whole)
    sign = "-" if tenths < 0 else ""
    integer, frac = divmod(abs(tenths), 10)
    return f"{sign}{integer}.{frac}%"


# -- dates ---------------------------------------------------------------------------------------


def week_start(day: date) -> date:
    """The Monday on or before `day`."""
    return day - timedelta(days=day.weekday())


def parse_iso_date(text: str) -> date:
    """Strict YYYY-MM-DD; raises ValueError."""
    if len(text) != 10:
        raise ValueError(f"{text!r} is not a date (use YYYY-MM-DD)")
    try:
        return date.fromisoformat(text)
    except ValueError:
        raise ValueError(f"{text!r} is not a date (use YYYY-MM-DD)") from None


def default_end(start: date) -> date:
    return start + timedelta(days=DEFAULT_SPAN_DAYS)


def weeks_in_range(start: date, end: date) -> list[date]:
    """Every Monday-start week touched by start..end (inclusive)."""
    weeks = []
    current = week_start(start)
    while current <= end:
        weeks.append(current)
        current += timedelta(days=7)
    return weeks


# -- projects ------------------------------------------------------------------------------------


def search_projects(projects: Iterable[Project], text: str = "", status: str = "") -> list[Project]:
    """Case-insensitive match of `text` on code, name or client; blank status = any."""
    needle = text.strip().lower()
    wanted = status.strip().lower()
    found = []
    for p in projects:
        if wanted and p.status.lower() != wanted:
            continue
        if needle and not any(needle in v.lower() for v in (p.code, p.name, p.client)):
            continue
        found.append(p)
    return found


def find_project(projects: Iterable[Project], code: str) -> Project | None:
    wanted = code.strip().lower()
    return next((p for p in projects if p.code.lower() == wanted), None)


@dataclass(frozen=True)
class TaskRow:
    name: str
    minutes: int
    budget_minutes: int
    pct_used: str


@dataclass(frozen=True)
class ProjectSummary:
    project: Project
    tasks: list[TaskRow]
    total_minutes: int
    cost_cents: int
    budget_cents: int
    remaining_cents: int
    pct_budget_used: str


def project_summary(
    project: Project, tasks: Sequence[Task], entries: Sequence[TimeEntry]
) -> ProjectSummary:
    minutes_by_task: dict[int, int] = defaultdict(int)
    for e in entries:
        minutes_by_task[e.task_id] += e.minutes
    rows = [
        TaskRow(
            name=t.name,
            minutes=minutes_by_task[t.id],
            budget_minutes=t.budget_minutes,
            pct_used=percent_text(minutes_by_task[t.id], t.budget_minutes),
        )
        for t in sorted(tasks, key=lambda t: t.id)
    ]
    cost = cost_cents(entries)
    return ProjectSummary(
        project=project,
        tasks=rows,
        total_minutes=sum(e.minutes for e in entries),
        cost_cents=cost,
        budget_cents=project.budget_cents,
        remaining_cents=project.budget_cents - cost,
        pct_budget_used=percent_text(cost, project.budget_cents),
    )


# -- hours by person by week ---------------------------------------------------------------------


@dataclass(frozen=True)
class HoursGrid:
    weeks: list[date]
    people: list[tuple[str, dict[date, int], int]]  # name, minutes by week, row total
    week_totals: dict[date, int]
    grand_total: int


def hours_grid(
    entries: Iterable[TimeEntry], users: dict[int, User], start: date, end: date
) -> HoursGrid:
    """Person x ISO week minutes for entries performed in start..end (inclusive)."""
    weeks = weeks_in_range(start, end)
    by_person: dict[int, dict[date, int]] = defaultdict(lambda: defaultdict(int))
    for e in entries:
        performed = date.fromisoformat(e.date_performed)
        if start <= performed <= end:
            by_person[e.user_id][week_start(performed)] += e.minutes

    def label(user_id: int) -> str:
        user = users.get(user_id)
        return user.name if user else f"user {user_id}"

    people = sorted(
        ((label(uid), dict(cells), sum(cells.values())) for uid, cells in by_person.items()),
        key=lambda row: row[0],
    )
    week_totals = {w: sum(cells.get(w, 0) for _, cells, _ in people) for w in weeks}
    return HoursGrid(weeks, people, week_totals, sum(week_totals.values()))


# -- approvals -----------------------------------------------------------------------------------


@dataclass(frozen=True)
class WaitingRow:
    person: str
    week_start: date
    days_waiting: int


@dataclass(frozen=True)
class WaitingReport:
    rows: list[WaitingRow]
    by_week: list[tuple[date, int]]


def approvals_waiting(
    approvals: Iterable[Approval], users: dict[int, User], today: date
) -> WaitingReport:
    """`submitted` approvals, oldest week first. Days waiting = today - week end (Sunday)."""
    rows = []
    for a in approvals:
        if a.status != "submitted":
            continue
        monday = date.fromisoformat(a.week_start)
        user = users.get(a.user_id)
        person = user.name if user else f"user {a.user_id}"
        rows.append(WaitingRow(person, monday, (today - (monday + timedelta(days=6))).days))
    rows.sort(key=lambda r: (r.week_start, r.person))
    counts: dict[date, int] = defaultdict(int)
    for r in rows:
        counts[r.week_start] += 1
    return WaitingReport(rows, sorted(counts.items()))

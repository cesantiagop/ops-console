from datetime import date

from ops_client import Project, Task, TimeEntry, User
from ops_console import reports

STAMP = {"created_at": "2026-01-01T00:00:00Z", "updated_at": "2026-01-01T00:00:00Z", "version": 1}


def entry(minutes, rate, day="2026-03-02", user_id=1, task_id=1, entry_id=1):
    return TimeEntry(
        id=entry_id, user_id=user_id, project_id=1, task_id=task_id, date_performed=day,
        minutes=minutes, billable=True, cost_rate_cents=rate, notes="", **STAMP,
    )


def project(budget_cents):
    return Project(
        id=1, code="PRJ-0001", name="Demo", client="Acme", status="active",
        budget_cents=budget_cents, start_date="2026-01-01", **STAMP,
    )


def user(user_id, name):
    return User(
        id=user_id, name=name, email="x@example.com", title="Analyst", department="Delivery",
        active=True, cost_rate_cents=5000, bill_rate_cents=9000, **STAMP,
    )


def test_cost_is_summed_in_cents_then_rounded_once():
    # Each entry is 0.5 cent: rounding per entry gives 1 + 1 = 2; sum-then-round gives 1.
    entries = [entry(1, 30, entry_id=1), entry(1, 30, entry_id=2)]
    per_entry = sum(reports.cost_cents([e]) for e in entries)
    assert per_entry == 2
    assert reports.cost_cents(entries) == 1
    # Exactly half rounds up; the result is an int, never a float.
    assert reports.cost_cents([entry(1, 30)]) == 1
    assert isinstance(reports.cost_cents(entries), int)
    assert reports.dollars(123456) == "$1,234.56"
    assert reports.dollars(-5) == "-$0.05"


def test_week_bucketing_and_totals_from_minutes():
    assert reports.week_start(date(2026, 3, 8)) == date(2026, 3, 2)  # Sunday -> previous Monday
    assert reports.week_start(date(2026, 3, 2)) == date(2026, 3, 2)  # Monday -> itself
    entries = [
        entry(50, 100, day="2026-03-08", entry_id=1),
        entry(10, 100, day="2026-03-09", entry_id=2),
        entry(7, 100, day="2026-03-03", entry_id=3),
        entry(99, 100, day="2026-03-20", entry_id=4),  # outside the range
    ]
    grid = reports.hours_grid(entries, {1: user(1, "Ann")}, date(2026, 3, 2), date(2026, 3, 15))
    assert grid.weeks == [date(2026, 3, 2), date(2026, 3, 9)]
    name, cells, total = grid.people[0]
    assert cells == {date(2026, 3, 2): 57, date(2026, 3, 9): 10}
    assert total == 67 == grid.grand_total
    # 57 min and 10 min show as 1.0 and 0.2 hours; the total comes from 67 minutes, not 1.0 + 0.2.
    assert reports.hours_text(57) == "1.0"
    assert reports.hours_text(67) == "1.1"


def test_percent_with_zero_budget_is_na():
    summary = reports.project_summary(
        project(0), [Task(id=1, project_id=1, name="Build", budget_minutes=0, **STAMP)],
        [entry(60, 6000)],
    )
    assert summary.pct_budget_used == "n/a"
    assert summary.tasks[0].pct_used == "n/a"
    assert summary.remaining_cents == -6000
    assert reports.percent_text(1, 3) == "33.3%"
    assert reports.percent_text(1, 8) == "12.5%"

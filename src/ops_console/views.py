"""Rich renderables built from report rows. No client calls here."""

from __future__ import annotations

from collections.abc import Sequence

from rich.markup import escape
from rich.panel import Panel
from rich.table import Table

from ops_client import Project

from . import reports

MAX_PROJECT_ROWS = 50


def _cell(value: object) -> str:
    return escape(str(value))


def projects_table(projects: Sequence[Project]) -> Table:
    table = Table(title="Projects")
    table.add_column("Code")
    table.add_column("Name")
    table.add_column("Client")
    table.add_column("Status")
    table.add_column("Budget ($)", justify="right")
    for p in projects[:MAX_PROJECT_ROWS]:
        table.add_row(
            _cell(p.code), _cell(p.name), _cell(p.client), _cell(p.status),
            reports.dollars(p.budget_cents),
        )
    hidden = len(projects) - MAX_PROJECT_ROWS
    caption = f"{len(projects)} projects"
    if hidden > 0:
        caption += f"  … {hidden} more"
    table.caption = caption
    return table


def project_panel(summary: reports.ProjectSummary) -> Panel:
    p = summary.project
    lines = [
        f"Name:    {_cell(p.name)}",
        f"Client:  {_cell(p.client)}",
        f"Status:  {_cell(p.status)}",
        f"Dates:   {p.start_date} to {p.end_date or 'open'}",
        f"Budget:  {reports.dollars(p.budget_cents)}",
    ]
    return Panel("\n".join(lines), title=_cell(p.code), expand=False)


def tasks_table(summary: reports.ProjectSummary) -> Table:
    table = Table(title="Tasks")
    table.add_column("Task")
    table.add_column("Hours logged", justify="right")
    table.add_column("Budget hours", justify="right")
    table.add_column("% used", justify="right")
    for t in summary.tasks:
        table.add_row(
            _cell(t.name), reports.hours_text(t.minutes),
            reports.hours_text(t.budget_minutes), t.pct_used,
        )
    return table


def project_footer(summary: reports.ProjectSummary) -> Table:
    table = Table(show_header=False, box=None)
    table.add_column()
    table.add_column(justify="right")
    table.add_row("Total hours", reports.hours_text(summary.total_minutes))
    table.add_row("Labor cost ($)", reports.dollars(summary.cost_cents))
    table.add_row("Budget ($)", reports.dollars(summary.budget_cents))
    table.add_row("Remaining ($)", reports.dollars(summary.remaining_cents))
    table.add_row("% of budget used", summary.pct_budget_used)
    return table


def hours_table(grid: reports.HoursGrid) -> Table:
    table = Table(title="Hours by person by week", caption="Weeks start Monday (MM-DD)")
    table.add_column("Person")
    for week in grid.weeks:
        table.add_column(week.strftime("%m-%d"), justify="right")
    table.add_column("Total", justify="right", style="bold")
    for name, cells, total in grid.people:
        table.add_row(
            _cell(name),
            *(reports.hours_text(cells.get(w, 0)) for w in grid.weeks),
            reports.hours_text(total),
        )
    table.add_section()
    table.add_row(
        "Total",
        *(reports.hours_text(grid.week_totals[w]) for w in grid.weeks),
        reports.hours_text(grid.grand_total),
    )
    return table


def waiting_table(report: reports.WaitingReport) -> Table:
    table = Table(title="Approvals waiting")
    table.add_column("Person")
    table.add_column("Week start")
    table.add_column("Days waiting", justify="right")
    for row in report.rows:
        table.add_row(_cell(row.person), row.week_start.isoformat(), str(row.days_waiting))
    table.caption = f"{len(report.rows)} approvals waiting"
    return table


def waiting_by_week(report: reports.WaitingReport) -> Table:
    table = Table(title="Count by week")
    table.add_column("Week start")
    table.add_column("Waiting", justify="right")
    for monday, count in report.by_week:
        table.add_row(monday.isoformat(), str(count))
    return table

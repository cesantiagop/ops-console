"""Rich renderables for plans, summaries and the ledger. No client calls, no ledger writes."""

from __future__ import annotations

import json
from collections.abc import Sequence

from rich.markup import escape
from rich.table import Table

from . import reports
from .apply import Summary
from .changeset import ChangesetError
from .ledger import OUTCOMES, Run, RunRow
from .plan import Plan

SHORT_ID = 12


def _cell(value: object) -> str:
    return escape(str(value))


def show_value(field: str | None, value: object) -> str:
    """Display text for one value; money in dollars."""
    if value is None:
        return "NULL"
    if field == "budget_cents" and isinstance(value, int):
        return reports.dollars(value)
    return str(value)


def _field_label(field: str) -> str:
    return "budget" if field == "budget_cents" else field


def plan_table(plan: Plan) -> Table:
    table = Table(title="Planned changes")
    table.add_column("Code")
    table.add_column("Field")
    table.add_column("Old → New")
    for change in plan.changes:
        for fc in change.fields:
            table.add_row(
                _cell(change.code), _field_label(fc.field),
                f"{_cell(show_value(fc.field, fc.old))} → {_cell(show_value(fc.field, fc.new))}",
            )
        table.add_section()
    table.caption = counts_line(plan)
    return table


def counts_line(plan: Plan) -> str:
    return f"{len(plan.changes)} changes, {len(plan.no_change)} no_change"


def summary_table(summary: Summary) -> Table:
    table = Table(title="Result")
    table.add_column("Outcome")
    table.add_column("Rows", justify="right")
    for outcome in OUTCOMES:
        if summary.get(outcome):
            table.add_row(outcome, str(summary.get(outcome)))
    if not summary.counts:
        table.add_row("(nothing recorded)", "0")
    return table


def problems_table(error: ChangesetError) -> Table:
    table = Table(title="Changeset problems")
    table.add_column("Line", justify="right")
    table.add_column("Column")
    table.add_column("Problem")
    for p in error.problems:
        table.add_row(str(p.line), _cell(p.column), _cell(p.message))
    table.caption = f"{len(error.problems)} problems; nothing was applied"
    return table


def runs_table(runs: Sequence[Run]) -> Table:
    table = Table(title="Ledger: latest runs")
    for name in ("Run", "Started (UTC)", "Mode", "Source"):
        table.add_column(name)
    for name in ("Changes", "Applied", "Conflict", "Error", "No change"):
        table.add_column(name, justify="right")
    table.add_column("Status")
    for r in runs:
        table.add_row(
            r.run_id[:SHORT_ID], r.started_at[:19].replace("T", " "), r.mode,
            _cell(r.source_file if r.source_file.startswith("undo:") else _name(r.source_file)),
            str(r.n_changes), str(r.n_applied), str(r.n_conflict), str(r.n_error),
            str(r.n_no_change), r.status,
        )
    table.caption = f"{len(runs)} runs"
    return table


def _name(path: str) -> str:
    return path.replace("\\", "/").rsplit("/", 1)[-1]


def run_rows_table(run: Run, rows: Sequence[RunRow]) -> Table:
    table = Table(title=f"Run {run.run_id}", caption=(
        f"{run.mode} · {run.status} · by {run.actor} · sha256 {run.source_sha256[:12]}"
    ))
    for name in ("Code", "Field", "Old", "New"):
        table.add_column(name)
    table.add_column("Ver", justify="right")
    table.add_column("Outcome")
    table.add_column("Message")
    for r in rows:
        old = show_value(r.field, json.loads(r.old_value)) if r.field else ""
        new = show_value(r.field, json.loads(r.new_value)) if r.field else ""
        versions = "" if r.version_before is None else f"{r.version_before}"
        if r.version_after is not None:
            versions += f"→{r.version_after}"
        table.add_row(
            _cell(r.row_key), _cell(_field_label(r.field) if r.field else ""),
            _cell(old), _cell(new), versions, r.outcome, _cell(r.message),
        )
    return table

"""Apply a plan row by row with the planned version, and write every outcome to the ledger.

A 409 is a `conflict`: recorded, not retried, and the run goes on (ADR 0004 step 5). Undo is
an ordinary changeset built from a run's `applied` rows (step 7).
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass

from ops_client import ConflictError, OpsClient, OpsError

from .changeset import Desired
from .ledger import Ledger
from .plan import RESOURCE, Plan, RowChange


@dataclass(frozen=True)
class Summary:
    """Project rows per outcome for one run."""

    counts: dict[str, int]

    def get(self, outcome: str) -> int:
        return self.counts.get(outcome, 0)

    @property
    def has_problems(self) -> bool:
        return self.get("conflict") > 0 or self.get("error") > 0


@dataclass(frozen=True)
class RunResult:
    run_id: str
    status: str  # done / cancelled / failed
    summary: Summary


def _summary(ledger: Ledger, run_id: str) -> Summary:
    return Summary(ledger.outcome_counts(run_id))


def _record_change(
    ledger: Ledger, run_id: str, change: RowChange, outcome: str,
    version_after: int | None = None, message: str = "",
) -> None:
    for fc in change.fields:
        ledger.record(
            run_id, RESOURCE, change.row_id, change.code, outcome, field=fc.field,
            old=fc.old, new=fc.new, version_before=change.version,
            version_after=version_after, message=message,
        )


def _record_no_change(ledger: Ledger, run_id: str, plan: Plan) -> None:
    for row in plan.no_change:
        ledger.record(
            run_id, RESOURCE, row.row_id, row.code, "no_change", version_before=row.version,
            message="already at the desired values",
        )


def record_only(ledger: Ledger, run_id: str, plan: Plan, outcome: str) -> Summary:
    """Write `dry_run` or `cancelled` for every change (and `no_change`); touch nothing else."""
    if outcome not in ("dry_run", "cancelled"):
        raise ValueError("record_only is for dry_run or cancelled")
    _record_no_change(ledger, run_id, plan)
    for change in plan.changes:
        _record_change(ledger, run_id, change, outcome)
    return _summary(ledger, run_id)


def apply_plan(client: OpsClient, plan: Plan, ledger: Ledger, run_id: str) -> Summary:
    _record_no_change(ledger, run_id, plan)
    for change in plan.changes:
        values = {fc.field: fc.new for fc in change.fields}
        try:
            updated = client.patch_project(change.row_id, change.version, **values)
        except ConflictError as exc:
            now = (exc.current or {}).get("version")
            note = f"changed after the plan (now version {now})" if now is not None else str(exc)
            _record_change(ledger, run_id, change, "conflict", message=note)
        except OpsError as exc:
            _record_change(
                ledger, run_id, change, "error", message=f"{type(exc).__name__}: {exc}"
            )
        else:
            _record_change(ledger, run_id, change, "applied", version_after=updated.version)
    return _summary(ledger, run_id)


def run_plan(
    client: OpsClient,
    plan: Plan,
    ledger: Ledger,
    *,
    mode: str,
    source_file: str,
    source_sha256: str,
    apply: bool,
    confirm: Callable[[int], bool],
) -> RunResult:
    """One run: dry-run unless `apply`; with `apply`, `confirm(n_changes)` must say yes first.

    `mode` is the ledger mode for a real write (`apply` or `undo`); a dry run is `dry_run`.
    """
    n = len(plan.changes)
    run_id = ledger.start_run(
        mode if apply else "dry_run", source_file, source_sha256, n, len(plan.no_change)
    )
    try:
        if not apply:
            summary, status = record_only(ledger, run_id, plan, "dry_run"), "done"
        elif n and not confirm(n):
            summary, status = record_only(ledger, run_id, plan, "cancelled"), "cancelled"
        else:
            summary, status = apply_plan(client, plan, ledger, run_id), "done"
    except BaseException:
        ledger.finish_run(run_id, "failed")
        raise
    ledger.finish_run(run_id, status)
    return RunResult(run_id, status, summary)


def inverse_changeset(ledger: Ledger, run_id: str) -> list[Desired]:
    """The old values of every field the run applied, one `Desired` per project, in run order."""
    values: dict[str, dict[str, object]] = {}
    for row in ledger.run_rows(run_id):
        if row.outcome != "applied" or row.field is None:
            continue
        old = json.loads(row.old_value) if row.old_value is not None else None
        values.setdefault(row.row_key, {})[row.field] = old
    return [Desired(code, i, v) for i, (code, v) in enumerate(values.items(), start=1)]


def inverse_sha256(desired: list[Desired]) -> str:
    """Hash of the inverse changeset, so an undo run has a fingerprint like a file does."""
    text = json.dumps([[d.code, d.values] for d in desired], sort_keys=True)
    return hashlib.sha256(text.encode()).hexdigest()

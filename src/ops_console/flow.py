"""The shared screen flow for the CLI and the menu: plan, preview, confirm, apply, summary.

Each function returns an exit code: 0 ok or cancelled, 1 bad input (file, run id, changeset),
2 the run finished with conflicts or errors.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from rich.console import Console
from rich.markup import escape

from ops_client import OpsClient

from . import changes_views as cv
from .apply import RunResult, inverse_changeset, inverse_sha256, run_plan
from .changeset import ChangesetError
from .ledger import Ledger, LedgerError
from .plan import Plan, build_plan, plan_from_file

Ask = Callable[[str], str]

EXIT_OK, EXIT_INPUT, EXIT_PROBLEMS = 0, 1, 2


def _red(console: Console, message: str) -> None:
    console.print(f"[red]{escape(message)}[/red]")


def _execute(
    client: OpsClient, plan: Plan, ledger: Ledger, console: Console, ask: Ask, *,
    mode: str, source_file: str, sha256: str, apply: bool, yes: bool,
) -> int:
    console.print(cv.plan_table(plan))
    if not plan.changes:
        console.print("Nothing to change.")

    def confirm(n: int) -> bool:
        if yes:
            return True
        return ask(f"Type APPLY {n} to apply, anything else cancels: ").strip() == f"APPLY {n}"

    result: RunResult = run_plan(
        client, plan, ledger, mode=mode, source_file=source_file, source_sha256=sha256,
        apply=apply, confirm=confirm,
    )
    console.print(cv.summary_table(result.summary))
    if not apply:
        console.print("Dry run: nothing was written to the API. Use --apply to write.")
    elif result.status == "cancelled":
        console.print("Cancelled: nothing was written to the API.")
    console.print(f"Run ID: {result.run_id}  (status {result.status})")
    return EXIT_PROBLEMS if result.summary.has_problems else EXIT_OK


def changes_file(
    client: OpsClient, path: str, ledger: Ledger, console: Console, ask: Ask, *,
    apply: bool, yes: bool = False,
) -> int:
    path = path.strip().strip('"')
    try:
        plan, sha256 = plan_from_file(client, Path(path))
    except ChangesetError as exc:
        console.print(cv.problems_table(exc))
        return EXIT_INPUT
    except OSError as exc:
        _red(console, f"Cannot read {path!r}: {exc.strerror or exc}")
        return EXIT_INPUT
    return _execute(
        client, plan, ledger, console, ask, mode="apply", source_file=path, sha256=sha256,
        apply=apply, yes=yes,
    )


def undo_run(
    client: OpsClient, run_id: str, ledger: Ledger, console: Console, ask: Ask, *,
    apply: bool, yes: bool = False,
) -> int:
    try:
        full_id = ledger.resolve_run_id(run_id)
        desired = inverse_changeset(ledger, full_id)
        plan = build_plan(client, desired)
    except LedgerError as exc:
        _red(console, str(exc))
        return EXIT_INPUT
    except ChangesetError as exc:
        console.print(cv.problems_table(exc))
        return EXIT_INPUT
    if not desired:
        console.print("That run applied nothing, so there is nothing to undo.")
        return EXIT_OK
    return _execute(
        client, plan, ledger, console, ask, mode="undo", source_file=f"undo:{full_id}",
        sha256=inverse_sha256(desired), apply=apply, yes=yes,
    )


def show_ledger(
    ledger: Ledger, console: Console, run_id: str | None, ask: Ask | None = None
) -> int:
    """No `run_id` and no `ask`: the table only. With `ask`: prompt for a run id (blank = back)."""
    if run_id is None:
        console.print(cv.runs_table(ledger.runs(10)))
        if ask is None:
            return EXIT_OK
        run_id = ask("Run id (blank = back): ").strip()
        if not run_id:
            return EXIT_OK
    try:
        run = ledger.run(run_id)
        rows = ledger.run_rows(run.run_id)
    except LedgerError as exc:
        _red(console, str(exc))
        return EXIT_INPUT
    console.print(cv.run_rows_table(run, rows))
    return EXIT_OK

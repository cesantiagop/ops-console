from datetime import date

from rich.console import Console

from ops_console.__main__ import main
from ops_console.ledger import Ledger
from ops_console.menu import Menu
from tests.changes_support import EXAMPLE, finished_run, ops, scripted

TODAY = date(2026, 7, 1)


def test_menu_bulk_change_then_ledger_end_to_end(client, tmp_path):
    ledger_path = tmp_path / "ledger.db"
    console = Console(record=True, width=140)
    menu = Menu(
        ops(client), scripted(["6", str(EXAMPLE), "APPLY 2", "7", "", "0"]), console,
        "demo (synthetic data)", "env", today=TODAY, ledger_path=ledger_path,
    )
    assert menu.run() == 0
    text = console.export_text()
    assert "Planned changes" in text
    assert "$320,000.00" in text  # money shown in dollars
    assert "Run ID:" in text
    assert "Ledger: latest runs" in text
    assert " 6  Bulk change projects (CSV)" in text
    assert "Traceback" not in text
    with Ledger(ledger_path) as ledger:
        (run,) = ledger.runs()
        assert (run.mode, run.status, run.n_applied) == ("apply", "done", 2)
    assert {p.code: p.status for p in ops(client).list("projects")}["PRJ-0001"] == "on_hold"


def test_menu_undo_item(client, tmp_path):
    ledger_path = tmp_path / "ledger.db"
    console = Console(record=True, width=140)
    with Ledger(ledger_path) as ledger:
        run_id = finished_run(ops(client), ledger)
    menu = Menu(
        ops(client), scripted(["8", run_id[:12], "APPLY 2", "0"]), console, "demo", "env",
        today=TODAY, ledger_path=ledger_path,
    )
    assert menu.run() == 0
    with Ledger(ledger_path) as ledger:
        assert ledger.runs(1)[0].mode == "undo"


def test_cli_changes_plan_demo_prints_preview_and_exits_zero(tmp_path):
    console = Console(record=True, width=140)
    ledger_path = tmp_path / "ledger.db"
    code = main(
        ["changes", "plan", str(EXAMPLE), "--demo", "--ledger", str(ledger_path)],
        ask=scripted([]), console=console,
    )
    text = console.export_text()
    assert code == 0
    assert "Planned changes" in text
    assert "PRJ-0001" in text
    assert "$308,000.00 → $320,000.00" in text
    assert "2 changes, 1 no_change" in text
    assert "Dry run" in text
    with Ledger(ledger_path) as ledger:
        assert ledger.runs()[0].mode == "dry_run"


def test_cli_ledger_command_needs_no_api(tmp_path):
    console = Console(record=True, width=140)
    code = main(["ledger", "--ledger", str(tmp_path / "empty.db")], console=console)
    assert code == 0
    assert "0 runs" in console.export_text()

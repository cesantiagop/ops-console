import sqlite3

import pytest

from ops_console.flow import changes_file, undo_run
from ops_console.ledger import Ledger
from tests.changes_support import finished_run, ops, recording_console, scripted


def snapshot(api):
    return {p.code: (p.name, p.status, p.budget_cents, p.end_date) for p in api.list("projects")}


def test_ledger_refuses_update_and_delete(client, tmp_path):
    with Ledger(tmp_path / "l.db") as ledger:
        run_id = finished_run(ops(client), ledger)
        with pytest.raises(sqlite3.DatabaseError, match="append-only"):
            ledger.execute("UPDATE run_rows SET outcome = 'applied' WHERE run_id = ?", run_id)
        with pytest.raises(sqlite3.DatabaseError, match="append-only"):
            ledger.execute("DELETE FROM run_rows WHERE run_id = ?", run_id)
        with pytest.raises(sqlite3.DatabaseError, match="append-only"):
            ledger.execute("UPDATE runs SET status = 'running' WHERE run_id = ?", run_id)
        with pytest.raises(sqlite3.DatabaseError, match="append-only"):
            ledger.execute("UPDATE runs SET n_applied = 99 WHERE run_id = ?", run_id)
        with pytest.raises(sqlite3.DatabaseError, match="append-only"):
            ledger.execute("DELETE FROM runs WHERE run_id = ?", run_id)
        assert ledger.run(run_id).status == "done"
        assert len(ledger.run_rows(run_id)) == 4


def test_running_run_can_only_be_finished_not_rewritten(tmp_path):
    with Ledger(tmp_path / "l.db") as ledger:
        run_id = ledger.start_run("apply", "f.csv", "0" * 64, 1, 0)
        with pytest.raises(sqlite3.DatabaseError, match="append-only"):
            ledger.execute("UPDATE runs SET source_file = 'other.csv' WHERE run_id = ?", run_id)
        ledger.finish_run(run_id, "failed")
        assert ledger.run(run_id).status == "failed"


def test_undo_round_trip_restores_every_touched_field(client, tmp_path):
    api = ops(client)
    original = snapshot(api)
    with Ledger(tmp_path / "l.db") as ledger:
        applied_id = finished_run(api, ledger)
        assert snapshot(api) != original

        console = recording_console()
        code = undo_run(api, applied_id, ledger, console, scripted(["APPLY 2"]), apply=True)
        assert code == 0
        assert snapshot(api) == original

        undo = ledger.runs(1)[0]
        assert undo.mode == "undo"
        assert undo.source_file == f"undo:{applied_id}"
        assert (undo.status, undo.n_applied) == ("done", 2)
        assert undo.run_id != applied_id


def test_undo_without_apply_is_a_dry_run(client, tmp_path):
    api = ops(client)
    with Ledger(tmp_path / "l.db") as ledger:
        applied_id = finished_run(api, ledger)
        changed = snapshot(api)
        undo_run(api, applied_id, ledger, recording_console(), scripted([]), apply=False)
        assert snapshot(api) == changed
        assert ledger.runs(1)[0].mode == "dry_run"


def test_undo_unknown_run_is_an_input_error(client, tmp_path):
    with Ledger(tmp_path / "l.db") as ledger:
        console = recording_console()
        code = undo_run(ops(client), "deadbeef", ledger, console, scripted([]), apply=True)
    assert code == 1
    assert "No run with id" in console.export_text()


def test_missing_file_is_a_red_line_not_a_traceback(client, tmp_path):
    with Ledger(tmp_path / "l.db") as ledger:
        console = recording_console()
        code = changes_file(
            ops(client), str(tmp_path / "nope.csv"), ledger, console, scripted([]), apply=False
        )
    assert code == 1
    assert "Cannot read" in console.export_text()
    assert "Traceback" not in console.export_text()

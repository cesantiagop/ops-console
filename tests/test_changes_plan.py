from ops_console.apply import apply_plan, run_plan
from ops_console.flow import changes_file
from ops_console.ledger import Ledger
from ops_console.plan import plan_from_file
from tests.changes_support import EXAMPLE, ops, recording_console, scripted, write_csv


def by_code(api):
    return {p.code: p for p in api.list("projects")}


def run_example(api, ledger, apply, confirm):
    plan, sha = plan_from_file(api, EXAMPLE)
    return plan, run_plan(
        api, plan, ledger, mode="apply", source_file=str(EXAMPLE), source_sha256=sha,
        apply=apply, confirm=confirm,
    )


def test_row_at_desired_value_is_no_change_and_changes_carry_the_read_version(client):
    api = ops(client)
    current = by_code(api)
    path = write_csv(
        client.db_path.parent, "code,status\nPRJ-0003,closed\nPRJ-0001,on_hold\n"
    )
    plan, _ = plan_from_file(api, path)
    assert [u.code for u in plan.no_change] == ["PRJ-0003"]
    (change,) = plan.changes
    assert change.code == "PRJ-0001"
    assert change.version == current["PRJ-0001"].version
    (fc,) = change.fields
    assert (fc.field, fc.old, fc.new) == ("status", "active", "on_hold")


def test_dry_run_writes_nothing_to_the_api_and_records_dry_run(client, tmp_path):
    api = ops(client)
    before = by_code(api)
    with Ledger(tmp_path / "l.db") as ledger:
        _, result = run_example(api, ledger, apply=False, confirm=lambda n: True)
        run = ledger.run(result.run_id)
        rows = ledger.run_rows(result.run_id)
    assert by_code(api) == before
    assert (run.mode, run.status) == ("dry_run", "done")
    assert {r.outcome for r in rows if r.field} == {"dry_run"}
    assert {r.outcome for r in rows if not r.field} == {"no_change"}
    assert result.summary.get("dry_run") == 2


def test_wrong_confirm_text_cancels_and_applies_nothing(client, tmp_path):
    api = ops(client)
    before = by_code(api)
    console = recording_console()
    with Ledger(tmp_path / "l.db") as ledger:
        code = changes_file(
            api, str(EXAMPLE), ledger, console, scripted(["apply 2"]), apply=True
        )
        (run,) = ledger.runs()
        rows = ledger.run_rows(run.run_id)
    assert code == 0
    assert by_code(api) == before
    assert (run.mode, run.status) == ("apply", "cancelled")
    assert {r.outcome for r in rows if r.field} == {"cancelled"}
    assert "Cancelled" in console.export_text()


def test_apply_changes_values_and_records_versions(client, tmp_path):
    api = ops(client)
    before = by_code(api)
    with Ledger(tmp_path / "l.db") as ledger:
        _, result = run_example(api, ledger, apply=True, confirm=lambda n: n == 2)
        run = ledger.run(result.run_id)
        applied = [r for r in ledger.run_rows(result.run_id) if r.outcome == "applied"]
    after = by_code(api)
    assert after["PRJ-0001"].status == "on_hold"
    assert after["PRJ-0001"].budget_cents == 32000000
    assert after["PRJ-0004"].end_date == "2027-03-31"
    assert after["PRJ-0003"] == before["PRJ-0003"]  # no_change: untouched
    assert (run.status, run.n_changes, run.n_applied, run.n_no_change) == ("done", 2, 2, 1)
    assert len(applied) == 3  # 2 fields on PRJ-0001, 1 on PRJ-0004
    for row in applied:
        assert row.version_after == row.version_before + 1
        assert row.version_after == after[row.row_key].version
    assert result.summary.counts == {"applied": 2, "no_change": 1}


def test_conflict_marks_that_row_and_the_rest_still_apply(client, tmp_path):
    api = ops(client)
    plan, sha = plan_from_file(api, EXAMPLE)
    target = by_code(api)["PRJ-0001"]
    api.patch_project(target.id, target.version, name="Edited by a colleague")  # after the plan
    with Ledger(tmp_path / "l.db") as ledger:
        run_id = ledger.start_run("apply", str(EXAMPLE), sha, len(plan.changes), 1)
        summary = apply_plan(api, plan, ledger, run_id)
        ledger.finish_run(run_id, "done")
        run = ledger.run(run_id)
        rows = ledger.run_rows(run_id)
    after = by_code(api)
    assert summary.get("conflict") == 1
    assert summary.get("applied") == 1
    assert {r.outcome for r in rows if r.row_key == "PRJ-0001" and r.field} == {"conflict"}
    assert {r.outcome for r in rows if r.row_key == "PRJ-0004"} == {"applied"}
    assert after["PRJ-0001"].status == "active"  # not overwritten
    assert after["PRJ-0001"].name == "Edited by a colleague"
    assert after["PRJ-0004"].end_date == "2027-03-31"
    assert (run.status, run.n_conflict, run.n_applied) == ("done", 1, 1)

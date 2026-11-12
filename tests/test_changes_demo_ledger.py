"""Demo mode keeps its promise: nothing saved, and runs are recorded as `demo-user`."""

from rich.console import Console

from ops_console.__main__ import DEMO_ACTOR, main
from ops_console.ledger import Ledger
from tests.changes_support import EXAMPLE


def test_demo_without_ledger_option_saves_nothing(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    code = main(["changes", "plan", str(EXAMPLE), "--demo"], console=Console(record=True))
    assert code == 0
    assert not (tmp_path / "data").exists()


def test_demo_runs_are_recorded_as_demo_user(tmp_path):
    ledger_path = tmp_path / "ledger.db"
    code = main(
        ["changes", "plan", str(EXAMPLE), "--demo", "--ledger", str(ledger_path)],
        console=Console(record=True),
    )
    assert code == 0
    with Ledger(ledger_path) as ledger:
        assert [run.actor for run in ledger.runs()] == [DEMO_ACTOR]

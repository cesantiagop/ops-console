"""Helpers shared by the tests/test_changes_*.py files."""

from pathlib import Path

from rich.console import Console

from ops_client import OpsClient
from tests.conftest import TOKEN

EXAMPLE = Path(__file__).resolve().parent.parent / "examples" / "projects_changes.csv"


def ops(http) -> OpsClient:
    return OpsClient(token=TOKEN, http=http, sleep=lambda s: None)


def write_csv(tmp_path: Path, text: str, name: str = "changes.csv", bom: bool = False) -> Path:
    path = tmp_path / name
    data = text.encode("utf-8")
    path.write_bytes((b"\xef\xbb\xbf" if bom else b"") + data)
    return path


def scripted(answers):
    queue = list(answers)

    def ask(prompt):
        if not queue:
            raise EOFError
        return queue.pop(0)

    return ask


def finished_run(api, ledger) -> str:
    """Apply the example changeset for real (in a test db) and return the run id."""
    from ops_console.apply import run_plan
    from ops_console.plan import plan_from_file

    plan, sha = plan_from_file(api, EXAMPLE)
    return run_plan(
        api, plan, ledger, mode="apply", source_file=str(EXAMPLE), source_sha256=sha,
        apply=True, confirm=lambda n: True,
    ).run_id


def recording_console() -> Console:
    return Console(record=True, width=140)

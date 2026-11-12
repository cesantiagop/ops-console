import sqlite3
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from rich.console import Console

from ops_client import OpsClient, ServerError
from ops_console.menu import Menu
from tests.conftest import TOKEN

TODAY = date(2026, 7, 1)


def scripted(answers):
    queue = list(answers)

    def ask(prompt):
        if not queue:
            raise EOFError
        return queue.pop(0)

    return ask


def run_menu(http, answers, token_source="env", client=None, color=False):
    console = Console(record=True, width=120, force_terminal=color, color_system="standard")
    client = client or OpsClient(token=TOKEN, http=http, sleep=lambda s: None)
    code = Menu(client, scripted(answers), console, "demo (synthetic data)", token_source,
                today=TODAY).run()
    assert code == 0
    return console


def db_rows(client, sql, *args):
    conn = sqlite3.connect(client.db_path)
    try:
        return conn.execute(sql, args).fetchall()
    finally:
        conn.close()


def test_search_projects_all(client):
    text = run_menu(client, ["2", "", "", "0"]).export_text()
    assert "Projects" in text
    assert "PRJ-0001" in text
    assert "25 projects" in text


def test_search_filters_case_insensitive(client):
    code, status = db_rows(client, "SELECT code, status FROM projects WHERE id = 7")[0]
    text = run_menu(client, ["2", code.lower(), status.upper(), "0"]).export_text()
    assert code in text
    assert "1 projects" in text
    assert "PRJ-0001" not in text


def test_project_detail_panel_and_tasks(client):
    text = run_menu(client, ["3", "PRJ-0001", "0"]).export_text()
    assert "PRJ-0001" in text
    assert "Budget:" in text
    assert "Tasks" in text
    assert "Hours logged" in text
    assert "Labor cost ($)" in text
    assert "% of budget used" in text
    assert "Traceback" not in text


def test_project_detail_unknown_code_is_red_line(client):
    console = run_menu(client, ["3", "NOPE", "0"], color=True)
    styled = console.export_text(styles=True, clear=False)
    text = console.export_text()
    assert "No project with code 'NOPE'" in text
    assert "Traceback" not in text
    assert "\x1b[31m" in styled  # red


def test_bad_date_is_red_line_and_menu_continues(client):
    text = run_menu(client, ["4", "2026-13-45", "0"]).export_text()
    assert "is not a date" in text
    assert text.count("ops-console —") == 2  # menu shown again after the error


def test_range_over_twelve_weeks_asks_for_shorter(client):
    text = run_menu(client, ["4", "2026-01-05", "2026-06-30", "0"]).export_text()
    assert "maximum is 12" in text


def test_hours_two_weeks_and_grand_total(client):
    text = run_menu(client, ["4", "2026-03-02", "2026-03-15", "0"]).export_text()
    header = next(line for line in text.splitlines() if "Person" in line)
    assert "03-02" in header
    assert "03-09" in header
    assert "03-16" not in header
    assert "03-23" not in header
    minutes = db_rows(
        client, "SELECT SUM(minutes) FROM time_entries WHERE date_performed BETWEEN ? AND ?",
        "2026-03-02", "2026-03-15",
    )[0][0]
    expected = (Decimal(minutes) / 60).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)
    rows = [line.replace("│", " ").split() for line in text.splitlines()]
    total_row = next(cells for cells in rows if cells[:1] == ["Total"] and len(cells) > 2)
    assert total_row[-1] == str(expected)


def test_approvals_waiting_count_matches_db(client):
    submitted = db_rows(client, "SELECT COUNT(*) FROM approvals WHERE status = 'submitted'")[0][0]
    assert submitted > 0
    text = run_menu(client, ["5", "0"]).export_text()
    assert f"{submitted} approvals waiting" in text
    assert "Days waiting" in text


def test_health_shows_token_source_not_token(client):
    text = run_menu(client, ["1", "0"], token_source="keyring").export_text()
    assert "Token source: keyring" in text
    assert "ok" in text
    assert "ms" in text
    assert TOKEN not in text


def test_ops_error_is_red_line_and_menu_continues(client):
    class Broken(OpsClient):
        def health(self):
            raise ServerError("boom")

    broken = Broken(token=TOKEN, http=client, sleep=lambda s: None)
    console = run_menu(client, ["1", "0"], client=broken, color=True)
    styled = console.export_text(styles=True, clear=False)
    text = console.export_text()
    assert "ServerError: boom" in text
    assert "Traceback" not in text
    assert "\x1b[31m" in styled
    assert text.count("ops-console —") == 2


def test_unknown_choice_and_end_of_input_exit_cleanly(client):
    text = run_menu(client, ["9"]).export_text()  # no "0": input ends, still exit code 0
    assert "Unknown choice" in text



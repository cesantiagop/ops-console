import pytest

from ops_console.changeset import ChangesetError, parse_changeset
from ops_console.plan import plan_from_file
from tests.changes_support import ops, write_csv


def test_valid_file_gives_desired_values(tmp_path):
    path = write_csv(
        tmp_path,
        "code,name,status,budget_dollars,end_date\n"
        'PRJ-0001,New name,on_hold,"12,500.50",2027-01-31\n'
        "PRJ-0002,,,,NULL\n"
        "PRJ-0003,,closed,0,\n",
    )
    first, second, third = parse_changeset(path)
    assert first.code == "PRJ-0001"
    assert first.line == 2
    assert first.values == {
        "name": "New name", "status": "on_hold", "budget_cents": 1250050, "end_date": "2027-01-31",
    }
    assert second.values == {"end_date": None}  # NULL = set to null; blank cells = absent
    assert third.values == {"status": "closed", "budget_cents": 0}


def test_dollars_use_decimal_cents_and_refuse_a_third_decimal(tmp_path):
    ok = write_csv(tmp_path, "code,budget_dollars\nPRJ-0001,0.29\nPRJ-0002,1234\n", "ok.csv")
    assert [d.values["budget_cents"] for d in parse_changeset(ok)] == [29, 123400]

    bad = write_csv(tmp_path, "code,budget_dollars\nPRJ-0001,1.005\n", "bad.csv")
    with pytest.raises(ChangesetError) as caught:
        parse_changeset(bad)
    (problem,) = caught.value.problems
    assert (problem.line, problem.column) == (2, "budget_dollars")
    assert "more than 2 decimals" in problem.message


def test_utf8_bom_is_ignored(tmp_path):
    path = write_csv(tmp_path, "code,status\nPRJ-0001,closed\n", bom=True)
    (only,) = parse_changeset(path)
    assert only.code == "PRJ-0001"
    assert only.values == {"status": "closed"}


def test_three_different_errors_are_raised_once_with_line_numbers(tmp_path, client):
    path = write_csv(
        tmp_path,
        "code,status,colour\n"           # line 1: unknown column
        "PRJ-0001,paused,red\n"          # line 2: bad status
        "PRJ-0001,closed,\n"             # line 3: duplicate code
        "PRJ-9999,closed,\n",            # line 4: unknown code (checked against the API)
    )
    before = [(p.id, p.version) for p in ops(client).list("projects")]
    with pytest.raises(ChangesetError) as caught:
        plan_from_file(ops(client), path)
    found = {(p.line, p.column) for p in caught.value.problems}
    assert found == {(1, "colour"), (2, "status"), (3, "code"), (4, "code")}
    text = str(caught.value)
    assert "line 2" in text
    assert "unknown code PRJ-9999" in text
    after = [(p.id, p.version) for p in ops(client).list("projects")]
    assert before == after  # nothing applied


def test_missing_code_column(tmp_path):
    path = write_csv(tmp_path, "name\nSomething\n")
    with pytest.raises(ChangesetError) as caught:
        parse_changeset(path)
    assert any("missing required column" in p.message for p in caught.value.problems)

from rich.console import Console

from ops_console.__main__ import main
from ops_console.demo import open_demo


def test_demo_starts_exits_and_removes_temp_db():
    with open_demo() as demo:
        path = demo.db_path
        assert path.exists()
        assert len(list(demo.client.list("projects"))) == 25
    assert not path.exists()
    assert not path.parent.exists()


def test_main_demo_with_exit_answer():
    answers = iter(["0"])
    console = Console(record=True, width=120)
    code = main(["--demo"], ask=lambda prompt: next(answers), console=console)
    text = console.export_text()
    assert code == 0
    assert "synthetic" in text
    assert "ops-console — demo (synthetic data)" in text


def test_main_demo_runs_search_and_never_shows_token():
    answers = iter(["1", "2", "", "", "0"])
    console = Console(record=True, width=120)
    assert main(["--demo"], ask=lambda prompt: next(answers), console=console) == 0
    text = console.export_text()
    assert "Token source: demo" in text
    assert "25 projects" in text

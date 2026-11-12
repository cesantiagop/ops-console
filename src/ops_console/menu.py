"""The menu loop. `ask` (input function) and `console` (rich Console) are injected."""

from __future__ import annotations

import time
from collections.abc import Callable
from datetime import date, timedelta

from rich.console import Console
from rich.markup import escape

from ops_client import OpsClient, OpsError

from . import reports, views

Ask = Callable[[str], str]

# `extract` windows on created_at (ADR 0003); an entry is created on or after the day it
# covers, usually within days. Read this far past the end date, then filter on date_performed.
CREATED_LAG_DAYS = 7

MENU = (
    (1, "Health check"),
    (2, "Search projects"),
    (3, "Project detail"),
    (4, "Hours by person by week"),
    (5, "Approvals waiting"),
    (0, "Exit"),
)


class InputError(Exception):
    """Bad user input: shown as one red line, then back to the menu."""


class Menu:
    def __init__(
        self,
        client: OpsClient,
        ask: Ask,
        console: Console,
        label: str,
        token_source: str,
        today: date | None = None,
    ) -> None:
        self.client = client
        self.ask = ask
        self.console = console
        self.label = label
        self.token_source = token_source
        self.today = today or date.today()
        self._actions: dict[str, Callable[[], None]] = {
            "1": self.health,
            "2": self.search_projects,
            "3": self.project_detail,
            "4": self.hours,
            "5": self.approvals,
        }

    # -- loop --------------------------------------------------------------------------------

    def red(self, message: str) -> None:
        self.console.print(f"[red]{escape(message)}[/red]")

    def show_menu(self) -> None:
        self.console.print(f"\n[bold]ops-console — {escape(self.label)}[/bold]")
        for number, text in MENU:
            self.console.print(f" {number}  {text}")

    def run(self) -> int:
        """Loop until `0`, Ctrl+C or end of input. Returns the exit code (always 0)."""
        try:
            while True:
                self.show_menu()
                choice = self.ask("Choose: ").strip()
                if choice == "0":
                    return 0
                action = self._actions.get(choice)
                if action is None:
                    self.red(f"Unknown choice {choice!r}; enter a number from the menu.")
                    continue
                try:
                    action()
                except InputError as exc:
                    self.red(str(exc))
                except OpsError as exc:
                    self.red(f"{type(exc).__name__}: {exc}")
        except (KeyboardInterrupt, EOFError):
            self.console.print("\nBye.")
            return 0

    # -- actions -----------------------------------------------------------------------------

    def health(self) -> None:
        started = time.perf_counter()
        body = self.client.health()
        elapsed_ms = round((time.perf_counter() - started) * 1000)
        self.console.print(f"API status:   {escape(str(body.get('status')))}")
        self.console.print(f"API version:  {escape(str(body.get('version')))}")
        self.console.print(f"Token source: {self.token_source}")
        self.console.print(f"Round trip:   {elapsed_ms} ms")

    def search_projects(self) -> None:
        text = self.ask("Search text (blank = all): ")
        status = self.ask("Status (blank = any): ")
        found = reports.search_projects(self.client.list("projects"), text, status)
        self.console.print(views.projects_table(found))

    def project_detail(self) -> None:
        code = self.ask("Project code (e.g. PRJ-0007): ")
        project = reports.find_project(self.client.list("projects"), code)
        if project is None:
            raise InputError(f"No project with code {code.strip()!r}.")
        tasks = list(self.client.list("tasks", project_id=project.id))
        entries = list(self.client.list("time_entries", project_id=project.id))
        summary = reports.project_summary(project, tasks, entries)
        self.console.print(views.project_panel(summary))
        self.console.print(views.tasks_table(summary))
        self.console.print(views.project_footer(summary))

    def hours(self) -> None:
        start = self._ask_date("Start date (YYYY-MM-DD): ")
        raw_end = self.ask("End date, inclusive (blank = start + 27 days): ").strip()
        end = self._parse_date(raw_end) if raw_end else reports.default_end(start)
        if end < start:
            raise InputError("End date is before the start date.")
        weeks = reports.weeks_in_range(start, end)
        if len(weeks) > reports.MAX_WEEKS:
            raise InputError(
                f"That range spans {len(weeks)} weeks; the maximum is {reports.MAX_WEEKS}. "
                "Enter a shorter range."
            )
        entries = self.client.extract(
            "time_entries", start, end + timedelta(days=CREATED_LAG_DAYS)
        )
        users = {u.id: u for u in self.client.list("users")}
        grid = reports.hours_grid(entries, users, start, end)
        self.console.print(views.hours_table(grid))

    def approvals(self) -> None:
        waiting = list(self.client.list("approvals", status="submitted"))
        users = {u.id: u for u in self.client.list("users")}
        report = reports.approvals_waiting(waiting, users, self.today)
        self.console.print(views.waiting_table(report))
        self.console.print(views.waiting_by_week(report))

    # -- input helpers -----------------------------------------------------------------------

    @staticmethod
    def _parse_date(text: str) -> date:
        try:
            return reports.parse_iso_date(text.strip())
        except ValueError as exc:
            raise InputError(str(exc)) from None

    def _ask_date(self, prompt: str) -> date:
        return self._parse_date(self.ask(prompt))

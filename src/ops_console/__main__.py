"""`python -m ops_console [--base-url URL] [--demo]`; also the script entry `ops-console`.

Subcommands (M4): `changes plan FILE`, `changes apply FILE [--apply] [--yes]`,
`ledger [RUN_ID]`, `undo RUN_ID [--apply]`. Without one, the menu runs.
"""

from __future__ import annotations

import argparse
import os
import sys
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date
from pathlib import Path

import keyring
from keyring.errors import KeyringError
from rich.console import Console

from ops_client import OpsClient, OpsError
from ops_client.auth import ENV_VAR, SERVICE, USERNAME

from . import flow
from .demo import DEMO_TODAY, open_demo
from .ledger import DEFAULT_PATH, Ledger
from .menu import Ask, Menu

DEFAULT_BASE_URL = "http://127.0.0.1:8000"
DEMO_LABEL = "demo (synthetic data)"


def _add_common(parser: argparse.ArgumentParser, *, top: bool) -> None:
    """The options every command takes. On subcommands the defaults are suppressed so a value
    given before the subcommand is not overwritten."""
    unset = {} if top else {"default": argparse.SUPPRESS}
    parser.add_argument(
        "--base-url", help="API base URL",
        **({"default": DEFAULT_BASE_URL} if top else unset),
    )
    parser.add_argument(
        "--demo", action="store_true", help="in-process API on synthetic data",
        **({} if top else unset),
    )
    parser.add_argument(
        "--ledger", type=Path,
        help=f"ledger database (default {DEFAULT_PATH}; with --demo a temp file deleted on exit)",
        **({"default": None} if top else unset),
    )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="ops-console", description="Ops console")
    _add_common(parser, top=True)
    commands = parser.add_subparsers(dest="command")

    changes = commands.add_parser("changes", help="bulk change projects from a CSV")
    actions = changes.add_subparsers(dest="action", required=True)
    plan = actions.add_parser("plan", help="preview a changeset and record a dry run")
    plan.add_argument("file")
    _add_common(plan, top=False)
    apply = actions.add_parser("apply", help="dry run, or write with --apply")
    apply.add_argument("file")
    apply.add_argument("--apply", action="store_true", help="really write (asks to confirm)")
    apply.add_argument("--yes", action="store_true", help="skip the prompt (needs --apply)")
    _add_common(apply, top=False)

    ledger = commands.add_parser("ledger", help="list runs, or show one run's rows")
    ledger.add_argument("run_id", nargs="?")
    _add_common(ledger, top=False)

    undo = commands.add_parser("undo", help="undo a run through a new changeset")
    undo.add_argument("run_id")
    undo.add_argument("--apply", action="store_true", help="really write (asks to confirm)")
    _add_common(undo, top=False)
    return parser


def token_source() -> str:
    """`keyring` or `env`, by the same order as `ops_client.auth.get_token`. Never the value."""
    try:
        if keyring.get_password(SERVICE, USERNAME):
            return "keyring"
    except KeyringError:
        pass
    return "env" if os.environ.get(ENV_VAR) else "none"


@contextmanager
def _client_for(args: argparse.Namespace, console: Console) -> Iterator[tuple | None]:
    """Yield `(client, label, token_source, today)`, or None when the client cannot start."""
    if args.demo:
        console.print("[yellow]Demo mode: synthetic data, in-process API, nothing saved.[/yellow]")
        with open_demo() as demo:
            yield demo.client, DEMO_LABEL, "demo", DEMO_TODAY
        return
    try:
        client = OpsClient(base_url=args.base_url)
    except OpsError as exc:
        console.print(f"[red]{type(exc).__name__}: {exc}[/red]")
        yield None
        return
    yield client, args.base_url, token_source(), date.today()


DEMO_ACTOR = "demo-user"


@contextmanager
def _ledger_target(args: argparse.Namespace) -> Iterator[tuple[Path, str | None]]:
    """Yield (ledger path, actor). Demo mode without --ledger uses a temp ledger deleted on
    exit, so "nothing saved" stays true; demo runs are recorded as `demo-user`."""
    actor = DEMO_ACTOR if args.demo else None
    if args.ledger is not None:
        yield args.ledger, actor
    elif args.demo and args.command != "ledger":
        with tempfile.TemporaryDirectory(prefix="ops-console-ledger-") as folder:
            yield Path(folder) / "ledger.db", actor
    else:
        yield DEFAULT_PATH, actor


def _run_command(
    args: argparse.Namespace, client: OpsClient, console: Console, ask: Ask
) -> int:
    with Ledger(args.ledger, actor=args.ledger_actor) as ledger:
        if args.command == "undo":
            return flow.undo_run(client, args.run_id, ledger, console, ask, apply=args.apply)
        apply = args.action == "apply" and args.apply
        yes = args.action == "apply" and args.yes
        if yes and not apply:
            console.print("[yellow]--yes does nothing without --apply; this is a dry run.[/yellow]")
            yes = False
        return flow.changes_file(client, args.file, ledger, console, ask, apply=apply, yes=yes)


def main(
    argv: list[str] | None = None,
    ask: Ask | None = None,
    console: Console | None = None,
) -> int:
    args = _build_parser().parse_args(argv)
    console = console or Console()
    ask = ask or input

    with _ledger_target(args) as (ledger_path, ledger_actor):
        args.ledger, args.ledger_actor = ledger_path, ledger_actor

        if args.command == "ledger":  # reads the local ledger only: no API, no token
            with Ledger(args.ledger) as ledger:
                return flow.show_ledger(ledger, console, args.run_id)

        with _client_for(args, console) as started:
            if started is None:
                return 1
            client, label, source, today = started
            if args.command:
                return _run_command(args, client, console, ask)
            return Menu(
                client, ask, console, label, source, today=today,
                ledger_path=args.ledger, ledger_actor=args.ledger_actor,
            ).run()


if __name__ == "__main__":
    sys.exit(main())

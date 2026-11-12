"""`python -m ops_console [--base-url URL] [--demo]`; also the script entry `ops-console`."""

from __future__ import annotations

import argparse
import os
import sys

import keyring
from keyring.errors import KeyringError
from rich.console import Console

from ops_client import OpsClient, OpsError
from ops_client.auth import ENV_VAR, SERVICE, USERNAME

from .demo import DEMO_TODAY, open_demo
from .menu import Ask, Menu

DEFAULT_BASE_URL = "http://127.0.0.1:8000"
DEMO_LABEL = "demo (synthetic data)"


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="ops-console", description="Read-only ops console")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL, help="API base URL")
    parser.add_argument("--demo", action="store_true", help="in-process API on synthetic data")
    return parser


def token_source() -> str:
    """`keyring` or `env`, by the same order as `ops_client.auth.get_token`. Never the value."""
    try:
        if keyring.get_password(SERVICE, USERNAME):
            return "keyring"
    except KeyringError:
        pass
    return "env" if os.environ.get(ENV_VAR) else "none"


def main(
    argv: list[str] | None = None,
    ask: Ask | None = None,
    console: Console | None = None,
) -> int:
    args = _build_parser().parse_args(argv)
    console = console or Console()
    ask = ask or input

    if args.demo:
        console.print("[yellow]Demo mode: synthetic data, in-process API, nothing saved.[/yellow]")
        with open_demo() as demo:
            menu = Menu(demo.client, ask, console, DEMO_LABEL, "demo", today=DEMO_TODAY)
            return menu.run()

    try:
        client = OpsClient(base_url=args.base_url)
    except OpsError as exc:
        console.print(f"[red]{type(exc).__name__}: {exc}[/red]")
        return 1
    return Menu(client, ask, console, args.base_url, token_source()).run()


if __name__ == "__main__":
    sys.exit(main())

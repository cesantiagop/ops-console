"""CLI: `python -m ops_api seed ...` and `python -m ops_api serve ...`."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

DEFAULT_DB = "data/ops_api.db"
DEMO_TOKEN = "dev-token"


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="ops_api", description="Mock PSA API (synthetic data)")
    sub = parser.add_subparsers(dest="command", required=True)

    seed = sub.add_parser("seed", help="drop and rebuild the synthetic database")
    seed.add_argument("--db", default=DEFAULT_DB)
    seed.add_argument("--seed", type=int, default=42)

    serve = sub.add_parser("serve", help="run the API with uvicorn")
    serve.add_argument("--db", default=DEFAULT_DB)
    serve.add_argument("--port", type=int, default=8000)
    serve.add_argument("--chaos-rows", type=int, default=0)
    serve.add_argument("--fault-rate", type=float, default=0.0)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)

    if args.command == "seed":
        from .seed import build_db

        counts = build_db(args.db, seed=args.seed)
        for table, count in counts.items():
            print(f"{table}: {count}")
        return 0

    import uvicorn

    from .app import create_app

    if not Path(args.db).exists():
        print(f"database not found: {args.db} (run `python -m ops_api seed`)", file=sys.stderr)
        return 1
    token = os.environ.get("OPS_API_TOKEN")
    if not token:
        token = DEMO_TOKEN
        print(f"warning: OPS_API_TOKEN not set, using demo token '{DEMO_TOKEN}'", file=sys.stderr)
    app = create_app(args.db, token, chaos_rows=args.chaos_rows, fault_rate=args.fault_rate)
    uvicorn.run(app, host="127.0.0.1", port=args.port)
    return 0


if __name__ == "__main__":
    sys.exit(main())

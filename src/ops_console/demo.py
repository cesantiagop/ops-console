"""`--demo`: a seeded temp database behind an in-process API. No server, no token setup."""

from __future__ import annotations

import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from fastapi.testclient import TestClient

from ops_api.app import create_app
from ops_api.seed import NOW, build_db
from ops_client import OpsClient

DEMO_TOKEN = "demo"
DEMO_SEED = 42
DEMO_TODAY = NOW.date()  # the synthetic world's fixed "now"


@dataclass(frozen=True)
class Demo:
    client: OpsClient
    db_path: Path


@contextmanager
def open_demo() -> Iterator[Demo]:
    """Seed a temp db (seed 42), build the API, yield a client. The temp files go on exit."""
    with tempfile.TemporaryDirectory(prefix="ops-console-demo-") as tmp:
        db_path = Path(tmp) / "demo.db"
        build_db(db_path, seed=DEMO_SEED)
        http = TestClient(create_app(db_path, DEMO_TOKEN))
        try:
            yield Demo(OpsClient(token=DEMO_TOKEN, http=http), db_path)
        finally:
            http.close()

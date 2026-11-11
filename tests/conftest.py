import shutil

import pytest
from fastapi.testclient import TestClient

from ops_api.app import create_app
from ops_api.seed import build_db

TOKEN = "test-token"
AUTH = {"Authorization": f"Bearer {TOKEN}"}


@pytest.fixture(scope="session")
def seeded(tmp_path_factory):
    """Seed once per session (seed=42). Returns (db_path, row_counts). Tests never write to it."""
    path = tmp_path_factory.mktemp("seed") / "base.db"
    return path, build_db(path, seed=42)


@pytest.fixture(scope="session")
def base_db(seeded):
    return seeded[0]


@pytest.fixture(scope="session")
def counts(seeded):
    return seeded[1]


@pytest.fixture
def make_client(base_db, tmp_path):
    """Factory: a TestClient on a private copy of the seeded db, so writes never leak."""
    made = []

    def factory(**options):
        copy = tmp_path / f"copy{len(made)}.db"
        shutil.copy(base_db, copy)
        client = TestClient(create_app(copy, TOKEN, **options))
        client.headers.update(AUTH)
        client.db_path = copy
        made.append(client)
        return client

    yield factory
    for client in made:
        client.close()


@pytest.fixture
def client(make_client):
    return make_client()

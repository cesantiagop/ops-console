import logging
import sqlite3

import httpx
import pytest

from ops_client import (
    AuthError,
    ConflictError,
    NotFoundError,
    OpsClient,
    Project,
    RateLimitError,
    User,
)
from ops_client import auth as auth_mod
from tests.conftest import TOKEN


class FakeSleep:
    def __init__(self):
        self.calls = []

    def __call__(self, seconds):
        self.calls.append(seconds)


class CountingHttp:
    """Delegates to a real client and counts requests."""

    def __init__(self, inner):
        self._inner = inner
        self.requests = 0

    def request(self, *args, **kwargs):
        self.requests += 1
        return self._inner.request(*args, **kwargs)


def make(http, sleep=None, **kw):
    return OpsClient(token=kw.pop("token", TOKEN), http=http, sleep=sleep or FakeSleep(), **kw)


def test_health_get_and_unknown_resource(client):
    spy = CountingHttp(client)
    ops = make(spy)
    assert ops.health()["status"] == "ok"
    user = ops.get("users", 1)
    assert isinstance(user, User)
    assert user.id == 1
    assert isinstance(ops.get("projects", 1), Project)
    before = spy.requests
    with pytest.raises(ValueError):
        ops.get("nope", 1)
    with pytest.raises(ValueError):
        list(ops.list("nope"))
    assert spy.requests == before


def test_list_projects_returns_all_models(client):
    projects = list(make(client).list("projects"))
    assert len(projects) == 25
    assert all(isinstance(p, Project) for p in projects)


def test_retry_on_429(make_client, caplog):
    sleep = FakeSleep()
    ops = make(make_client(fault_rate=0.5, rng_seed=1), sleep)
    with caplog.at_level(logging.INFO):
        users = list(ops.list("users"))
    assert len(users) == 40
    assert 1 in sleep.calls
    assert TOKEN not in caplog.text
    assert TOKEN not in repr(ops)


def test_retries_used_up(make_client):
    sleep = FakeSleep()
    ops = make(make_client(fault_rate=1.0), sleep, max_retries=4)
    with pytest.raises(RateLimitError):
        list(ops.list("users"))
    assert len(sleep.calls) == 4


def test_auth_and_not_found(client):
    sleep = FakeSleep()
    with pytest.raises(AuthError):
        make(client, sleep, token="wrong").get("users", 1)
    assert sleep.calls == []
    with pytest.raises(NotFoundError):
        make(client, sleep).get("users", 99999)


def test_patch_project_conflict_and_success(client):
    ops = make(client)
    project = ops.get("projects", 1)
    updated = ops.patch_project(1, project.version, name="Renamed")
    assert updated.name == "Renamed"
    assert updated.version == project.version + 1
    with pytest.raises(ConflictError) as info:
        ops.patch_project(1, project.version, name="Again")
    assert info.value.current["version"] == updated.version
    assert info.value.error == "version_conflict"


def test_approve_and_stale_reject(client):
    ops = make(client)
    conn = sqlite3.connect(client.db_path)
    row = conn.execute(
        "SELECT id, version FROM approvals WHERE status = 'submitted' LIMIT 1"
    ).fetchone()
    conn.close()
    done = ops.approve(row[0], row[1], approver_id=1)
    assert done.status == "approved"
    with pytest.raises(ConflictError):
        ops.reject(row[0], row[1], approver_id=1)


def test_token_keyring_wins_over_env(monkeypatch):
    monkeypatch.setenv("OPS_API_TOKEN", "from-env")
    monkeypatch.setattr(auth_mod.keyring, "get_password", lambda *a: "from-keyring")
    assert auth_mod.get_token() == "from-keyring"


def test_token_env_when_keyring_empty(monkeypatch):
    monkeypatch.setenv("OPS_API_TOKEN", "from-env")
    monkeypatch.setattr(auth_mod.keyring, "get_password", lambda *a: None)
    assert auth_mod.get_token() == "from-env"


def test_token_env_when_keyring_has_no_backend(monkeypatch):
    from keyring.errors import NoKeyringError

    def boom(*args):
        raise NoKeyringError("no backend")

    monkeypatch.setenv("OPS_API_TOKEN", "from-env")
    monkeypatch.setattr(auth_mod.keyring, "get_password", boom)
    assert auth_mod.get_token() == "from-env"


def test_token_missing_raises(monkeypatch):
    monkeypatch.delenv("OPS_API_TOKEN", raising=False)
    monkeypatch.setattr(auth_mod.keyring, "get_password", lambda *a: None)
    with pytest.raises(AuthError):
        auth_mod.get_token()


def test_transport_error_retries_then_server_error(monkeypatch):
    from ops_client import ServerError

    class Broken:
        def request(self, *a, **k):
            raise httpx.ConnectError("down")

    sleep = FakeSleep()
    with pytest.raises(ServerError):
        OpsClient(token=TOKEN, http=Broken(), sleep=sleep, max_retries=2).health()
    assert len(sleep.calls) == 2

import sqlite3


def _snapshot(path) -> dict[int, tuple[str, int]]:
    conn = sqlite3.connect(path)
    cursor = conn.execute("SELECT id, updated_at, version FROM time_entries")
    rows = {r[0]: (r[1], r[2]) for r in cursor}
    conn.close()
    return rows


def _changed_ids(client) -> set[int]:
    before = _snapshot(client.db_path)
    assert client.get("/v1/time_entries").status_code == 200
    after = _snapshot(client.db_path)
    changed = {i for i in before if before[i] != after[i]}
    for row_id in changed:
        assert after[row_id][1] == before[row_id][1] + 1
        assert after[row_id][0] != before[row_id][0]
    return changed


def test_chaos_edits_rows_repeatably(make_client):
    first = _changed_ids(make_client(chaos_rows=5, rng_seed=1))
    second = _changed_ids(make_client(chaos_rows=5, rng_seed=1))
    other = _changed_ids(make_client(chaos_rows=5, rng_seed=2))
    assert len(first) == 5
    assert first == second
    assert first != other


def test_chaos_is_off_by_default(client):
    assert _changed_ids(client) == set()


def test_fault_rate_returns_429(make_client):
    client = make_client(fault_rate=1.0)
    resp = client.get("/v1/time_entries")
    assert resp.status_code == 429
    assert resp.headers["Retry-After"] == "1"
    assert client.get("/v1/projects/1").status_code == 429
    assert client.get("/v1/health").status_code == 200


def test_unauthorised_beats_fault(make_client):
    client = make_client(fault_rate=1.0)
    assert client.get("/v1/users", headers={"Authorization": "Bearer wrong"}).status_code == 401

import logging
import sqlite3
from datetime import date

import httpx
import pytest

from ops_client import IncompleteWindowError, OpsClient
from ops_client.paging import naive_read_by_updated_at
from tests.conftest import TOKEN

START, END = date(2026, 1, 1), date(2026, 7, 15)


def all_ids(client):
    conn = sqlite3.connect(client.db_path)
    try:
        return {r[0] for r in conn.execute("SELECT id FROM time_entries")}
    finally:
        conn.close()


class Spy:
    """Wraps an http client; records every row seen per id and can edit list responses."""

    def __init__(self, inner, drop_first_row=False):
        self._inner = inner
        self.max_version = {}
        self.drop_first_row = drop_first_row

    def request(self, *args, **kwargs):
        response = self._inner.request(*args, **kwargs)
        if response.status_code != 200:
            return response
        body = response.json()
        for row in body.get("results", []):
            if "version" in row:
                seen = self.max_version.get(row["id"], 0)
                self.max_version[row["id"]] = max(seen, row["version"])
        params = kwargs.get("params") or {}
        if (
            self.drop_first_row
            and params.get("created_between")
            and params.get("page") == 1
            and body["results"]
        ):
            body["results"] = body["results"][1:]
            return httpx.Response(200, json=body)
        return response


def ops_for(http):
    return OpsClient(token=TOKEN, http=http, sleep=lambda s: None)


def test_extract_no_chaos(client, caplog):
    ops = ops_for(client)
    with caplog.at_level(logging.INFO):
        rows = ops.extract("time_entries", START, END)
    assert [r.id for r in rows] == sorted(all_ids(client))
    assert TOKEN not in caplog.text
    assert "window" in caplog.text


def test_extract_under_chaos(make_client):
    client = make_client(chaos_rows=20)
    spy = Spy(client)
    rows = ops_for(spy).extract("time_entries", START, END)
    assert {r.id for r in rows} == all_ids(client)
    assert [r.id for r in rows] == sorted(r.id for r in rows)
    assert all(r.version == spy.max_version[r.id] for r in rows)


def test_naive_updated_at_paging_skips_rows(make_client):
    client = make_client(chaos_rows=20)
    ids = all_ids(client)
    rows = naive_read_by_updated_at(
        lambda resource, params: ops_for(client)._fetch(resource, params), "time_entries"
    )
    seen = {r["id"] for r in rows}
    missed = ids - seen
    print(f"naive read missed {len(missed)} of {len(ids)} ids")
    assert missed, "naive updated_at paging should have skipped at least one row"


def test_incomplete_window(client):
    ops = ops_for(Spy(client, drop_first_row=True))
    with pytest.raises(IncompleteWindowError) as info:
        ops.extract("time_entries", START, END)
    assert info.value.got == info.value.expected - 1
    assert info.value.window[0] >= START.isoformat()


def test_extract_rejects_bad_range(client):
    with pytest.raises(ValueError):
        ops_for(client).extract("time_entries", END, START)


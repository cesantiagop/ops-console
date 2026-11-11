import pytest

from ops_api.db import TABLES


@pytest.mark.parametrize("resource", TABLES)
def test_envelope_and_meta(client, counts, resource):
    body = client.get(f"/v1/{resource}", params={"per_page": 10}).json()
    assert set(body) == {"results", "meta"}
    assert len(body["results"]) == 10
    meta = body["meta"]
    assert meta["count"] == counts[resource]
    assert meta["page"] == 1
    assert meta["per_page"] == 10
    assert meta["page_count"] == -(-counts[resource] // 10)
    assert {"id", "created_at", "updated_at", "version"} <= set(body["results"][0])


def test_unknown_resource_is_404(client):
    assert client.get("/v1/widgets").status_code == 404


def test_paging_without_changes_yields_every_id_once(client, counts):
    seen = []
    page = 1
    while True:
        body = client.get(
            "/v1/time_entries", params={"order": "created_at:asc", "per_page": 200, "page": page}
        ).json()
        seen.extend(row["id"] for row in body["results"])
        if page >= body["meta"]["page_count"]:
            break
        page += 1
    assert len(seen) == counts["time_entries"]
    assert len(set(seen)) == counts["time_entries"]


def test_filters_are_inclusive_and_validated(client):
    # date_between: inclusive on both ends
    one_day = client.get(
        "/v1/time_entries", params={"date_between": "2026-01-05:2026-01-05", "per_page": 200}
    ).json()
    assert one_day["meta"]["count"] > 0
    assert {r["date_performed"] for r in one_day["results"]} == {"2026-01-05"}
    second_day = client.get(
        "/v1/time_entries", params={"date_between": "2026-01-06:2026-01-06"}
    ).json()
    two_days = client.get(
        "/v1/time_entries", params={"date_between": "2026-01-05:2026-01-06"}
    ).json()
    assert second_day["meta"]["count"] > 0
    assert two_days["meta"]["count"] == one_day["meta"]["count"] + second_day["meta"]["count"]

    # created_between: inclusive on both ends (all of the end day is included)
    rows = client.get(
        "/v1/time_entries", params={"order": "created_at:asc", "per_page": 200}
    ).json()["results"]
    first_day = rows[0]["created_at"][:10]
    window = client.get(
        "/v1/time_entries",
        params={"created_between": f"{first_day}:{first_day}", "per_page": 200},
    ).json()
    assert window["meta"]["count"] > 0
    assert {r["created_at"][:10] for r in window["results"]} == {first_day}
    assert rows[0]["id"] in {r["id"] for r in window["results"]}

    # approvals use date_between on week_start
    week = client.get("/v1/approvals", params={"date_between": "2026-01-05:2026-01-05"}).json()
    assert week["meta"]["count"] == 40

    # a filter that does not apply to the resource, and a bad per_page, are 422
    assert client.get("/v1/users", params={"project_id": 1}).status_code == 422
    bad = {"date_between": "2026-01-05:2026-01-06"}
    assert client.get("/v1/projects", params=bad).status_code == 422
    assert client.get("/v1/users", params={"nonsense": 1}).status_code == 422
    assert client.get("/v1/time_entries", params={"per_page": 201}).status_code == 422
    assert client.get("/v1/time_entries", params={"per_page": 0}).status_code == 422
    assert client.get("/v1/time_entries", params={"page": 0}).status_code == 422
    assert client.get("/v1/time_entries", params={"order": "minutes:asc"}).status_code == 422


def test_other_filters(client):
    body = client.get("/v1/users", params={"ids": "1,2,3"}).json()
    assert [r["id"] for r in body["results"]] == [1, 2, 3]
    body = client.get("/v1/projects", params={"status": "closed"}).json()
    assert all(r["status"] == "closed" for r in body["results"])
    body = client.get("/v1/time_entries", params={"user_id": 1, "per_page": 200}).json()
    assert body["meta"]["count"] > 0
    assert {r["user_id"] for r in body["results"]} <= {1}
    body = client.get("/v1/users", params={"updated_since": "2999-01-01T00:00:00Z"}).json()
    assert body["meta"]["count"] == 0
    assert client.get("/v1/users", params={"updated_since": "yesterday"}).status_code == 422


def test_auth(client, make_client):
    anonymous = make_client()
    anonymous.headers.pop("Authorization")
    assert anonymous.get("/v1/users").status_code == 401
    assert client.get("/v1/users", headers={"Authorization": "Bearer wrong"}).status_code == 401
    assert client.get("/v1/users", headers={"Authorization": "Basic test-token"}).status_code == 401
    assert anonymous.get("/v1/health").json() == {"status": "ok", "version": "0.1.0"}
    assert client.get("/v1/users").status_code == 200

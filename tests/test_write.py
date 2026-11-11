def test_patch_project(client):
    before = client.get("/v1/projects/1").json()["results"][0]
    resp = client.patch(
        "/v1/projects/1",
        json={"version": before["version"], "name": "Renamed", "budget_cents": 123400},
    )
    assert resp.status_code == 200
    after = resp.json()["results"][0]
    assert after["name"] == "Renamed"
    assert after["budget_cents"] == 123400
    assert after["version"] == before["version"] + 1
    assert after["updated_at"] > before["updated_at"]
    assert after["updated_at"].endswith("Z")
    assert client.get("/v1/projects/1").json()["results"][0] == after


def test_patch_stale_version_conflicts(client):
    before = client.get("/v1/projects/2").json()["results"][0]
    first = client.patch("/v1/projects/2", json={"version": before["version"], "status": "on_hold"})
    assert first.status_code == 200
    stale = client.patch("/v1/projects/2", json={"version": before["version"], "status": "closed"})
    assert stale.status_code == 409
    body = stale.json()
    assert body["error"] == "version_conflict"
    assert body["current"]["status"] == "on_hold"
    assert body["current"]["version"] == before["version"] + 1


def test_patch_rejects_bad_requests(client):
    version = client.get("/v1/projects/3").json()["results"][0]["version"]
    patch = client.patch
    assert patch("/v1/projects/3", json={"version": version, "code": "X"}).status_code == 422
    assert patch("/v1/projects/3", json={"version": version, "status": "nope"}).status_code == 422
    assert client.patch("/v1/projects/3", json={"name": "No version"}).status_code == 422
    assert client.patch("/v1/projects/3", json={"version": version}).status_code == 422
    assert client.patch("/v1/projects/999999", json={"version": 1, "name": "x"}).status_code == 404


def test_approve_then_invalid_transition(client):
    row = client.get("/v1/approvals", params={"status": "submitted"}).json()["results"][0]
    ok = client.post(
        f"/v1/approvals/{row['id']}/approve", json={"version": row["version"], "approver_id": 1}
    )
    assert ok.status_code == 200
    done = ok.json()["results"][0]
    assert done["status"] == "approved"
    assert done["approver_id"] == 1
    assert done["decided_at"].endswith("Z")
    assert done["version"] == row["version"] + 1

    again = client.post(
        f"/v1/approvals/{row['id']}/approve", json={"version": done["version"], "approver_id": 1}
    )
    assert again.status_code == 409
    assert again.json()["error"] == "invalid_transition"


def test_reject_and_validation(client):
    row = client.get("/v1/approvals", params={"status": "submitted"}).json()["results"][0]
    url = f"/v1/approvals/{row['id']}/reject"
    assert client.post(url, json={"version": row["version"]}).status_code == 422
    unknown = client.post(url, json={"version": row["version"], "approver_id": 9999})
    assert unknown.status_code == 422
    stale = client.post(url, json={"version": row["version"] + 5, "approver_id": 1})
    assert stale.status_code == 409
    assert stale.json()["error"] == "version_conflict"
    ok = client.post(url, json={"version": row["version"], "approver_id": 1})
    assert ok.json()["results"][0]["status"] == "rejected"

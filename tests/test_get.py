def test_get_existing(client):
    body = client.get("/v1/projects/1").json()
    assert len(body["results"]) == 1
    assert body["results"][0]["id"] == 1
    assert body["results"][0]["code"] == "PRJ-0001"
    assert body["meta"]["count"] == 1


def test_get_missing_is_404(client):
    assert client.get("/v1/projects/999999").status_code == 404
    assert client.get("/v1/users/0").status_code == 404
    assert client.get("/v1/widgets/1").status_code == 404

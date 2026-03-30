def test_health_endpoint_returns_ok_payload(client):
    response = client.get("/health")

    assert response.status_code == 200
    body = response.get_json()
    assert body["status"] == "ok"
    assert isinstance(body["timestamp"], str)


def test_unknown_route_returns_json_404(client):
    response = client.get("/does-not-exist")

    assert response.status_code == 404
    assert response.get_json() == {"message": "Route not found"}

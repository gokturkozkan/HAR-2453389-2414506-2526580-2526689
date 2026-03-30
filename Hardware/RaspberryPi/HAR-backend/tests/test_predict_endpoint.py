from unittest.mock import patch

import database
from backend_test_helpers import build_window
from routes import activity


def test_predict_endpoint_combines_windows_and_marks_used_nodes_connected(client):
    payload = {
        "windows_by_node": {
            "1": build_window(offset=0.0),
            "2": build_window(offset=1.0),
        }
    }

    with patch("routes.activity.predict_activity", return_value=("walking", 0.88)):
        response = client.post("/predict", json=payload)

    assert response.status_code == 200
    body = response.get_json()
    assert body["node_id"] is None
    assert body["used_node_ids"] == [1, 2]
    assert body["activity"] == "walking"
    assert body["confidence"] == 0.88
    assert body["fusion"] == "average_per_timestep"

    assert database.db_get("SELECT name FROM labels WHERE id = 1")["name"] == "walking"
    assert database.db_get("SELECT is_connected, state FROM esp_devices WHERE id = 1") == {
        "is_connected": 1,
        "state": "streaming",
    }
    assert database.db_get("SELECT is_connected, state FROM esp_devices WHERE id = 2") == {
        "is_connected": 1,
        "state": "streaming",
    }
    assert activity.get_latest_window(1)["node_id"] == 1
    assert activity.get_latest_window(2)["node_id"] == 2
    assert activity.LATEST_WINDOWS_BY_NODE[activity.COMBINED_KEY]["node_ids"] == [1, 2]


def test_predict_endpoint_requires_sensor_payload(client):
    response = client.post("/predict", json={})

    assert response.status_code == 400
    assert response.get_json()["error"] == "No sensor readings provided"


def test_predict_endpoint_rejects_invalid_windows_by_node_payload(client):
    response = client.post(
        "/predict",
        json={"windows_by_node": {"bad-id": build_window()}},
    )

    assert response.status_code == 400
    assert "Invalid node id" in response.get_json()["error"]


def test_predict_endpoint_returns_500_when_prediction_layer_fails(client):
    with patch("routes.activity.predict_activity", side_effect=RuntimeError("model unavailable")):
        response = client.post("/predict", json={"node_id": 3, "readings": build_window()})

    assert response.status_code == 500
    assert response.get_json()["error"] == "model unavailable"


def test_predict_endpoint_tracks_default_window_when_node_id_is_omitted(client):
    with patch("routes.activity.predict_activity", return_value=("standing", 0.91)):
        response = client.post("/predict", json={"readings": build_window(offset=0.5)})

    assert response.status_code == 200
    latest = activity.get_latest_window()
    assert latest["node_id"] is None
    assert latest["predicted_label"] == "standing"

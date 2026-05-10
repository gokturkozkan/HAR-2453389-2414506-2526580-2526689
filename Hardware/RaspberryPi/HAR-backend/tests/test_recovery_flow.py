import json
import os
import tempfile
from unittest.mock import patch

import pytest

import database
import routes.activity as activity
from app import app
from database import db_get


@pytest.fixture()
def client():
    db_file = tempfile.NamedTemporaryFile(delete=False, suffix=".db")
    db_file.close()
    sensor_log = tempfile.NamedTemporaryFile(delete=False, suffix=".jsonl")
    sensor_log.close()
    calibration_file = tempfile.NamedTemporaryFile(delete=False, suffix=".json")
    calibration_file.close()
    os.remove(calibration_file.name)

    old_db_path = database.db_path
    os.environ["SENSOR_LOG_PATH"] = sensor_log.name
    os.environ["HAR_LIVE_CALIBRATION_PATH"] = calibration_file.name

    database.close_database()
    database.db_path = db_file.name
    database.init_database()
    activity.LATEST_WINDOWS_BY_NODE.clear()
    activity.LAST_NODE_ID = None

    with app.test_client() as test_client:
        yield test_client

    activity.LATEST_WINDOWS_BY_NODE.clear()
    activity.LAST_NODE_ID = None
    database.close_database()
    database.db_path = old_db_path
    os.environ.pop("SENSOR_LOG_PATH", None)
    os.environ.pop("HAR_LIVE_CALIBRATION_PATH", None)

    for path in (db_file.name, sensor_log.name, calibration_file.name):
        if os.path.exists(path):
            os.remove(path)


def build_window(size=200):
    return [
        {
            "ax": 0.1 + i * 0.01,
            "ay": 0.2,
            "az": 9.7,
            "gx": 0.01,
            "gy": 0.02,
            "gz": 0.03,
            "mx": 0.04,
            "my": 0.05,
            "mz": 0.06,
        }
        for i in range(size)
    ]


def windows_by_node():
    return {
        "1": build_window(),
        "2": build_window(),
        "3": build_window(),
    }


def test_invalid_prediction_after_success_does_not_corrupt_current_label(client):
    with patch("routes.activity.predict_activity", return_value=("walking", 0.84)):
        success = client.post(
            "/predict",
            json={"windows_by_node": windows_by_node(), "order_sweep": False},
        )

    assert success.status_code == 200
    assert db_get("SELECT name FROM labels WHERE id = 1")["name"] == "walking"

    invalid_payload = windows_by_node()
    invalid_payload["2"][0].pop("ax")
    failure = client.post("/predict", json={"windows_by_node": invalid_payload})

    assert failure.status_code == 400
    assert db_get("SELECT name FROM labels WHERE id = 1")["name"] == "walking"


def test_esp_connection_status_recovers_from_disconnect_to_reconnect(client):
    disconnect = client.post("/esp-status/2", json={"isConnected": False})
    assert disconnect.status_code == 200
    assert client.get("/esp-status?id=2").get_json()["isConnected"] is False

    reconnect = client.post("/esp-status/2", json={"isConnected": True})
    assert reconnect.status_code == 200
    assert client.get("/esp-status?id=2").get_json()["isConnected"] is True


def test_relabel_endpoint_handles_missing_sensor_window_without_crashing(client):
    response = client.post("/label", json={"label": "manual-recovery", "node_id": 7})

    assert response.status_code == 200
    assert response.get_json()["label"] == "manual-recovery"

    relabel = db_get(
        "SELECT node_id, new_label, sensor_data, esp_data "
        "FROM relabels ORDER BY id DESC LIMIT 1"
    )
    assert relabel["node_id"] == 7
    assert relabel["new_label"] == "manual-recovery"
    assert relabel["sensor_data"] is None
    assert relabel["esp_data"] is None


def test_invalid_calibration_sample_preserves_existing_calibration_file(client):
    valid = client.post(
        "/calibration/sample",
        json={"label": "standing", "windows_by_node": windows_by_node()},
    )
    assert valid.status_code == 200
    calibration_path = valid.get_json()["path"]

    invalid_windows = windows_by_node()
    invalid_windows["1"][0].pop("gy")
    invalid = client.post(
        "/calibration/sample",
        json={"label": "sitting", "windows_by_node": invalid_windows},
    )

    assert invalid.status_code == 400

    with open(calibration_path, "r", encoding="utf-8") as calibration_file:
        stored = json.load(calibration_file)

    assert stored["counts"] == {"standing": 1}
    assert stored["samples"][0]["label"] == "standing"

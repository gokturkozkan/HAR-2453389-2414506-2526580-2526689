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


def build_window(base, size=200):
    return [
        {
            "ax": base + i * 0.001,
            "ay": base + 0.2,
            "az": 9.7 - base,
            "gx": 0.01,
            "gy": 0.02,
            "gz": 0.03,
            "mx": 0.04,
            "my": 0.05,
            "mz": 0.06,
        }
        for i in range(size)
    ]


def windows_by_node(base=0.1):
    return {
        "1": build_window(base + 1),
        "2": build_window(base + 2),
        "3": build_window(base + 3),
    }


def register_user(client, username="system-user"):
    response = client.post(
        "/register",
        json={"credentials": {"username": username, "password": "pass123"}},
    )
    assert response.status_code == 201
    return response.get_json()["user"]


def test_complete_backend_system_flow_from_user_to_prediction_to_relabel(client):
    health = client.get("/health")
    assert health.status_code == 200
    assert health.get_json()["status"] == "ok"

    user = register_user(client)
    login = client.post(
        "/login",
        json={"credentials": {"username": "system-user", "password": "pass123"}},
    )
    assert login.status_code == 200
    assert login.get_json()["user"]["id"] == user["id"]

    sensor_payload = {
        "windows_by_node": windows_by_node(),
        "node_order": [1, 2, 3],
        "axis_transform": "+x+y+z",
        "mag_mode": "raw",
        "order_sweep": False,
    }

    with patch("routes.activity.predict_activity", return_value=("walking", 0.88)):
        prediction = client.post("/predict", json=sensor_payload)

    assert prediction.status_code == 200
    assert prediction.get_json()["activity"] == "walking"

    label = client.get("/label")
    assert label.status_code == 200
    assert label.get_json()["label"] == "walking"

    esp_status = client.get("/esp-status")
    assert esp_status.status_code == 200
    connected_nodes = {
        item["id"]
        for item in esp_status.get_json()
        if item["isConnected"]
    }
    assert {1, 2, 3}.issubset(connected_nodes)

    relabel = client.post("/label", json={"label": "standing", "node_id": 1})
    assert relabel.status_code == 200
    assert relabel.get_json()["label"] == "standing"

    stored_relabel = db_get(
        "SELECT original_label, new_label, sensor_data, esp_data "
        "FROM relabels ORDER BY id DESC LIMIT 1"
    )
    assert stored_relabel["original_label"] == "walking"
    assert stored_relabel["new_label"] == "standing"
    assert len(json.loads(stored_relabel["sensor_data"])) == 200
    assert len(json.loads(stored_relabel["esp_data"])) == 3


def test_calibrated_system_flow_from_training_samples_to_current_label(client):
    standing_window = windows_by_node(base=0.2)
    sitting_window = windows_by_node(base=4.0)

    standing_sample = client.post(
        "/calibration/sample",
        json={"label": "standing", "windows_by_node": standing_window},
    )
    assert standing_sample.status_code == 200

    sitting_sample = client.post(
        "/calibration/sample",
        json={"label": "sitting", "windows_by_node": sitting_window},
    )
    assert sitting_sample.status_code == 200

    calibration_status = client.get("/calibration")
    assert calibration_status.status_code == 200
    assert calibration_status.get_json()["counts"] == {
        "standing": 1,
        "sitting": 1,
    }

    with patch("routes.activity.predict_activity", return_value=("lying", 0.99)):
        prediction = client.post(
            "/predict",
            json={"windows_by_node": standing_window, "order_sweep": False},
        )

    assert prediction.status_code == 200
    body = prediction.get_json()
    assert body["classifier"] == "live_calibrated"
    assert body["activity"] == "standing"
    assert body["pamap2_activity"] == "lying"

    label = client.get("/label")
    assert label.status_code == 200
    assert label.get_json()["label"] == "standing"

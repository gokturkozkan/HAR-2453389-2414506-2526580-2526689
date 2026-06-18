import json
import os
import sys
import tempfile
import types
from unittest.mock import patch

import pytest

import database
import routes.activity as activity
from app import app
from database import db_get


ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))

if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

if "serial" not in sys.modules:
    sys.modules["serial"] = types.SimpleNamespace(
        SerialException=Exception,
        Serial=lambda *args, **kwargs: None,
    )

import tdma_hub


@pytest.fixture()
def client():
    db_file = tempfile.NamedTemporaryFile(delete=False, suffix=".db")
    db_file.close()
    sensor_log = tempfile.NamedTemporaryFile(delete=False, suffix=".jsonl")
    sensor_log.close()
    prediction_log = tempfile.NamedTemporaryFile(delete=False, suffix=".jsonl")
    prediction_log.close()
    calibration_file = tempfile.NamedTemporaryFile(delete=False, suffix=".json")
    calibration_file.close()
    os.remove(calibration_file.name)

    old_db_path = database.db_path
    os.environ["SENSOR_LOG_PATH"] = sensor_log.name
    os.environ["PAMAP2_PREDICTION_LOG_PATH"] = prediction_log.name
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
    os.environ.pop("PAMAP2_PREDICTION_LOG_PATH", None)
    os.environ.pop("HAR_LIVE_CALIBRATION_PATH", None)

    for path in (db_file.name, sensor_log.name, prediction_log.name, calibration_file.name):
        if os.path.exists(path):
            os.remove(path)


def node_reading(base, step=0.0):
    return {
        "ax": base + step,
        "ay": base + 0.2,
        "az": 9.7 - base,
        "gx": 0.01 + step,
        "gy": 0.02,
        "gz": 0.03,
        "mx": 0.04,
        "my": 0.05,
        "mz": 0.06,
    }


def windows_by_node(base=0.1):
    return {
        str(node_id): [
            node_reading(base + node_id, step=i * 0.001)
            for i in range(tdma_hub.WINDOW_SIZE)
        ]
        for node_id in (1, 2, 3)
    }


def fused_timestep(index):
    nodes = {}

    for node_id in (1, 2, 3):
        nodes[str(node_id)] = node_reading(node_id * 0.5, step=index * 0.001)

    return {"nodes": nodes}


def tdma_payload():
    window = [
        fused_timestep(index)
        for index in range(tdma_hub.WINDOW_SIZE)
    ]
    _, payload, error = tdma_hub.build_predict_payload(
        window,
        node_order=(3, 2, 1),
        axis_transform="-x-z+y",
        mag_mode="center",
    )

    assert error is None
    payload["order_sweep"] = False
    return payload


def test_tdma_payload_backend_prediction_label_and_esp_status_flow(client):
    payload = tdma_payload()

    with patch("routes.activity.predict_activity", return_value=("walking", 0.87)):
        response = client.post("/predict", json=payload)

    assert response.status_code == 200
    body = response.get_json()
    assert body["activity"] == "walking"
    assert body["node_order"] == [3, 2, 1]
    assert body["axis_transform"] == "-x-z+y"
    assert body["mag_mode"] == "center"

    label_row = db_get("SELECT name FROM labels WHERE id = 1")
    assert label_row["name"] == "walking"

    label_response = client.get("/label")
    assert label_response.status_code == 200
    assert label_response.get_json()["label"] == "walking"

    for node_id in (1, 2, 3):
        esp_response = client.get(f"/esp-status?id={node_id}")
        assert esp_response.status_code == 200
        assert esp_response.get_json()["isConnected"] is True


def test_prediction_to_manual_relabel_persists_sensor_and_all_node_data(client):
    with patch("routes.activity.predict_activity", return_value=("standing", 0.91)):
        prediction = client.post("/predict", json={**tdma_payload(), "order_sweep": False})

    assert prediction.status_code == 200

    relabel = client.post("/label", json={"label": "sitting", "node_id": 3})
    assert relabel.status_code == 200
    assert relabel.get_json()["label"] == "sitting"

    relabel_row = db_get(
        "SELECT node_id, original_label, new_label, sensor_data, esp_data "
        "FROM relabels ORDER BY id DESC LIMIT 1"
    )
    assert relabel_row["node_id"] == 3
    assert relabel_row["original_label"] == "standing"
    assert relabel_row["new_label"] == "sitting"

    sensor_data = json.loads(relabel_row["sensor_data"])
    assert len(sensor_data) == tdma_hub.WINDOW_SIZE
    assert "ax" in sensor_data[0]

    esp_data = json.loads(relabel_row["esp_data"])
    assert [item["node_id"] for item in esp_data] == [1, 2, 3]
    assert all(len(item["readings"]) == tdma_hub.WINDOW_SIZE for item in esp_data)

    labels_row = db_get("SELECT name, esp3 FROM labels WHERE id = 1")
    assert labels_row["name"] == "sitting"
    assert len(json.loads(labels_row["esp3"])) == tdma_hub.WINDOW_SIZE


def test_live_calibration_sample_changes_prediction_output(client):
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

    with patch("routes.activity.predict_activity", return_value=("lying", 0.99)):
        prediction = client.post(
            "/predict",
            json={
                "windows_by_node": standing_window,
                "order_sweep": False,
            },
        )

    assert prediction.status_code == 200
    body = prediction.get_json()
    assert body["classifier"] == "live_calibrated"
    assert body["activity"] == "standing"
    assert body["pamap2_activity"] == "lying"
    assert body["calibrated_result"]["sample_counts"] == {
        "standing": 1,
        "sitting": 1,
    }


def test_mobile_style_auth_update_and_login_flow(client):
    register = client.post(
        "/register",
        json={"credentials": {"username": "mobile-user", "password": "pass123"}},
    )
    assert register.status_code == 201
    user_id = register.get_json()["user"]["id"]

    update = client.post(
        "/user/update",
        json={
            "userId": user_id,
            "credentials": {"username": "mobile-user-updated"},
        },
    )
    assert update.status_code == 200

    old_login = client.post(
        "/login",
        json={"credentials": {"username": "mobile-user", "password": "pass123"}},
    )
    assert old_login.status_code == 401

    new_login = client.post(
        "/login",
        json={"credentials": {"username": "mobile-user-updated", "password": "pass123"}},
    )
    assert new_login.status_code == 200
    assert new_login.get_json()["user"]["id"] == user_id

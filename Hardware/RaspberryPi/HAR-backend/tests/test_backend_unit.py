import json
import os
import tempfile

import pytest

import database
import routes.activity as activity
from app import app
from database import db_get, db_run


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


def build_windows_by_node():
    return {
        "1": build_window(),
        "2": build_window(),
        "3": build_window(),
    }


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


def register(client, username, password="secret123"):
    return client.post(
        "/register",
        json={"credentials": {"username": username, "password": password}},
    )


def test_auth_register_login_duplicate_and_wrong_password(client):
    missing = client.post("/register", json={"credentials": {"username": "alice"}})
    assert missing.status_code == 400

    created = register(client, "alice")
    assert created.status_code == 201
    body = created.get_json()
    assert body["user"]["username"] == "alice"

    row = db_get("SELECT username, password FROM users WHERE username = ?", ["alice"])
    assert row["username"] == "alice"
    assert row["password"] != "secret123"

    duplicate = register(client, "alice")
    assert duplicate.status_code == 409

    wrong_password = client.post(
        "/login",
        json={"credentials": {"username": "alice", "password": "bad"}},
    )
    assert wrong_password.status_code == 401

    login = client.post(
        "/login",
        json={"credentials": {"username": "alice", "password": "secret123"}},
    )
    assert login.status_code == 200
    assert login.get_json()["user"]["username"] == "alice"


def test_user_update_validates_and_prevents_duplicate_usernames(client):
    first = register(client, "first").get_json()["user"]
    register(client, "second")

    missing_username = client.post(
        "/user/update",
        json={"userId": first["id"], "credentials": {"username": " "}},
    )
    assert missing_username.status_code == 400

    duplicate = client.post(
        "/user/update",
        json={"userId": first["id"], "credentials": {"username": "second"}},
    )
    assert duplicate.status_code == 409

    updated = client.post(
        "/user/update",
        json={"userId": first["id"], "credentials": {"username": "first-renamed"}},
    )
    assert updated.status_code == 200
    assert updated.get_json()["user"]["username"] == "first-renamed"

    row = db_get("SELECT username FROM users WHERE id = ?", [first["id"]])
    assert row["username"] == "first-renamed"


def test_esp_status_routes_list_update_and_validate_ids(client):
    initial = client.get("/esp-status")
    assert initial.status_code == 200
    assert len(initial.get_json()) == 7

    invalid = client.get("/esp-status?id=not-a-number")
    assert invalid.status_code == 400

    missing = client.get("/esp-status?id=99")
    assert missing.status_code == 404

    update = client.post("/esp-status/2", json={"isConnected": True})
    assert update.status_code == 200

    node = client.get("/esp-status?id=2")
    assert node.status_code == 200
    assert node.get_json() == {"id": 2, "isConnected": True}


def test_admin_json_routes_are_protected_by_admin_token(client, monkeypatch):
    register(client, "admin-visible")
    monkeypatch.setenv("ADMIN_TOKEN", "test-token")

    unauthorized = client.get("/admin/users.json")
    assert unauthorized.status_code == 401

    authorized = client.get("/admin/users.json", headers={"x-admin-token": "test-token"})
    assert authorized.status_code == 200
    assert authorized.get_json()[0]["username"] == "admin-visible"


def test_calibration_sample_status_and_clear(client):
    status = client.get("/calibration")
    assert status.status_code == 200
    assert status.get_json()["sample_count"] == 0

    sample = client.post(
        "/calibration/sample",
        json={
            "label": "standing",
            "windows_by_node": build_windows_by_node(),
            "resampled_window": {"seconds": 4.0, "model_timesteps": 200},
        },
    )
    assert sample.status_code == 200
    body = sample.get_json()
    assert body["counts"] == {"standing": 1}

    with open(body["path"], "r", encoding="utf-8") as calibration_file:
        stored = json.load(calibration_file)
    assert stored["counts"] == {"standing": 1}
    assert stored["samples"][0]["label"] == "standing"
    assert len(stored["samples"][0]["features"]) > 0

    cleared = client.post("/calibration/clear", json={})
    assert cleared.status_code == 200
    assert cleared.get_json()["counts"] == {}

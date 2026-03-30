import database
from routes import esp


def test_serialize_device_and_normalizers_cover_fallbacks():
    serialized = esp.serialize_device(
        {
            "id": 2,
            "isConnected": 1,
            "state": None,
            "lastSeenMs": None,
            "lastSeq": None,
            "missedPackets": None,
        }
    )

    assert serialized == {
        "id": 2,
        "isConnected": True,
        "state": "streaming",
        "lastSeenMs": None,
        "lastSeq": 0,
        "missedPackets": 0,
    }
    assert esp.normalize_state("stale", True) == "stale"
    assert esp.normalize_state("unknown", True) == "streaming"
    assert esp.normalize_state("unknown", False) == "disconnected"
    assert esp.normalize_optional_int(None, "lastSeenMs") is None
    assert esp.normalize_optional_int("42", "lastSeenMs") == 42


def test_get_esp_status_validates_bad_ids_and_missing_devices(client):
    bad_id = client.get("/esp-status?id=abc")
    missing = client.get("/esp-status?id=3")

    assert bad_id.status_code == 400
    assert bad_id.get_json()["message"] == "Invalid device ID"
    assert missing.status_code == 404
    assert missing.get_json()["message"] == "Device not found"


def test_get_esp_lists_return_rows_in_id_order(client):
    database.db_run(
        "INSERT INTO esp_devices (id, is_connected, state, last_seen_ms, last_seq, missed_packets) VALUES (3, 1, 'streaming', 100, 9, 1)"
    )
    database.db_run(
        "INSERT INTO esp_devices (id, is_connected, state, last_seen_ms, last_seq, missed_packets) VALUES (1, 0, 'disconnected', NULL, 0, 0)"
    )

    status_response = client.get("/esp-status")
    list_response = client.get("/esp")

    assert status_response.status_code == 200
    assert [row["id"] for row in status_response.get_json()] == [1, 3]
    assert list_response.status_code == 200
    assert list_response.get_json() == [{"id": 1}, {"id": 3}]


def test_update_esp_status_preserves_existing_values_on_partial_update(client):
    database.db_run(
        """
        INSERT INTO esp_devices (id, is_connected, state, last_seen_ms, last_seq, missed_packets)
        VALUES (5, 1, 'streaming', 125, 19, 4)
        """
    )

    response = client.post("/esp-status/5", json={"state": "stale"})

    assert response.status_code == 200
    body = response.get_json()["device"]
    assert body["id"] == 5
    assert body["isConnected"] is False
    assert body["state"] == "stale"
    assert body["lastSeenMs"] == 125
    assert body["lastSeq"] == 19
    assert body["missedPackets"] == 4


def test_update_esp_status_invalid_state_falls_back_based_on_connectivity(client):
    streaming = client.post("/esp-status/2", json={"state": "bad-state", "isConnected": True})
    disconnected = client.post("/esp-status/3", json={"state": "bad-state", "isConnected": False})

    assert streaming.status_code == 200
    assert streaming.get_json()["device"]["state"] == "streaming"
    assert streaming.get_json()["device"]["isConnected"] is True

    assert disconnected.status_code == 200
    assert disconnected.get_json()["device"]["state"] == "disconnected"
    assert disconnected.get_json()["device"]["isConnected"] is False


def test_init_esp_devices_creates_missing_rows_only_once(client):
    first = client.post("/esp-devices/init", json={"count": 3})
    second = client.post("/esp-devices/init", json={"count": 3})

    assert first.status_code == 200
    assert second.status_code == 200
    rows = database.db_all("SELECT id, state FROM esp_devices ORDER BY id")
    assert rows == [
        {"id": 1, "state": "disconnected"},
        {"id": 2, "state": "disconnected"},
        {"id": 3, "state": "disconnected"},
    ]

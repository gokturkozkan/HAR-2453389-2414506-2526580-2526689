import pytest

import database
from backend_test_helpers import build_window
from routes import activity


def test_validate_sensor_readings_accepts_numeric_strings():
    readings = build_window()
    readings[0]["ax"] = "1.23"

    activity.validate_sensor_readings(readings)


def test_validate_sensor_readings_rejects_non_list_payload():
    with pytest.raises(ValueError, match="must be a list"):
        activity.validate_sensor_readings({"ax": 1})


def test_validate_sensor_readings_rejects_wrong_window_size():
    with pytest.raises(ValueError, match="Exactly 32 readings"):
        activity.validate_sensor_readings(build_window(size=31))


def test_validate_sensor_readings_rejects_non_object_readings():
    readings = build_window()
    readings[3] = "bad-row"

    with pytest.raises(ValueError, match="index 3 must be an object"):
        activity.validate_sensor_readings(readings)


def test_validate_sensor_readings_rejects_missing_and_non_numeric_fields():
    missing_field = build_window()
    missing_field[0].pop("gz")
    with pytest.raises(ValueError, match="missing 'gz'"):
        activity.validate_sensor_readings(missing_field)

    bad_type = build_window()
    bad_type[2]["gy"] = "not-a-number"
    with pytest.raises(ValueError, match="non-numeric 'gy'"):
        activity.validate_sensor_readings(bad_type)


def test_validate_windows_by_node_normalizes_string_ids():
    normalized = activity.validate_windows_by_node({"1": build_window(), 2: build_window(offset=1.0)})

    assert sorted(normalized) == [1, 2]
    assert normalized[1][0]["ax"] == pytest.approx(0.1)
    assert normalized[2][0]["ax"] == pytest.approx(1.1)


def test_validate_windows_by_node_rejects_empty_payloads_and_bad_ids():
    with pytest.raises(ValueError, match="non-empty object"):
        activity.validate_windows_by_node({})

    with pytest.raises(ValueError, match="Invalid node id"):
        activity.validate_windows_by_node({"abc": build_window()})


def test_combine_windows_by_node_averages_each_feature():
    combined, node_ids = activity.combine_windows_by_node(
        {
            2: build_window(offset=1.0),
            1: build_window(offset=0.0),
        }
    )

    assert node_ids == [1, 2]
    assert len(combined) == 32
    assert combined[0]["ax"] == pytest.approx(0.6)
    assert combined[0]["gy"] == pytest.approx(0.52)


def test_combine_windows_by_node_requires_at_least_one_window():
    with pytest.raises(ValueError, match="At least one node window"):
        activity.combine_windows_by_node({})


def test_latest_window_helpers_store_combined_and_per_node_windows_in_order():
    activity.remember_latest_combined_window([1, 3], build_window(offset=2.0), "walking")
    activity.remember_latest_window(3, build_window(offset=1.0), "walking")
    activity.remember_latest_window(1, build_window(offset=0.0), "walking")

    latest_default = activity.get_latest_window()
    latest_node_3 = activity.get_latest_window(3)
    node_windows = activity.get_all_latest_node_windows()

    assert latest_default["node_id"] == 1
    assert latest_node_3["predicted_label"] == "walking"
    assert node_windows[0]["node_id"] == 1
    assert node_windows[1]["node_id"] == 3
    assert activity.LATEST_WINDOWS_BY_NODE[activity.COMBINED_KEY]["node_ids"] == [1, 3]


def test_upsert_current_label_inserts_and_updates_current_row(backend_db):
    database.db_run("DELETE FROM labels WHERE id = 1")

    activity.upsert_current_label("walking")
    assert database.db_get("SELECT name FROM labels WHERE id = 1")["name"] == "walking"

    activity.upsert_current_label("standing")
    assert database.db_get("SELECT name FROM labels WHERE id = 1")["name"] == "standing"


def test_mark_esp_connected_if_known_inserts_and_updates_rows(backend_db):
    activity.mark_esp_connected_if_known(4)
    first_row = database.db_get(
        "SELECT is_connected, state, last_seen_ms, last_seq, missed_packets FROM esp_devices WHERE id = ?",
        [4],
    )
    assert first_row == {
        "is_connected": 1,
        "state": "streaming",
        "last_seen_ms": None,
        "last_seq": 0,
        "missed_packets": 0,
    }

    database.db_run(
        """
        UPDATE esp_devices
        SET is_connected = 0, state = 'stale', last_seen_ms = 1000, last_seq = 8, missed_packets = 2
        WHERE id = 4
        """
    )

    activity.mark_esp_connected_if_known(4)
    updated_row = database.db_get(
        "SELECT is_connected, state, last_seen_ms, last_seq, missed_packets FROM esp_devices WHERE id = ?",
        [4],
    )
    assert updated_row["is_connected"] == 1
    assert updated_row["state"] == "streaming"
    assert updated_row["last_seen_ms"] == 1000
    assert updated_row["last_seq"] == 8
    assert updated_row["missed_packets"] == 2


def test_mark_esp_connected_if_known_ignores_none(backend_db):
    activity.mark_esp_connected_if_known(None)

    assert database.db_get("SELECT id FROM esp_devices WHERE id = 1") is None

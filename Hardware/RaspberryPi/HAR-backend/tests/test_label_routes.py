import json

import database
from backend_test_helpers import build_window, seed_test_images
from routes import activity
from routes.label import clear_label


def test_get_label_returns_current_label_without_image_when_image_is_missing(client):
    database.db_run("UPDATE labels SET name = ? WHERE id = 1", ["jumping"])
    activity.remember_latest_window(3, build_window(), "jumping")

    response = client.get("/label")

    assert response.status_code == 200
    assert response.get_json() == {
        "label": "jumping",
        "image": None,
        "hasImage": False,
        "node_id": 3,
    }


def test_get_label_returns_pre_encoded_image_strings_as_is(client):
    database.db_run("UPDATE labels SET name = ? WHERE id = 1", ["jumping"])
    database.db_run(
        "INSERT OR REPLACE INTO unity_images (name, data) VALUES (?, ?)",
        ["jumping.png", "already-encoded"],
    )

    response = client.get("/label")

    assert response.status_code == 200
    body = response.get_json()
    assert body["label"] == "jumping"
    assert body["image"] == "already-encoded"
    assert body["hasImage"] is True


def test_update_label_rejects_missing_and_blank_labels(client):
    for payload in ({}, {"label": ""}, {"name": "   "}):
        response = client.post("/label", json=payload)
        assert response.status_code == 400
        assert response.get_json()["message"] == "Label is required and must be a string"


def test_update_label_uses_latest_window_when_node_id_is_invalid(client):
    seed_test_images("walking.png")
    activity.remember_latest_window(4, build_window(offset=0.4), "standing")

    response = client.post("/label", json={"label": "walking", "node_id": "oops"})

    assert response.status_code == 200
    body = response.get_json()
    assert body["label"] == "walking"
    assert body["node_id"] == 4
    assert body["hasImage"] is True

    relabel_row = database.db_get(
        "SELECT node_id, sensor_data FROM relabels ORDER BY id DESC LIMIT 1"
    )
    assert relabel_row["node_id"] == 4
    assert len(json.loads(relabel_row["sensor_data"])) == 32

    labels_row = database.db_get("SELECT name, esp4 FROM labels WHERE id = 1")
    assert labels_row["name"] == "walking"
    assert len(json.loads(labels_row["esp4"])) == 32


def test_update_label_out_of_range_node_id_keeps_relabel_but_skips_esp_columns(client):
    activity.remember_latest_window(8, build_window(offset=0.8), "standing")

    response = client.post("/label", json={"label": "jumping", "node_id": 8})

    assert response.status_code == 200
    assert response.get_json()["node_id"] == 8

    relabel_row = database.db_get(
        "SELECT node_id, sensor_data FROM relabels ORDER BY id DESC LIMIT 1"
    )
    assert relabel_row["node_id"] == 8
    assert len(json.loads(relabel_row["sensor_data"])) == 32

    labels_row = database.db_get(
        "SELECT esp1, esp2, esp3, esp4, esp5, esp6, esp7 FROM labels WHERE id = 1"
    )
    assert all(value is None for value in labels_row.values())


def test_clear_label_causes_get_label_to_return_404(client):
    clear_label()

    response = client.get("/label")

    assert response.status_code == 404
    assert response.get_json()["message"] == "No activity label available yet"

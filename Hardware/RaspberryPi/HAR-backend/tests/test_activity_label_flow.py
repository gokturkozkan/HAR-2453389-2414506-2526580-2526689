import os
import json
import tempfile
import unittest
from unittest.mock import patch

import database
from app import app
from database import db_get, db_run


def build_window(size=32):
    return [
        {
            "ax": 0.1 + i * 0.01,
            "ay": 0.2 + i * 0.01,
            "az": 9.7,
            "gx": 0.01,
            "gy": 0.02,
            "gz": 0.03,
        }
        for i in range(size)
    ]


class ActivityLabelFlowTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".db")
        self.tmp.close()

        database.close_database()
        database.db_path = self.tmp.name
        database.init_database()
        self._seed_test_images()

        self.client = app.test_client()

    def _seed_test_images(self):
        # Keep tests deterministic even when mock-Unity files are absent on disk.
        db_run(
            'CREATE TABLE IF NOT EXISTS unity_images (name TEXT PRIMARY KEY, data BLOB NOT NULL)'
        )
        fake_png = b'\x89PNG\r\n\x1a\nTEST'
        for name in ('standing.png', 'jumping.png', 'sitting.png'):
            db_run(
                'INSERT OR REPLACE INTO unity_images (name, data) VALUES (?, ?)',
                [name, fake_png],
            )

    def tearDown(self):
        database.close_database()
        if os.path.exists(self.tmp.name):
            os.remove(self.tmp.name)

    def test_predict_updates_current_label_and_frontend_get_label(self):
        payload = {"node_id": 2, "readings": build_window()}

        with patch("routes.activity.predict_activity", return_value=("standing", 0.91)):
            res = self.client.post("/predict", json=payload)

        self.assertEqual(res.status_code, 200)
        body = res.get_json()
        self.assertEqual(body["node_id"], 2)
        self.assertEqual(body["activity"], "standing")

        current_label = db_get("SELECT name FROM labels WHERE id = 1")
        self.assertEqual(current_label["name"], "standing")

        label_res = self.client.get("/label")
        self.assertEqual(label_res.status_code, 200)
        label_body = label_res.get_json()
        self.assertEqual(label_body["label"], "standing")
        self.assertTrue(isinstance(label_body["image"], str) and len(label_body["image"]) > 0)

    def test_get_label_returns_404_when_current_label_is_empty(self):
        db_run("UPDATE labels SET name = ? WHERE id = 1", [""])

        res = self.client.get("/label")

        self.assertEqual(res.status_code, 404)
        body = res.get_json()
        self.assertEqual(body["message"], "No activity label available yet")

    def test_predict_rejects_invalid_sensor_payload(self):
        bad_window = build_window()
        bad_window[0].pop("gz")

        res = self.client.post("/predict", json={"node_id": 1, "readings": bad_window})

        self.assertEqual(res.status_code, 400)
        body = res.get_json()
        self.assertIn("missing 'gz'", body["error"])

    def test_manual_label_post_is_returned_by_get_label(self):
        payload = {"node_id": 7, "readings": build_window()}
        with patch("routes.activity.predict_activity", return_value=("standing", 0.91)):
            predict_res = self.client.post("/predict", json=payload)
        self.assertEqual(predict_res.status_code, 200)

        post_res = self.client.post("/label", json={"label": "jumping", "node_id": 7})

        self.assertEqual(post_res.status_code, 200)
        post_body = post_res.get_json()
        self.assertEqual(post_body["label"], "jumping")

        relabel_row = db_get(
            "SELECT node_id, original_label, new_label, sensor_data, esp_data FROM relabels ORDER BY id DESC LIMIT 1"
        )
        self.assertEqual(relabel_row["node_id"], 7)
        self.assertEqual(relabel_row["original_label"], "standing")
        self.assertEqual(relabel_row["new_label"], "jumping")
        parsed_sensor_data = json.loads(relabel_row["sensor_data"])
        self.assertEqual(len(parsed_sensor_data), 32)
        self.assertIn("ax", parsed_sensor_data[0])
        parsed_esp_data = json.loads(relabel_row["esp_data"])
        self.assertTrue(isinstance(parsed_esp_data, list) and len(parsed_esp_data) > 0)
        self.assertEqual(parsed_esp_data[0]["node_id"], 7)
        self.assertEqual(len(parsed_esp_data[0]["readings"]), 32)

        labels_row = db_get(
            "SELECT name, esp1, esp2, esp3, esp4, esp5, esp6, esp7 FROM labels WHERE id = 1"
        )
        self.assertEqual(labels_row["name"], "jumping")
        self.assertIsNone(labels_row["esp1"])
        self.assertIsNone(labels_row["esp2"])
        self.assertIsNone(labels_row["esp3"])
        self.assertIsNone(labels_row["esp4"])
        self.assertIsNone(labels_row["esp5"])
        self.assertIsNone(labels_row["esp6"])
        self.assertTrue(isinstance(labels_row["esp7"], str) and len(labels_row["esp7"]) > 0)

        esp7_readings = json.loads(labels_row["esp7"])
        self.assertEqual(len(esp7_readings), 32)
        self.assertIn("ax", esp7_readings[0])

        get_res = self.client.get("/label")
        self.assertEqual(get_res.status_code, 200)
        get_body = get_res.get_json()
        self.assertEqual(get_body["label"], "jumping")

    def test_manual_label_allows_missing_sensor_windows(self):
        res = self.client.post("/label", json={"label": "jumping", "node_id": 99})
        self.assertEqual(res.status_code, 200)

        labels_row = db_get(
            "SELECT name, esp1, esp2, esp3, esp4, esp5, esp6, esp7 FROM labels WHERE id = 1"
        )
        self.assertEqual(labels_row["name"], "jumping")
        self.assertIsNone(labels_row["esp1"])
        self.assertIsNone(labels_row["esp2"])
        self.assertIsNone(labels_row["esp3"])
        self.assertIsNone(labels_row["esp4"])
        self.assertIsNone(labels_row["esp5"])
        self.assertIsNone(labels_row["esp6"])
        self.assertIsNone(labels_row["esp7"])


if __name__ == "__main__":
    unittest.main()

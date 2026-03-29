import os
import tempfile
import unittest

import database
from app import app
from database import db_get


class EspStatusFlowTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".db")
        self.tmp.close()

        database.close_database()
        database.db_path = self.tmp.name
        database.init_database()
        self.client = app.test_client()

    def tearDown(self):
        database.close_database()
        if os.path.exists(self.tmp.name):
            os.remove(self.tmp.name)

    def test_extended_status_fields_round_trip(self):
        payload = {
            "isConnected": True,
            "state": "streaming",
            "lastSeenMs": 120,
            "lastSeq": 44,
            "missedPackets": 3,
        }

        post_res = self.client.post("/esp-status/2", json=payload)
        self.assertEqual(post_res.status_code, 200)

        get_res = self.client.get("/esp-status?id=2")
        self.assertEqual(get_res.status_code, 200)
        body = get_res.get_json()
        self.assertEqual(body["id"], 2)
        self.assertTrue(body["isConnected"])
        self.assertEqual(body["state"], "streaming")
        self.assertEqual(body["lastSeenMs"], 120)
        self.assertEqual(body["lastSeq"], 44)
        self.assertEqual(body["missedPackets"], 3)

        row = db_get(
            "SELECT is_connected, state, last_seen_ms, last_seq, missed_packets FROM esp_devices WHERE id = ?",
            [2],
        )
        self.assertEqual(row["is_connected"], 1)
        self.assertEqual(row["state"], "streaming")
        self.assertEqual(row["last_seen_ms"], 120)
        self.assertEqual(row["last_seq"], 44)
        self.assertEqual(row["missed_packets"], 3)

    def test_status_update_accepts_state_without_is_connected(self):
        post_res = self.client.post(
            "/esp-status/5",
            json={"state": "stale", "lastSeenMs": 2400, "lastSeq": 91, "missedPackets": 7},
        )
        self.assertEqual(post_res.status_code, 200)

        get_res = self.client.get("/esp-status?id=5")
        self.assertEqual(get_res.status_code, 200)
        body = get_res.get_json()
        self.assertFalse(body["isConnected"])
        self.assertEqual(body["state"], "stale")
        self.assertEqual(body["lastSeenMs"], 2400)

    def test_invalid_numeric_fields_are_rejected(self):
        post_res = self.client.post(
            "/esp-status/3",
            json={"state": "streaming", "lastSeenMs": "not-a-number"},
        )
        self.assertEqual(post_res.status_code, 400)
        body = post_res.get_json()
        self.assertIn("Invalid lastSeenMs", body["message"])


if __name__ == "__main__":
    unittest.main()

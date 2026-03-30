import os
import tempfile
import unittest

import database
from app import app


class EspStatusRouteTests(unittest.TestCase):
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

    def test_post_and_get_rich_esp_status(self):
        payload = {
            "transport": "ble",
            "state": "streaming",
            "lastSeenMs": 125,
            "lastSeq": 99,
            "missedPackets": 3,
            "bootId": 456,
            "firmwareVersion": 7,
            "lastError": None,
        }

        post_res = self.client.post("/esp-status/4", json=payload)
        self.assertEqual(post_res.status_code, 200)
        post_body = post_res.get_json()
        self.assertTrue(post_body["isConnected"])
        self.assertEqual(post_body["transport"], "ble")
        self.assertEqual(post_body["state"], "streaming")
        self.assertEqual(post_body["lastSeq"], 99)
        self.assertEqual(post_body["missedPackets"], 3)
        self.assertEqual(post_body["bootId"], 456)
        self.assertEqual(post_body["firmwareVersion"], 7)
        self.assertTrue(isinstance(post_body["lastSeenAt"], str) and len(post_body["lastSeenAt"]) > 0)

        get_res = self.client.get("/esp-status?id=4")
        self.assertEqual(get_res.status_code, 200)
        get_body = get_res.get_json()
        self.assertTrue(get_body["isConnected"])
        self.assertEqual(get_body["transport"], "ble")
        self.assertEqual(get_body["state"], "streaming")
        self.assertEqual(get_body["lastSeenMs"], 125)
        self.assertEqual(get_body["lastSeq"], 99)
        self.assertEqual(get_body["missedPackets"], 3)
        self.assertEqual(get_body["bootId"], 456)
        self.assertEqual(get_body["firmwareVersion"], 7)

    def test_partial_update_preserves_existing_fields_and_state_drives_is_connected(self):
        first_res = self.client.post(
            "/esp-status/2",
            json={
                "transport": "ble",
                "state": "streaming",
                "lastSeq": 10,
                "missedPackets": 0,
                "bootId": 222,
                "firmwareVersion": 3,
            },
        )
        self.assertEqual(first_res.status_code, 200)

        second_res = self.client.post(
            "/esp-status/2",
            json={
                "state": "stale",
                "lastSeenMs": 2500,
                "lastError": "timeout waiting for data",
            },
        )
        self.assertEqual(second_res.status_code, 200)
        second_body = second_res.get_json()
        self.assertFalse(second_body["isConnected"])
        self.assertEqual(second_body["state"], "stale")
        self.assertEqual(second_body["transport"], "ble")
        self.assertEqual(second_body["lastSeq"], 10)
        self.assertEqual(second_body["bootId"], 222)
        self.assertEqual(second_body["firmwareVersion"], 3)
        self.assertEqual(second_body["lastError"], "timeout waiting for data")

        list_res = self.client.get("/esp-status")
        self.assertEqual(list_res.status_code, 200)
        devices = list_res.get_json()
        self.assertEqual(len(devices), 1)
        self.assertEqual(devices[0]["id"], 2)
        self.assertFalse(devices[0]["isConnected"])
        self.assertEqual(devices[0]["state"], "stale")

    def test_rejects_invalid_state(self):
        res = self.client.post("/esp-status/1", json={"state": "broken"})
        self.assertEqual(res.status_code, 400)
        body = res.get_json()
        self.assertIn("state must be one of", body["message"])


if __name__ == "__main__":
    unittest.main()

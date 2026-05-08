import json
import tempfile
import unittest
from pathlib import Path

import bridge_server


class BridgeServerTests(unittest.TestCase):
    def test_compute_secret_hash_is_deterministic_and_code_specific(self):
        first = bridge_server.compute_secret_hash("123456")
        second = bridge_server.compute_secret_hash("123456")
        other = bridge_server.compute_secret_hash("654321")

        self.assertEqual(first, second)
        self.assertNotEqual(first, other)
        self.assertEqual(len(first), 64)

    def test_log_message_overwrites_with_latest_json_object(self):
        with tempfile.TemporaryDirectory() as tmp:
            original_log = bridge_server.LOG_FILE
            bridge_server.LOG_FILE = Path(tmp) / "unity_commands.log"
            try:
                bridge_server.log_message({"label": "standing"})
                bridge_server.log_message({"label": "walking", "node_id": 2})

                data = json.loads(bridge_server.LOG_FILE.read_text(encoding="utf-8"))
                self.assertEqual(data["label"], "walking")
                self.assertEqual(data["node_id"], 2)
                self.assertIn("timestamp", data)
                self.assertNotIn("standing", bridge_server.LOG_FILE.read_text(encoding="utf-8"))
            finally:
                bridge_server.LOG_FILE = original_log


if __name__ == "__main__":
    unittest.main()

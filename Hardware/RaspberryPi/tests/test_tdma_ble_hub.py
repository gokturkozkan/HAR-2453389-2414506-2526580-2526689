import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

CURRENT_DIR = os.path.dirname(__file__)
RASPBERRY_PI_DIR = os.path.dirname(CURRENT_DIR)
if RASPBERRY_PI_DIR not in sys.path:
    sys.path.insert(0, RASPBERRY_PI_DIR)

from tdma_ble_hub import (  # noqa: E402
    AsyncBackendStatusReporter,
    choose_nodes,
    load_registry,
    mark_all_disconnected,
)


class TDMABleHubHelpersTests(unittest.TestCase):
    def test_load_registry_parses_node_rows(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            registry_path = Path(tmp_dir) / "ble_node_registry.json"
            registry_path.write_text(
                json.dumps(
                    {
                        "nodes": [
                            {"id": 1, "name": "Left Wrist", "mac": "AA:BB:CC:DD:EE:01"},
                            {"id": 2, "name": "Right Wrist", "mac": "AA:BB:CC:DD:EE:02"},
                        ]
                    }
                ),
                encoding="utf-8",
            )

            registry = load_registry(registry_path)

        self.assertEqual(sorted(registry.keys()), [1, 2])
        self.assertEqual(registry[1]["name"], "Left Wrist")
        self.assertEqual(registry[2]["mac"], "AA:BB:CC:DD:EE:02")

    def test_choose_nodes_uses_environment_filter_when_valid(self):
        registry = {
            1: {"id": 1, "name": "One", "mac": "AA"},
            2: {"id": 2, "name": "Two", "mac": "BB"},
            3: {"id": 3, "name": "Three", "mac": "CC"},
        }

        with patch.dict(os.environ, {"HAR_ACTIVE_NODES": "3,2,99,abc"}, clear=False):
            chosen = choose_nodes(registry)

        self.assertEqual(chosen, [2, 3])

    def test_choose_nodes_falls_back_to_all_when_env_has_no_valid_ids(self):
        registry = {
            1: {"id": 1, "name": "One", "mac": "AA"},
            2: {"id": 2, "name": "Two", "mac": "BB"},
        }

        with patch.dict(os.environ, {"HAR_ACTIVE_NODES": "99,abc"}, clear=False):
            chosen = choose_nodes(registry)

        self.assertEqual(chosen, [1, 2])

    def test_mark_all_disconnected_emits_expected_payloads(self):
        payloads = []

        mark_all_disconnected(payloads.append, [1, 4])

        self.assertEqual(len(payloads), 2)
        self.assertEqual(payloads[0]["id"], 1)
        self.assertEqual(payloads[0]["transport"], "ble")
        self.assertFalse(payloads[0]["isConnected"])
        self.assertEqual(payloads[0]["state"], "disconnected")
        self.assertEqual(payloads[1]["id"], 4)
        self.assertEqual(payloads[1]["lastError"], "hub shutdown")

    def test_backend_status_reporter_deduplicates_identical_payloads(self):
        reporter = AsyncBackendStatusReporter()
        payload = {
            "id": 1,
            "transport": "ble",
            "isConnected": True,
            "state": "streaming",
            "lastSeenMs": 50,
            "lastSeq": 12,
            "missedPackets": 0,
            "bootId": 100,
            "firmwareVersion": 1,
            "lastError": None,
        }

        reporter(payload)
        reporter(dict(payload))
        reporter({**payload, "lastSeq": 13})

        self.assertEqual(reporter._queue.qsize(), 2)


if __name__ == "__main__":
    unittest.main()

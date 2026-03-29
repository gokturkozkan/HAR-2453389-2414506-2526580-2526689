import os
import sys
import time
import unittest

CURRENT_DIR = os.path.dirname(__file__)
RASPBERRY_PI_DIR = os.path.dirname(CURRENT_DIR)
if RASPBERRY_PI_DIR not in sys.path:
    sys.path.insert(0, RASPBERRY_PI_DIR)

from tdma_wifi_transport import (  # noqa: E402
    HELLO_FLAG_SYNC_LOCKED,
    SAMPLE_PERIOD_US,
    STALE_AFTER_SECONDS,
    DISCONNECTED_AFTER_SECONDS,
    SoftTDMAHub,
    decode_packet,
    pack_data,
    pack_hello,
    pack_sync,
)


def make_samples(count, offset=0.0):
    rows = []
    for index in range(count):
        base = offset + index * 0.1
        rows.append(
            {
                "ax": base,
                "ay": base + 0.1,
                "az": 9.8 + base,
                "gx": base + 0.2,
                "gy": base + 0.3,
                "gz": base + 0.4,
            }
        )
    return rows


class TDMAWiFiTransportTests(unittest.TestCase):
    def test_packet_round_trip(self):
        hello = decode_packet(pack_hello(3, boot_id=1234, firmware_version=7, flags=HELLO_FLAG_SYNC_LOCKED))
        self.assertEqual(hello["type"], "hello")
        self.assertEqual(hello["node_id"], 3)
        self.assertTrue(hello["sync_locked"])

        sync = decode_packet(pack_sync(12, 456789, {1: 11, 3: 22}))
        self.assertEqual(sync["type"], "sync")
        self.assertEqual(sync["superframe_id"], 12)
        self.assertEqual(sync["hub_time_us"], 456789)
        self.assertEqual(sync["next_seq_expected"][1], 11)
        self.assertEqual(sync["next_seq_expected"][3], 22)

        data = decode_packet(pack_data(2, 40, 987654321, make_samples(3)))
        self.assertEqual(data["type"], "data")
        self.assertEqual(data["node_id"], 2)
        self.assertEqual(data["first_seq"], 40)
        self.assertEqual(data["sample_count"], 3)
        self.assertEqual(len(data["samples"]), 3)

    def test_hub_handles_overlapping_retransmit_without_duplicates(self):
        hub = SoftTDMAHub([1])
        hub.handle_packet(pack_hello(1, boot_id=1, flags=HELLO_FLAG_SYNC_LOCKED))
        first_batch = make_samples(3)
        second_batch = make_samples(3, offset=0.1)

        hub.handle_packet(pack_data(1, 0, 1_000_000, first_batch))
        hub.handle_packet(pack_data(1, 1, 1_000_000 + SAMPLE_PERIOD_US, second_batch))

        state = hub.node_states[1]
        self.assertEqual(state.state, "streaming")
        self.assertEqual(state.next_seq_expected, 4)
        seqs = [sample.seq for sample in state.sample_buffer]
        self.assertEqual(seqs, [0, 1, 2, 3])

    def test_build_prediction_windows_resamples_all_nodes(self):
        hub = SoftTDMAHub([1, 2])
        hub.handle_packet(pack_hello(1, boot_id=1, flags=HELLO_FLAG_SYNC_LOCKED))
        hub.handle_packet(pack_hello(2, boot_id=2, flags=HELLO_FLAG_SYNC_LOCKED))

        samples_node_1 = make_samples(76, offset=0.0)
        samples_node_2 = make_samples(76, offset=1.0)

        for start in range(0, len(samples_node_1), 16):
            batch_1 = samples_node_1[start:start + 16]
            batch_2 = samples_node_2[start:start + 16]
            hub.handle_packet(pack_data(1, start, start * SAMPLE_PERIOD_US, batch_1))
            hub.handle_packet(pack_data(2, start, start * SAMPLE_PERIOD_US, batch_2))

        windows = hub.build_prediction_windows()
        self.assertIsNotNone(windows)
        self.assertEqual(len(windows[1]), 32)
        self.assertEqual(len(windows[2]), 32)
        self.assertAlmostEqual(windows[1][0]["ax"], 0.0, delta=0.15)
        self.assertAlmostEqual(windows[1][-1]["ax"], 7.5, delta=0.2)
        self.assertAlmostEqual(windows[2][0]["ax"], 1.0, delta=0.15)

    def test_refresh_states_marks_stale_then_disconnected(self):
        hub = SoftTDMAHub([1])
        hub.handle_packet(pack_hello(1, boot_id=1, flags=HELLO_FLAG_SYNC_LOCKED))
        hub.handle_packet(pack_data(1, 0, 1_000_000, make_samples(4)))

        now = time.monotonic()
        hub.node_states[1].last_seen_monotonic = now - STALE_AFTER_SECONDS - 0.1
        hub.refresh_states(now)
        self.assertEqual(hub.node_states[1].state, "stale")

        hub.node_states[1].last_seen_monotonic = now - DISCONNECTED_AFTER_SECONDS - 0.1
        hub.refresh_states(now)
        self.assertEqual(hub.node_states[1].state, "disconnected")


if __name__ == "__main__":
    unittest.main()

import os
import sys
import time
import unittest

CURRENT_DIR = os.path.dirname(__file__)
RASPBERRY_PI_DIR = os.path.dirname(CURRENT_DIR)
if RASPBERRY_PI_DIR not in sys.path:
    sys.path.insert(0, RASPBERRY_PI_DIR)

from tdma_ble_transport import (  # noqa: E402
    HELLO_FLAG_SYNC_LOCKED,
    PREFERRED_ATT_PAYLOAD_BYTES,
    SAMPLE_PERIOD_US,
    SUPERFRAME_MS,
    STALE_AFTER_SECONDS,
    DISCONNECTED_AFTER_SECONDS,
    ProtocolError,
    SoftTDMAHub,
    att_payload_bytes_for_mtu,
    decode_packet,
    max_samples_per_packet,
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


class TDMABleTransportTests(unittest.TestCase):
    def test_decode_packet_rejects_invalid_headers(self):
        with self.assertRaises(ProtocolError):
            decode_packet(b"tiny")

        bad_magic = bytearray(pack_hello(1, boot_id=1))
        bad_magic[0:4] = b"NOPE"
        with self.assertRaises(ProtocolError):
            decode_packet(bytes(bad_magic))

        bad_version = bytearray(pack_hello(1, boot_id=1))
        bad_version[4] = 99
        with self.assertRaises(ProtocolError):
            decode_packet(bytes(bad_version))

        bad_size = bytearray(pack_hello(1, boot_id=1))
        bad_size[6:8] = (999).to_bytes(2, "little")
        with self.assertRaises(ProtocolError):
            decode_packet(bytes(bad_size))

    def test_packet_round_trip(self):
        hello = decode_packet(
            pack_hello(3, boot_id=1234, firmware_version=7, flags=HELLO_FLAG_SYNC_LOCKED)
        )
        self.assertEqual(hello["type"], "hello")
        self.assertEqual(hello["node_id"], 3)
        self.assertTrue(hello["sync_locked"])

        sync = decode_packet(
            pack_sync(
                superframe_id=12,
                hub_time_us=456789,
                next_seq_expected=22,
                slot_index=2,
                active_node_count=7,
            )
        )
        self.assertEqual(sync["type"], "sync")
        self.assertEqual(sync["superframe_id"], 12)
        self.assertEqual(sync["hub_time_us"], 456789)
        self.assertEqual(sync["next_seq_expected"], 22)
        self.assertEqual(sync["slot_index"], 2)
        self.assertEqual(sync["active_node_count"], 7)

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
        self.assertEqual(state.dropped_packets, 0)

    def test_sequence_gap_increments_missed_packets(self):
        hub = SoftTDMAHub([1])
        hub.handle_packet(pack_hello(1, boot_id=1, flags=HELLO_FLAG_SYNC_LOCKED))
        hub.handle_packet(pack_data(1, 0, 1_000_000, make_samples(2)))
        hub.handle_packet(pack_data(1, 5, 1_000_000 + (5 * SAMPLE_PERIOD_US), make_samples(2, 1.0)))

        state = hub.node_states[1]
        self.assertEqual(state.missed_packets, 3)
        self.assertEqual(state.next_seq_expected, 7)
        self.assertEqual([sample.seq for sample in state.sample_buffer], [0, 1, 5, 6])

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

    def test_build_prediction_windows_returns_none_without_full_window_coverage(self):
        hub = SoftTDMAHub([1, 2])
        hub.handle_packet(pack_hello(1, boot_id=1, flags=HELLO_FLAG_SYNC_LOCKED))
        hub.handle_packet(pack_hello(2, boot_id=2, flags=HELLO_FLAG_SYNC_LOCKED))
        hub.handle_packet(pack_data(1, 0, 0, make_samples(10)))
        hub.handle_packet(pack_data(2, 0, 0, make_samples(1, offset=1.0)))

        self.assertIsNone(hub.build_prediction_windows())

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

    def test_new_data_recovers_node_from_stale_to_streaming(self):
        hub = SoftTDMAHub([1])
        hub.handle_packet(pack_hello(1, boot_id=1, flags=HELLO_FLAG_SYNC_LOCKED))
        hub.handle_packet(pack_data(1, 0, 1_000_000, make_samples(4)))

        now = time.monotonic()
        hub.node_states[1].last_seen_monotonic = now - STALE_AFTER_SECONDS - 0.1
        hub.refresh_states(now)
        self.assertEqual(hub.node_states[1].state, "stale")

        hub.handle_packet(
            pack_data(1, 4, 1_000_000 + (4 * SAMPLE_PERIOD_US), make_samples(2, offset=1.0)),
            received_monotonic=now,
        )
        self.assertEqual(hub.node_states[1].state, "streaming")

    def test_new_boot_id_discards_old_sequence_state(self):
        hub = SoftTDMAHub([1])
        hub.handle_packet(pack_hello(1, boot_id=1, flags=HELLO_FLAG_SYNC_LOCKED))
        hub.handle_packet(pack_data(1, 0, 1_000_000, make_samples(4)))

        self.assertEqual(hub.node_states[1].next_seq_expected, 4)
        self.assertEqual(len(hub.node_states[1].sample_buffer), 4)

        hub.handle_packet(pack_hello(1, boot_id=2, flags=HELLO_FLAG_SYNC_LOCKED))

        self.assertEqual(hub.node_states[1].boot_id, 2)
        self.assertEqual(hub.node_states[1].next_seq_expected, 0)
        self.assertEqual(len(hub.node_states[1].sample_buffer), 0)

    def test_build_sync_packet_includes_slot_and_next_expected_seq(self):
        hub = SoftTDMAHub([2, 4, 6])
        hub.node_states[4].next_seq_expected = 11

        decoded = decode_packet(hub.build_sync_packet(4, now_us=560_000))

        self.assertEqual(decoded["type"], "sync")
        self.assertEqual(decoded["slot_index"], 1)
        self.assertEqual(decoded["active_node_count"], 3)
        self.assertEqual(decoded["next_seq_expected"], 11)
        self.assertEqual(decoded["superframe_id"], 560_000 // (SUPERFRAME_MS * 1000))

    def test_mark_transport_error_can_force_disconnected_state(self):
        hub = SoftTDMAHub([1])
        hub.mark_joining(1)
        hub.mark_transport_error(1, "radio timeout", disconnected=True)

        state = hub.node_states[1]
        self.assertEqual(state.state, "disconnected")
        self.assertEqual(state.last_error, "radio timeout")

    def test_att_payload_bytes_for_small_mtu_keeps_ble_floor(self):
        self.assertEqual(att_payload_bytes_for_mtu(10), 20)
        self.assertEqual(att_payload_bytes_for_mtu(185), 182)

    def test_max_samples_per_packet_matches_plan_formula(self):
        self.assertEqual(max_samples_per_packet(PREFERRED_ATT_PAYLOAD_BYTES), 13)


if __name__ == "__main__":
    unittest.main()

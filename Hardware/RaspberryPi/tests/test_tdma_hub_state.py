import pytest

from tdma_test_helpers import make_samples
from tdma_wifi_transport import (
    DISCONNECTED_AFTER_SECONDS,
    HELLO_FLAG_SYNC_LOCKED,
    SAMPLE_PERIOD_US,
    STALE_AFTER_SECONDS,
    STATUS_STREAMING_REPORT_SECONDS,
    ProtocolError,
    SoftTDMAHub,
    decode_packet,
    pack_data,
    pack_hello,
)


def test_build_sync_packet_uses_current_expected_sequences():
    hub = SoftTDMAHub([2, 1, 99])
    hub.node_states[1].next_seq_expected = 5
    hub.node_states[2].next_seq_expected = 9

    sync = decode_packet(hub.build_sync_packet(now_us=600_000))

    assert hub.active_nodes == [1, 2]
    assert sync["type"] == "sync"
    assert sync["superframe_id"] == hub.superframe_id
    assert sync["hub_time_us"] == 600_000
    assert sync["next_seq_expected"][1] == 5
    assert sync["next_seq_expected"][2] == 9


def test_hello_transitions_joining_then_synced_for_active_nodes_only():
    hub = SoftTDMAHub([1])

    hub.handle_packet(pack_hello(1, boot_id=10), addr=("10.0.0.8", 5000), received_monotonic=1.0)
    state = hub.node_states[1]
    assert state.state == "joining"
    assert state.address == ("10.0.0.8", 5000)
    assert state.boot_id == 10

    hub.handle_packet(
        pack_hello(1, boot_id=10, flags=HELLO_FLAG_SYNC_LOCKED),
        received_monotonic=2.0,
    )
    assert state.state == "synced"
    assert state.last_hello_monotonic == 2.0

    hub.handle_packet(pack_hello(7, boot_id=77, flags=HELLO_FLAG_SYNC_LOCKED), received_monotonic=3.0)
    assert list(hub.node_states) == [1]
    assert hub.node_states[1].state == "synced"


def test_hub_rejects_sync_packets_as_ingress():
    hub = SoftTDMAHub([1])

    with pytest.raises(ProtocolError, match="Hub should not ingest packet type sync"):
        hub.handle_packet(hub.build_sync_packet(now_us=123_000))


def test_gap_in_data_increments_missed_packets_and_tracks_latest_sample():
    hub = SoftTDMAHub([1])
    hub.handle_packet(pack_hello(1, boot_id=1, flags=HELLO_FLAG_SYNC_LOCKED), received_monotonic=0.5)

    hub.handle_packet(
        pack_data(1, 3, 300_000, make_samples(2, offset=1.0)),
        addr=("10.0.0.9", 6000),
        received_monotonic=1.5,
    )

    state = hub.node_states[1]
    assert state.state == "streaming"
    assert state.address == ("10.0.0.9", 6000)
    assert state.missed_packets == 3
    assert state.next_seq_expected == 5
    assert state.last_sample_time_us == 300_000 + SAMPLE_PERIOD_US
    assert hub.latest_rows[1].seq == 4
    assert hub.latest_rows[1].ax == pytest.approx(1.1, abs=0.02)


def test_duplicate_data_packet_counts_as_drop_without_appending_samples():
    hub = SoftTDMAHub([1])
    hub.handle_packet(pack_hello(1, boot_id=1, flags=HELLO_FLAG_SYNC_LOCKED))
    first_batch = make_samples(3)
    hub.handle_packet(pack_data(1, 0, 100_000, first_batch))

    state = hub.node_states[1]
    first_buffer_size = len(state.sample_buffer)

    hub.handle_packet(pack_data(1, 0, 100_000, first_batch))

    assert state.dropped_packets == 1
    assert len(state.sample_buffer) == first_buffer_size
    assert [sample.seq for sample in state.sample_buffer] == [0, 1, 2]


def test_status_snapshots_are_sorted_and_include_last_seen_age():
    hub = SoftTDMAHub([3, 1])
    hub.handle_packet(pack_hello(1, boot_id=1, flags=HELLO_FLAG_SYNC_LOCKED), received_monotonic=1.0)
    hub.handle_packet(pack_data(1, 0, 200_000, make_samples(2)), received_monotonic=2.25)

    snapshots = hub.status_snapshots(now_monotonic=3.0)

    assert [snapshot["id"] for snapshot in snapshots] == [1, 3]
    assert snapshots[0]["state"] == "streaming"
    assert snapshots[0]["isConnected"] is True
    assert snapshots[0]["lastSeenMs"] == 750
    assert snapshots[0]["lastSeq"] == 2
    assert snapshots[1]["state"] == "disconnected"
    assert snapshots[1]["lastSeenMs"] is None


def test_refresh_states_transitions_between_streaming_stale_and_disconnected():
    hub = SoftTDMAHub([1])
    hub.handle_packet(pack_hello(1, boot_id=1, flags=HELLO_FLAG_SYNC_LOCKED))
    hub.handle_packet(pack_data(1, 0, 100_000, make_samples(2)))

    now = 100.0
    hub.node_states[1].last_seen_monotonic = now - STALE_AFTER_SECONDS - 0.1
    hub.refresh_states(now)
    assert hub.node_states[1].state == "stale"

    hub.node_states[1].last_seen_monotonic = now - 0.1
    hub.refresh_states(now)
    assert hub.node_states[1].state == "streaming"

    hub.node_states[1].last_seen_monotonic = now - DISCONNECTED_AFTER_SECONDS - 0.1
    hub.refresh_states(now)
    assert hub.node_states[1].state == "disconnected"


def test_refresh_states_disconnects_hello_only_node_after_timeout():
    hub = SoftTDMAHub([1])
    hub.handle_packet(pack_hello(1, boot_id=42), received_monotonic=5.0)

    hub.refresh_states(now_monotonic=5.0 + DISCONNECTED_AFTER_SECONDS + 0.1)

    assert hub.node_states[1].state == "disconnected"
    assert hub.node_states[1].last_seen_monotonic == 0.0


def test_maybe_emit_streaming_status_respects_reporting_interval():
    events = []
    hub = SoftTDMAHub([1], status_callback=events.append)
    hub.handle_packet(pack_hello(1, boot_id=1, flags=HELLO_FLAG_SYNC_LOCKED), received_monotonic=1.0)
    hub.handle_packet(pack_data(1, 0, 100_000, make_samples(2)), received_monotonic=2.0)

    state = hub.node_states[1]
    state.last_report_monotonic = 0.0
    events.clear()

    hub.maybe_emit_streaming_status(now_monotonic=STATUS_STREAMING_REPORT_SECONDS - 0.01)
    assert events == []

    hub.maybe_emit_streaming_status(now_monotonic=STATUS_STREAMING_REPORT_SECONDS + 0.01)
    assert len(events) == 1
    assert events[0]["id"] == 1
    assert events[0]["state"] == "streaming"


def test_set_state_rejects_unknown_state_names():
    hub = SoftTDMAHub([1])

    with pytest.raises(ValueError, match="Unknown state"):
        hub._set_state(hub.node_states[1], "broken")

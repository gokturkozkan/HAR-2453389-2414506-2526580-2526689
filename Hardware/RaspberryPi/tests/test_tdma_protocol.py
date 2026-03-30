import struct

import pytest

from tdma_test_helpers import make_samples
from tdma_wifi_transport import (
    HELLO_FLAG_SYNC_LOCKED,
    MAGIC,
    MAX_BATCH_SAMPLES,
    MAX_NODE_ID,
    NODE_SLOT_MS,
    PACKET_TYPE_DATA,
    PROTOCOL_VERSION,
    ProtocolError,
    SAMPLE_PERIOD_US,
    SYNC_LEAD_MS,
    SUPERFRAME_US,
    decode_packet,
    default_sync_ack_table,
    pack_data,
    pack_hello,
    pack_sync,
    slot_start_us,
    status_to_is_connected,
    superframe_id_from_time,
)


def test_packet_round_trip_for_hello_sync_and_data():
    hello = decode_packet(pack_hello(3, boot_id=1234, firmware_version=7, flags=HELLO_FLAG_SYNC_LOCKED))
    assert hello["type"] == "hello"
    assert hello["node_id"] == 3
    assert hello["boot_id"] == 1234
    assert hello["firmware_version"] == 7
    assert hello["sync_locked"] is True

    sync = decode_packet(pack_sync(12, 456789, {1: 11, 3: 22}))
    assert sync["type"] == "sync"
    assert sync["superframe_id"] == 12
    assert sync["hub_time_us"] == 456789
    assert sync["next_seq_expected"][1] == 11
    assert sync["next_seq_expected"][3] == 22
    assert sync["next_seq_expected"][7] == 0

    data = decode_packet(pack_data(2, 40, 987654321, make_samples(3)))
    assert data["type"] == "data"
    assert data["node_id"] == 2
    assert data["first_seq"] == 40
    assert data["first_sample_time_us"] == 987654321
    assert data["sample_count"] == 3
    assert len(data["samples"]) == 3


def test_slot_start_superframe_and_connection_helpers():
    superframe_start_us = SUPERFRAME_US * 5
    assert superframe_id_from_time(superframe_start_us + 12_345) == 5
    assert slot_start_us(1, superframe_start_us) == superframe_start_us + (SYNC_LEAD_MS * 1000)
    assert slot_start_us(3, superframe_start_us) == superframe_start_us + (SYNC_LEAD_MS * 1000) + (2 * NODE_SLOT_MS * 1000)

    ack_table = default_sync_ack_table()
    assert ack_table[1] == 0
    assert ack_table[MAX_NODE_ID] == 0
    assert status_to_is_connected("streaming") is True
    assert status_to_is_connected("stale") is False


@pytest.mark.parametrize("node_id", [0, MAX_NODE_ID + 1])
def test_slot_start_rejects_invalid_node_ids(node_id):
    with pytest.raises(ValueError):
        slot_start_us(node_id, 0)


def test_pack_data_rejects_empty_and_oversized_batches():
    with pytest.raises(ValueError, match="at least one sample"):
        pack_data(1, 0, 0, [])

    with pytest.raises(ValueError, match="at most"):
        pack_data(1, 0, 0, make_samples(MAX_BATCH_SAMPLES + 1))


def test_decode_packet_rejects_invalid_headers_and_payloads():
    with pytest.raises(ProtocolError, match="Packet too short"):
        decode_packet(b"")

    hello = pack_hello(1, boot_id=99)
    with pytest.raises(ProtocolError, match="magic mismatch"):
        decode_packet(b"NOPE" + hello[4:])

    bad_version = hello[:4] + bytes([PROTOCOL_VERSION + 1]) + hello[5:]
    with pytest.raises(ProtocolError, match="Unsupported protocol version"):
        decode_packet(bad_version)

    bad_size = hello[:6] + struct.pack("<H", 0) + hello[8:]
    with pytest.raises(ProtocolError, match="payload size mismatch"):
        decode_packet(bad_size)

    unsupported = struct.pack("<4sBBH", MAGIC, PROTOCOL_VERSION, 99, 0)
    with pytest.raises(ProtocolError, match="Unsupported packet type"):
        decode_packet(unsupported)

    too_short_data = struct.pack("<4sBBH", MAGIC, PROTOCOL_VERSION, PACKET_TYPE_DATA, 1) + b"\x01"
    with pytest.raises(ProtocolError, match="DATA payload too short"):
        decode_packet(too_short_data)

    malformed_data = bytearray(pack_data(1, 10, 123_000, make_samples(1)))
    malformed_data[9] = 2
    with pytest.raises(ProtocolError, match="sample size mismatch"):
        decode_packet(bytes(malformed_data))


def test_data_packet_round_trip_keeps_sample_timing_spacing():
    decoded = decode_packet(pack_data(4, 7, 555_000, make_samples(4, offset=1.5)))

    assert decoded["sample_count"] == 4
    assert decoded["first_seq"] == 7
    assert decoded["first_sample_time_us"] == 555_000
    assert decoded["samples"][0]["ax"] == pytest.approx(1.5, abs=0.02)
    assert decoded["samples"][-1]["gz"] == pytest.approx(2.2, abs=0.02)
    assert SAMPLE_PERIOD_US > 0

from __future__ import annotations

import struct
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Callable, Deque, Dict, Iterable, List, Optional, Sequence, Tuple

MAGIC = b"HARB"
PROTOCOL_VERSION = 1

PACKET_TYPE_HELLO = 1
PACKET_TYPE_SYNC = 2
PACKET_TYPE_DATA = 3

HELLO_FLAG_SYNC_LOCKED = 1 << 0

MAX_NODE_ID = 7
WINDOW_SIZE = 32
WINDOW_DURATION_SECONDS = 3.0
SAMPLE_RATE_HZ = 25.0
SAMPLE_PERIOD_US = 40_000
SUPERFRAME_MS = 280
SUPERFRAME_SECONDS = SUPERFRAME_MS / 1000.0
SYNC_LEAD_MS = 20
NODE_SLOT_MS = 40
STALE_AFTER_SECONDS = 2.0
DISCONNECTED_AFTER_SECONDS = 5.0
STATUS_STREAMING_REPORT_SECONDS = 1.0
PREDICT_MIN_INTERVAL_SECONDS = 1.0
SAMPLE_BUFFER_CAPACITY = 1024
WINDOW_DURATION_US = int(WINDOW_DURATION_SECONDS * 1_000_000)
PREFERRED_ATT_MTU = 185
ATT_NOTIFICATION_OVERHEAD_BYTES = 3
PREFERRED_ATT_PAYLOAD_BYTES = PREFERRED_ATT_MTU - ATT_NOTIFICATION_OVERHEAD_BYTES
DATA_PREFIX_BYTES = 16
SAMPLE_BYTES = 12
FEATURE_KEYS = ("ax", "ay", "az", "gx", "gy", "gz")
CONNECTION_STATES = ("joining", "synced", "streaming", "stale", "disconnected")

MG_TO_MS2 = 9.80665 / 1000.0
MILLI_RAD_TO_RAD = 1.0 / 1000.0
MS2_TO_MG = 1000.0 / 9.80665
RAD_TO_MILLI_RAD = 1000.0

_HEADER_STRUCT = struct.Struct("<4sBBH")
_HELLO_STRUCT = struct.Struct("<BHII")
_SYNC_STRUCT = struct.Struct("<IQIHHBB")
_DATA_PREFIX_STRUCT = struct.Struct("<BBHIQ")
_SAMPLE_STRUCT = struct.Struct("<hhhhhh")


class ProtocolError(ValueError):
    pass


def monotonic_microseconds() -> int:
    return int(time.monotonic() * 1_000_000)


def superframe_id_from_time(now_us: int) -> int:
    return now_us // (SUPERFRAME_MS * 1000)


def slot_index_for_node(active_nodes: Sequence[int], node_id: int) -> int:
    try:
        return list(active_nodes).index(node_id)
    except ValueError as exc:
        raise ValueError(f"node_id {node_id} is not active") from exc


def status_to_is_connected(state: str) -> bool:
    return state == "streaming"


def att_payload_bytes_for_mtu(mtu: int) -> int:
    return max(20, int(mtu) - ATT_NOTIFICATION_OVERHEAD_BYTES)


def max_samples_per_packet(att_payload_bytes: int) -> int:
    payload = max(0, int(att_payload_bytes) - DATA_PREFIX_BYTES)
    return max(1, payload // SAMPLE_BYTES)


def _pack_packet(packet_type: int, payload: bytes) -> bytes:
    return _HEADER_STRUCT.pack(MAGIC, PROTOCOL_VERSION, packet_type, len(payload)) + payload


def _read_header(raw: bytes) -> Tuple[int, bytes]:
    if len(raw) < _HEADER_STRUCT.size:
        raise ProtocolError("Packet too short")
    magic, version, packet_type, payload_size = _HEADER_STRUCT.unpack_from(raw)
    if magic != MAGIC:
        raise ProtocolError("Packet magic mismatch")
    if version != PROTOCOL_VERSION:
        raise ProtocolError(f"Unsupported protocol version {version}")
    expected_size = _HEADER_STRUCT.size + payload_size
    if len(raw) != expected_size:
        raise ProtocolError("Packet payload size mismatch")
    return packet_type, raw[_HEADER_STRUCT.size:]


def pack_hello(node_id: int, boot_id: int, firmware_version: int = 1, flags: int = 0) -> bytes:
    payload = _HELLO_STRUCT.pack(node_id, flags, boot_id, firmware_version)
    return _pack_packet(PACKET_TYPE_HELLO, payload)


def pack_sync(
    superframe_id: int,
    hub_time_us: int,
    next_seq_expected: int,
    sample_period_us: int = SAMPLE_PERIOD_US,
    superframe_ms: int = SUPERFRAME_MS,
    slot_index: int = 0,
    active_node_count: int = 1,
) -> bytes:
    payload = _SYNC_STRUCT.pack(
        superframe_id,
        hub_time_us,
        next_seq_expected,
        sample_period_us,
        superframe_ms,
        slot_index,
        active_node_count,
    )
    return _pack_packet(PACKET_TYPE_SYNC, payload)


def pack_data(
    node_id: int,
    first_seq: int,
    first_sample_time_us: int,
    samples: Sequence[Dict[str, float]],
    flags: int = 0,
) -> bytes:
    sample_count = len(samples)
    if sample_count == 0:
        raise ValueError("DATA packet requires at least one sample")
    if sample_count > 255:
        raise ValueError("DATA packet may contain at most 255 samples")

    payload = bytearray()
    payload.extend(
        _DATA_PREFIX_STRUCT.pack(node_id, sample_count, flags, first_seq, first_sample_time_us)
    )
    for sample in samples:
        payload.extend(
            _SAMPLE_STRUCT.pack(
                int(round(sample["ax"] * MS2_TO_MG)),
                int(round(sample["ay"] * MS2_TO_MG)),
                int(round(sample["az"] * MS2_TO_MG)),
                int(round(sample["gx"] * RAD_TO_MILLI_RAD)),
                int(round(sample["gy"] * RAD_TO_MILLI_RAD)),
                int(round(sample["gz"] * RAD_TO_MILLI_RAD)),
            )
        )
    return _pack_packet(PACKET_TYPE_DATA, bytes(payload))


def decode_packet(raw: bytes) -> Dict[str, object]:
    packet_type, payload = _read_header(raw)

    if packet_type == PACKET_TYPE_HELLO:
        if len(payload) != _HELLO_STRUCT.size:
            raise ProtocolError("HELLO payload size mismatch")
        node_id, flags, boot_id, firmware_version = _HELLO_STRUCT.unpack(payload)
        return {
            "type": "hello",
            "node_id": int(node_id),
            "flags": int(flags),
            "boot_id": int(boot_id),
            "firmware_version": int(firmware_version),
            "sync_locked": bool(flags & HELLO_FLAG_SYNC_LOCKED),
        }

    if packet_type == PACKET_TYPE_SYNC:
        if len(payload) != _SYNC_STRUCT.size:
            raise ProtocolError("SYNC payload size mismatch")
        (
            superframe_id,
            hub_time_us,
            next_seq_expected,
            sample_period_us,
            superframe_ms,
            slot_index,
            active_node_count,
        ) = _SYNC_STRUCT.unpack(payload)
        return {
            "type": "sync",
            "superframe_id": int(superframe_id),
            "hub_time_us": int(hub_time_us),
            "next_seq_expected": int(next_seq_expected),
            "sample_period_us": int(sample_period_us),
            "superframe_ms": int(superframe_ms),
            "slot_index": int(slot_index),
            "active_node_count": int(active_node_count),
        }

    if packet_type == PACKET_TYPE_DATA:
        if len(payload) < _DATA_PREFIX_STRUCT.size:
            raise ProtocolError("DATA payload too short")
        node_id, sample_count, flags, first_seq, first_sample_time_us = _DATA_PREFIX_STRUCT.unpack_from(
            payload
        )
        expected_size = _DATA_PREFIX_STRUCT.size + (sample_count * _SAMPLE_STRUCT.size)
        if len(payload) != expected_size:
            raise ProtocolError("DATA payload sample size mismatch")
        offset = _DATA_PREFIX_STRUCT.size
        samples = []
        for _ in range(sample_count):
            ax_mg, ay_mg, az_mg, gx_mrad, gy_mrad, gz_mrad = _SAMPLE_STRUCT.unpack_from(
                payload, offset
            )
            offset += _SAMPLE_STRUCT.size
            samples.append(
                {
                    "ax": ax_mg * MG_TO_MS2,
                    "ay": ay_mg * MG_TO_MS2,
                    "az": az_mg * MG_TO_MS2,
                    "gx": gx_mrad * MILLI_RAD_TO_RAD,
                    "gy": gy_mrad * MILLI_RAD_TO_RAD,
                    "gz": gz_mrad * MILLI_RAD_TO_RAD,
                }
            )
        return {
            "type": "data",
            "node_id": int(node_id),
            "sample_count": int(sample_count),
            "flags": int(flags),
            "first_seq": int(first_seq),
            "first_sample_time_us": int(first_sample_time_us),
            "samples": samples,
        }

    raise ProtocolError(f"Unsupported packet type {packet_type}")


@dataclass
class TimedSample:
    seq: int
    t_us: int
    ax: float
    ay: float
    az: float
    gx: float
    gy: float
    gz: float

    def as_predict_reading(self) -> Dict[str, float]:
        return {
            "ax": self.ax,
            "ay": self.ay,
            "az": self.az,
            "gx": self.gx,
            "gy": self.gy,
            "gz": self.gz,
        }


@dataclass
class NodeRuntimeState:
    node_id: int
    transport: str = "ble"
    state: str = "disconnected"
    address: Optional[Tuple[str, int]] = None
    boot_id: Optional[int] = None
    firmware_version: Optional[int] = None
    hello_flags: int = 0
    last_hello_monotonic: float = 0.0
    last_seen_monotonic: float = 0.0
    last_sample_time_us: Optional[int] = None
    next_seq_expected: int = 0
    missed_packets: int = 0
    dropped_packets: int = 0
    last_report_monotonic: float = 0.0
    last_error: Optional[str] = None
    sample_buffer: Deque[TimedSample] = field(
        default_factory=lambda: deque(maxlen=SAMPLE_BUFFER_CAPACITY)
    )


class SoftTDMAHub:
    def __init__(
        self,
        active_nodes: Iterable[int],
        transport_name: str = "ble",
        status_callback: Optional[Callable[[Dict[str, object]], None]] = None,
    ) -> None:
        self.active_nodes = sorted(
            {int(node_id) for node_id in active_nodes if 1 <= int(node_id) <= MAX_NODE_ID}
        )
        self.node_states: Dict[int, NodeRuntimeState] = {
            node_id: NodeRuntimeState(node_id=node_id, transport=transport_name)
            for node_id in self.active_nodes
        }
        self.last_predict_monotonic = 0.0
        self.prediction_state = {
            "label": "WAITING",
            "confidence": "-",
            "used_nodes": [],
        }
        self.latest_rows: Dict[int, TimedSample] = {}
        self.status_callback = status_callback

    def build_sync_packet(self, node_id: int, now_us: Optional[int] = None) -> bytes:
        if now_us is None:
            now_us = monotonic_microseconds()
        slot_index = slot_index_for_node(self.active_nodes, node_id)
        next_expected = self.node_states[node_id].next_seq_expected
        return pack_sync(
            superframe_id=superframe_id_from_time(now_us),
            hub_time_us=now_us,
            next_seq_expected=next_expected,
            slot_index=slot_index,
            active_node_count=len(self.active_nodes),
        )

    def mark_joining(
        self,
        node_id: int,
        address: Optional[Tuple[str, int]] = None,
        last_error: Optional[str] = None,
    ) -> None:
        state = self.node_states.get(node_id)
        if state is None:
            return
        state.address = address or state.address
        state.last_error = last_error
        self._set_state(state, "joining")

    def mark_disconnected(self, node_id: int, error: Optional[str] = None) -> None:
        state = self.node_states.get(node_id)
        if state is None:
            return
        state.last_error = error
        self._set_state(state, "disconnected")

    def mark_transport_error(self, node_id: int, error: str, disconnected: bool = False) -> None:
        state = self.node_states.get(node_id)
        if state is None:
            return
        state.last_error = error
        if disconnected:
            self._set_state(state, "disconnected")
        else:
            self._emit_status(state)

    def record_prediction_result(
        self, ok: bool, result: Dict[str, object], now_monotonic: Optional[float] = None
    ) -> bool:
        if now_monotonic is None:
            now_monotonic = time.monotonic()
        if ok:
            self.prediction_state["label"] = result.get("activity", "?")
            self.prediction_state["confidence"] = result.get("confidence", "?")
            self.prediction_state["used_nodes"] = result.get("used_node_ids", self.active_nodes)
            self.last_predict_monotonic = now_monotonic
        else:
            self.prediction_state["label"] = "ERROR"
            self.prediction_state["confidence"] = "-"
            self.prediction_state["used_nodes"] = self.active_nodes
        return ok

    def handle_packet(
        self,
        raw: bytes,
        addr: Optional[Tuple[str, int]] = None,
        received_monotonic: Optional[float] = None,
    ) -> Dict[str, object]:
        if received_monotonic is None:
            received_monotonic = time.monotonic()
        decoded = decode_packet(raw)
        packet_type = decoded["type"]
        if packet_type == "hello":
            self._handle_hello(decoded, addr, received_monotonic)
        elif packet_type == "data":
            self._handle_data(decoded, addr, received_monotonic)
        else:
            raise ProtocolError(f"Hub should not ingest packet type {packet_type}")
        return decoded

    def _reset_sample_tracking(self, state: NodeRuntimeState) -> None:
        state.last_sample_time_us = None
        state.next_seq_expected = 0
        state.missed_packets = 0
        state.dropped_packets = 0
        state.sample_buffer.clear()
        self.latest_rows.pop(state.node_id, None)

    def _handle_hello(
        self,
        packet: Dict[str, object],
        addr: Optional[Tuple[str, int]],
        received_monotonic: float,
    ) -> None:
        node_id = int(packet["node_id"])
        state = self.node_states.get(node_id)
        if state is None:
            return

        boot_id = int(packet["boot_id"])
        if state.boot_id is not None and state.boot_id != boot_id:
            self._reset_sample_tracking(state)

        state.address = addr or state.address
        state.boot_id = boot_id
        state.firmware_version = int(packet["firmware_version"])
        state.hello_flags = int(packet["flags"])
        state.last_hello_monotonic = received_monotonic
        state.last_error = None

        if state.state == "disconnected":
            self._set_state(state, "joining")
        if packet.get("sync_locked"):
            if state.state != "streaming":
                self._set_state(state, "synced")
        else:
            self._emit_status(state)

    def _handle_data(
        self,
        packet: Dict[str, object],
        addr: Optional[Tuple[str, int]],
        received_monotonic: float,
    ) -> None:
        node_id = int(packet["node_id"])
        state = self.node_states.get(node_id)
        if state is None:
            return

        samples = list(packet["samples"])
        sample_count = int(packet["sample_count"])
        first_seq = int(packet["first_seq"])
        first_sample_time_us = int(packet["first_sample_time_us"])
        state.address = addr or state.address
        state.last_seen_monotonic = received_monotonic
        state.last_error = None

        expected = state.next_seq_expected
        last_seq_in_packet = first_seq + sample_count
        if last_seq_in_packet <= expected:
            state.dropped_packets += 1
            self._emit_status(state)
            return

        start_offset = max(0, expected - first_seq)
        if first_seq > expected:
            state.missed_packets += first_seq - expected
            expected = first_seq

        for sample_offset in range(start_offset, sample_count):
            seq = first_seq + sample_offset
            t_us = first_sample_time_us + (sample_offset * SAMPLE_PERIOD_US)
            sample = samples[sample_offset]
            timed = TimedSample(
                seq=seq,
                t_us=t_us,
                ax=float(sample["ax"]),
                ay=float(sample["ay"]),
                az=float(sample["az"]),
                gx=float(sample["gx"]),
                gy=float(sample["gy"]),
                gz=float(sample["gz"]),
            )
            state.sample_buffer.append(timed)
            state.last_sample_time_us = timed.t_us
            self.latest_rows[node_id] = timed

        state.next_seq_expected = max(expected, last_seq_in_packet)
        self._set_state(state, "streaming")

    def refresh_states(self, now_monotonic: Optional[float] = None) -> None:
        if now_monotonic is None:
            now_monotonic = time.monotonic()
        for state in self.node_states.values():
            if state.state == "disconnected":
                continue
            reference = state.last_seen_monotonic or state.last_hello_monotonic
            if not reference:
                continue
            age = now_monotonic - reference
            if age >= DISCONNECTED_AFTER_SECONDS:
                self._set_state(state, "disconnected")
            elif age >= STALE_AFTER_SECONDS and state.state == "streaming":
                self._set_state(state, "stale")
            elif age < STALE_AFTER_SECONDS and state.state == "stale":
                self._set_state(state, "streaming")

    def status_snapshot(
        self, node_id: int, now_monotonic: Optional[float] = None
    ) -> Dict[str, object]:
        if now_monotonic is None:
            now_monotonic = time.monotonic()
        state = self.node_states[node_id]
        last_seen_ms = None
        reference = state.last_seen_monotonic or state.last_hello_monotonic
        if reference:
            last_seen_ms = int(max(0.0, now_monotonic - reference) * 1000)
        return {
            "id": node_id,
            "transport": state.transport,
            "isConnected": status_to_is_connected(state.state),
            "state": state.state,
            "lastSeenMs": last_seen_ms,
            "lastSeq": int(state.next_seq_expected),
            "missedPackets": int(state.missed_packets),
            "bootId": state.boot_id,
            "firmwareVersion": state.firmware_version,
            "lastError": state.last_error,
        }

    def status_snapshots(self, now_monotonic: Optional[float] = None) -> List[Dict[str, object]]:
        return [self.status_snapshot(node_id, now_monotonic) for node_id in self.active_nodes]

    def maybe_emit_streaming_status(self, now_monotonic: Optional[float] = None) -> None:
        if self.status_callback is None:
            return
        if now_monotonic is None:
            now_monotonic = time.monotonic()
        for state in self.node_states.values():
            if state.state != "streaming":
                continue
            if (now_monotonic - state.last_report_monotonic) >= STATUS_STREAMING_REPORT_SECONDS:
                state.last_report_monotonic = now_monotonic
                self.status_callback(self.status_snapshot(state.node_id, now_monotonic))

    def _emit_status(self, state: NodeRuntimeState) -> None:
        if self.status_callback is not None:
            self.status_callback(self.status_snapshot(state.node_id))

    def _set_state(self, state: NodeRuntimeState, next_state: str) -> None:
        if next_state not in CONNECTION_STATES:
            raise ValueError(f"Unknown state {next_state}")
        if state.state == next_state:
            self._emit_status(state)
            return
        state.state = next_state
        state.last_report_monotonic = time.monotonic()
        self._emit_status(state)

    def build_prediction_windows(self) -> Optional[Dict[int, List[Dict[str, float]]]]:
        if not self.active_nodes:
            return None
        if any(self.node_states[node_id].state != "streaming" for node_id in self.active_nodes):
            return None

        latest_common_time = min(
            self.node_states[node_id].last_sample_time_us or 0 for node_id in self.active_nodes
        )
        if latest_common_time <= 0:
            return None

        window_start_us = latest_common_time - WINDOW_DURATION_US
        target_times = _linspace(window_start_us, latest_common_time, WINDOW_SIZE)
        result: Dict[int, List[Dict[str, float]]] = {}

        for node_id in self.active_nodes:
            samples = list(self.node_states[node_id].sample_buffer)
            if len(samples) < 2:
                return None
            if samples[0].t_us > window_start_us:
                return None
            if samples[-1].t_us < latest_common_time:
                return None

            timestamps = [sample.t_us for sample in samples]
            window_rows = [{} for _ in range(WINDOW_SIZE)]
            for feature in FEATURE_KEYS:
                values = [float(getattr(sample, feature)) for sample in samples]
                interpolated = _interpolate_series(target_times, timestamps, values)
                for index, value in enumerate(interpolated):
                    window_rows[index][feature] = value
            result[node_id] = window_rows
        return result

    def latest_table_rows(self) -> Dict[int, Dict[str, float]]:
        rows: Dict[int, Dict[str, float]] = {}
        for node_id, sample in self.latest_rows.items():
            rows[node_id] = {
                "t": sample.t_us // 1000,
                "ax": sample.ax,
                "ay": sample.ay,
                "az": sample.az,
                "gx": sample.gx,
                "gy": sample.gy,
                "gz": sample.gz,
            }
        return rows


def _linspace(start: float, stop: float, count: int) -> List[float]:
    if count <= 1:
        return [float(stop)]
    step = (stop - start) / float(count - 1)
    return [start + (step * index) for index in range(count)]


def _interpolate_series(
    target_times: Sequence[float], timestamps: Sequence[int], values: Sequence[float]
) -> List[float]:
    if len(timestamps) != len(values):
        raise ValueError("timestamps and values must have the same length")
    if len(timestamps) < 2:
        raise ValueError("at least two points are required for interpolation")

    results: List[float] = []
    left_index = 0

    for target in target_times:
        if target <= timestamps[0]:
            results.append(float(values[0]))
            continue
        if target >= timestamps[-1]:
            results.append(float(values[-1]))
            continue

        while left_index + 1 < len(timestamps) and timestamps[left_index + 1] < target:
            left_index += 1

        t0 = float(timestamps[left_index])
        t1 = float(timestamps[left_index + 1])
        v0 = float(values[left_index])
        v1 = float(values[left_index + 1])
        if t1 == t0:
            results.append(v1)
            continue

        ratio = (float(target) - t0) / (t1 - t0)
        results.append(v0 + ((v1 - v0) * ratio))

    return results

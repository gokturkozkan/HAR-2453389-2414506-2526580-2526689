from __future__ import annotations

import socket
import struct
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Callable, Deque, Dict, Iterable, List, Optional, Sequence, Tuple

import numpy as np

MAGIC = b"HARW"
PROTOCOL_VERSION = 1

PACKET_TYPE_HELLO = 1
PACKET_TYPE_SYNC = 2
PACKET_TYPE_DATA = 3

HELLO_FLAG_SYNC_LOCKED = 1 << 0

MAX_NODE_ID = 7
WINDOW_SIZE = 32
WINDOW_DURATION_SECONDS = 3.0
SAMPLE_RATE_HZ = 25.0
SAMPLE_PERIOD_US = int(round(1_000_000 / SAMPLE_RATE_HZ))
SUPERFRAME_SECONDS = 0.3
SUPERFRAME_US = int(round(SUPERFRAME_SECONDS * 1_000_000))
SYNC_LEAD_MS = 20
NODE_SLOT_MS = 40
MAX_BATCH_SAMPLES = 16
SYNC_TIMEOUT_SECONDS = 0.9
STALE_AFTER_SECONDS = 2.0
DISCONNECTED_AFTER_SECONDS = 5.0
STATUS_STREAMING_REPORT_SECONDS = 1.0
PREDICT_MIN_INTERVAL_SECONDS = 1.0
SAMPLE_BUFFER_CAPACITY = 1024
MG_TO_MS2 = 9.80665 / 1000.0
MILLI_RAD_TO_RAD = 1.0 / 1000.0
MS2_TO_MG = 1000.0 / 9.80665
RAD_TO_MILLI_RAD = 1000.0
CONNECTION_STATES = ("joining", "synced", "streaming", "stale", "disconnected")
FEATURE_KEYS = ("ax", "ay", "az", "gx", "gy", "gz")

_HEADER_STRUCT = struct.Struct("<4sBBH")
_HELLO_STRUCT = struct.Struct("<BBHII")
_SYNC_STRUCT = struct.Struct("<IQ" + ("I" * MAX_NODE_ID))
_DATA_PREFIX_STRUCT = struct.Struct("<BBHIQ")
_SAMPLE_STRUCT = struct.Struct("<hhhhhh")


class ProtocolError(ValueError):
    pass


def monotonic_microseconds() -> int:
    return int(time.monotonic() * 1_000_000)


def superframe_id_from_time(now_us: int) -> int:
    return now_us // SUPERFRAME_US


def slot_start_us(node_id: int, superframe_start_us: int) -> int:
    if not 1 <= node_id <= MAX_NODE_ID:
        raise ValueError(f"node_id must be between 1 and {MAX_NODE_ID}")
    return superframe_start_us + (SYNC_LEAD_MS * 1000) + ((node_id - 1) * NODE_SLOT_MS * 1000)


def status_to_is_connected(state: str) -> bool:
    return state == "streaming"


def default_sync_ack_table() -> Dict[int, int]:
    return {node_id: 0 for node_id in range(1, MAX_NODE_ID + 1)}


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
    payload = _HELLO_STRUCT.pack(node_id, 0, flags, boot_id, firmware_version)
    return _pack_packet(PACKET_TYPE_HELLO, payload)


def pack_sync(superframe_id: int, hub_time_us: int, next_seq_expected: Dict[int, int]) -> bytes:
    ordered = [int(next_seq_expected.get(node_id, 0)) for node_id in range(1, MAX_NODE_ID + 1)]
    payload = _SYNC_STRUCT.pack(superframe_id, hub_time_us, *ordered)
    return _pack_packet(PACKET_TYPE_SYNC, payload)


def pack_data(
    node_id: int,
    first_seq: int,
    first_sample_time_us: int,
    samples: Sequence[Dict[str, float]],
) -> bytes:
    sample_count = len(samples)
    if sample_count == 0:
        raise ValueError("DATA packet requires at least one sample")
    if sample_count > MAX_BATCH_SAMPLES:
        raise ValueError(f"DATA packet may contain at most {MAX_BATCH_SAMPLES} samples")

    payload = bytearray()
    payload.extend(_DATA_PREFIX_STRUCT.pack(node_id, sample_count, 0, first_seq, first_sample_time_us))
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
        node_id, _, flags, boot_id, firmware_version = _HELLO_STRUCT.unpack(payload)
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
        values = _SYNC_STRUCT.unpack(payload)
        superframe_id = int(values[0])
        hub_time_us = int(values[1])
        ack_map = {
            node_id: int(values[1 + node_id])
            for node_id in range(1, MAX_NODE_ID + 1)
        }
        return {
            "type": "sync",
            "superframe_id": superframe_id,
            "hub_time_us": hub_time_us,
            "next_seq_expected": ack_map,
        }

    if packet_type == PACKET_TYPE_DATA:
        if len(payload) < _DATA_PREFIX_STRUCT.size:
            raise ProtocolError("DATA payload too short")
        node_id, sample_count, _, first_seq, first_sample_time_us = _DATA_PREFIX_STRUCT.unpack_from(payload)
        expected_size = _DATA_PREFIX_STRUCT.size + (sample_count * _SAMPLE_STRUCT.size)
        if len(payload) != expected_size:
            raise ProtocolError("DATA payload sample size mismatch")
        offset = _DATA_PREFIX_STRUCT.size
        samples = []
        for _ in range(sample_count):
            ax_mg, ay_mg, az_mg, gx_mrad, gy_mrad, gz_mrad = _SAMPLE_STRUCT.unpack_from(payload, offset)
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
    clock_offset_us: float = 0.0
    last_report_monotonic: float = 0.0
    sample_buffer: Deque[TimedSample] = field(
        default_factory=lambda: deque(maxlen=SAMPLE_BUFFER_CAPACITY)
    )


class SoftTDMAHub:
    def __init__(
        self,
        active_nodes: Iterable[int],
        status_callback: Optional[Callable[[Dict[str, object]], None]] = None,
    ) -> None:
        self.active_nodes = sorted({int(node_id) for node_id in active_nodes if 1 <= int(node_id) <= MAX_NODE_ID})
        self.node_states: Dict[int, NodeRuntimeState] = {
            node_id: NodeRuntimeState(node_id=node_id)
            for node_id in self.active_nodes
        }
        self.superframe_id = 0
        self.last_predict_monotonic = 0.0
        self.prediction_state = {
            "label": "WAITING",
            "confidence": "-",
            "used_nodes": [],
        }
        self.latest_rows: Dict[int, TimedSample] = {}
        self.status_callback = status_callback

    def build_sync_packet(self, now_us: Optional[int] = None) -> bytes:
        if now_us is None:
            now_us = monotonic_microseconds()
        self.superframe_id = superframe_id_from_time(now_us)
        next_seq_expected = {
            node_id: self.node_states[node_id].next_seq_expected
            for node_id in self.active_nodes
        }
        return pack_sync(self.superframe_id, now_us, next_seq_expected)

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

        state.address = addr
        state.boot_id = int(packet["boot_id"])
        state.firmware_version = int(packet["firmware_version"])
        state.hello_flags = int(packet["flags"])
        state.last_hello_monotonic = received_monotonic

        if state.state == "disconnected":
            self._set_state(state, "joining")
        if packet.get("sync_locked") and state.state in {"joining", "disconnected"}:
            self._set_state(state, "synced")

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
        state.address = addr
        state.last_seen_monotonic = received_monotonic

        expected = state.next_seq_expected
        last_seq_in_packet = first_seq + sample_count
        if last_seq_in_packet <= expected:
            state.dropped_packets += 1
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
        state.clock_offset_us = float(first_sample_time_us - monotonic_microseconds())
        self._set_state(state, "streaming")

    def refresh_states(self, now_monotonic: Optional[float] = None) -> None:
        if now_monotonic is None:
            now_monotonic = time.monotonic()
        for state in self.node_states.values():
            if state.state == "disconnected":
                continue
            if state.last_seen_monotonic:
                age = now_monotonic - state.last_seen_monotonic
                if age >= DISCONNECTED_AFTER_SECONDS:
                    self._set_state(state, "disconnected")
                elif age >= STALE_AFTER_SECONDS and state.state == "streaming":
                    self._set_state(state, "stale")
                elif age < STALE_AFTER_SECONDS and state.state == "stale":
                    self._set_state(state, "streaming")
            elif state.last_hello_monotonic:
                if now_monotonic - state.last_hello_monotonic >= DISCONNECTED_AFTER_SECONDS:
                    self._set_state(state, "disconnected")

    def status_snapshot(self, node_id: int, now_monotonic: Optional[float] = None) -> Dict[str, object]:
        if now_monotonic is None:
            now_monotonic = time.monotonic()
        state = self.node_states[node_id]
        last_seen_ms = None
        if state.last_seen_monotonic:
            last_seen_ms = int(max(0.0, now_monotonic - state.last_seen_monotonic) * 1000)
        return {
            "id": node_id,
            "isConnected": status_to_is_connected(state.state),
            "state": state.state,
            "lastSeenMs": last_seen_ms,
            "lastSeq": int(state.next_seq_expected),
            "missedPackets": int(state.missed_packets),
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

    def _set_state(self, state: NodeRuntimeState, next_state: str) -> None:
        if next_state not in CONNECTION_STATES:
            raise ValueError(f"Unknown state {next_state}")
        if state.state == next_state:
            return
        state.state = next_state
        state.last_report_monotonic = time.monotonic()
        if next_state == "disconnected":
            state.last_seen_monotonic = 0.0
        if self.status_callback is not None:
            self.status_callback(self.status_snapshot(state.node_id))

    def build_prediction_windows(self) -> Optional[Dict[int, List[Dict[str, float]]]]:
        if not self.active_nodes:
            return None
        if any(self.node_states[node_id].state != "streaming" for node_id in self.active_nodes):
            return None

        latest_common_time = min(
            self.node_states[node_id].last_sample_time_us or 0
            for node_id in self.active_nodes
        )
        if latest_common_time <= 0:
            return None

        window_start_us = latest_common_time - int(WINDOW_DURATION_SECONDS * 1_000_000)
        target_times = np.linspace(window_start_us, latest_common_time, WINDOW_SIZE)
        result: Dict[int, List[Dict[str, float]]] = {}
        for node_id in self.active_nodes:
            samples = list(self.node_states[node_id].sample_buffer)
            if len(samples) < 2:
                return None
            if samples[0].t_us > window_start_us:
                return None
            timestamps = np.array([sample.t_us for sample in samples], dtype=np.float64)
            if timestamps[-1] < latest_common_time:
                return None

            window_rows = []
            for feature in FEATURE_KEYS:
                values = np.array([getattr(sample, feature) for sample in samples], dtype=np.float64)
                interpolated = np.interp(target_times, timestamps, values)
                if not window_rows:
                    window_rows = [{} for _ in range(WINDOW_SIZE)]
                for index, value in enumerate(interpolated):
                    window_rows[index][feature] = float(value)
            result[node_id] = window_rows
        return result

    def maybe_predict(
        self,
        predict_func: Callable[[List[int], Dict[int, List[Dict[str, float]]]], Tuple[bool, Dict[str, object]]],
        now_monotonic: Optional[float] = None,
    ) -> bool:
        if now_monotonic is None:
            now_monotonic = time.monotonic()
        if (now_monotonic - self.last_predict_monotonic) < PREDICT_MIN_INTERVAL_SECONDS:
            return False
        windows = self.build_prediction_windows()
        if windows is None:
            return False
        ok, result = predict_func(self.active_nodes, windows)
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


def broadcast_socket() -> socket.socket:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    return sock


def listening_socket(bind_port: int) -> socket.socket:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(("0.0.0.0", bind_port))
    sock.setblocking(False)
    return sock

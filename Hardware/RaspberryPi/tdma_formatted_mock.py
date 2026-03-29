import json
import math
import os
import random
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional
from urllib import error, request

from tdma_wifi_transport import (
    HELLO_FLAG_SYNC_LOCKED,
    MAX_BATCH_SAMPLES,
    SAMPLE_PERIOD_US,
    SAMPLE_RATE_HZ,
    SUPERFRAME_SECONDS,
    SoftTDMAHub,
    decode_packet,
    pack_data,
    pack_hello,
    pack_sync,
)

BACKEND_URL = os.getenv("HAR_BACKEND_URL", "http://127.0.0.1:3000")
SEND_TO_BACKEND = os.getenv("MOCK_SEND_TO_BACKEND", "1") == "1"
RUN_SECONDS = float(os.getenv("MOCK_RUN_SECONDS", "99999"))
ACTIVITY_SWITCH_SECONDS = float(os.getenv("MOCK_ACTIVITY_SWITCH_SECONDS", "30"))
DROP_RATE = max(0.0, min(1.0, float(os.getenv("MOCK_DROP_RATE", "0.0"))))
JITTER_MS = max(0.0, float(os.getenv("MOCK_JITTER_MS", "0.0")))
CLOCK_DRIFT_PPM = float(os.getenv("MOCK_CLOCK_DRIFT_PPM", "0.0"))
OUTAGE_NODE = int(os.getenv("MOCK_OUTAGE_NODE", "0"))
OUTAGE_START_SECONDS = float(os.getenv("MOCK_OUTAGE_START_SECONDS", "15"))
OUTAGE_DURATION_SECONDS = float(os.getenv("MOCK_OUTAGE_SECONDS", "0"))
RANDOM_SEED = int(os.getenv("MOCK_RANDOM_SEED", "1234"))
RENDER_INTERVAL_SECONDS = float(os.getenv("HAR_RENDER_INTERVAL_SECONDS", "0.5"))

WALK_FREQ_HZ = 1.8
GYRO_SCALE = 1.4
ACC_NOISE = 0.12
GYRO_NOISE = 0.08
STAND_ACC_NOISE = 0.015
STAND_GYRO_NOISE = 0.01


def clear_console():
    print("\n" * 40)


def choose_nodes():
    raw = os.getenv("MOCK_NODE_IDS", "")
    if not raw.strip():
        return list(range(1, 8))
    nodes = []
    for part in raw.split(","):
        try:
            node_id = int(part.strip())
        except ValueError:
            continue
        if 1 <= node_id <= 7:
            nodes.append(node_id)
    nodes = sorted(set(nodes))
    return nodes or list(range(1, 8))


def backend_post(path, payload, timeout=1.0):
    if not SEND_TO_BACKEND:
        if path == "/predict":
            mode = payload.get("mock_activity_mode", "walking")
            activity = "walking" if mode == "walking" else "standing"
            return True, {
                "activity": activity,
                "confidence": 0.98 if activity == "walking" else 0.99,
                "used_node_ids": payload.get("node_ids", []),
                "mock": True,
            }
        return True, {"ok": True, "mock": True}

    url = f"{BACKEND_URL}{path}"
    body = json.dumps(payload).encode("utf-8")
    req = request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", errors="ignore")
            if not raw:
                return True, {}
            try:
                return True, json.loads(raw)
            except Exception:
                return True, {"raw": raw}
    except error.HTTPError as exc:
        try:
            raw = exc.read().decode("utf-8", errors="ignore")
            try:
                return False, json.loads(raw) if raw else {}
            except Exception:
                return False, raw
        except Exception:
            return False, f"HTTP Error {exc.code}: {exc.reason}"
    except error.URLError as exc:
        return False, str(exc)
    except Exception as exc:
        return False, str(exc)


class BackendStatusReporter:
    def __init__(self):
        self.cache = {}

    def __call__(self, payload):
        node_id = payload["id"]
        previous = self.cache.get(node_id)
        if previous == payload:
            return
        ok, result = backend_post(f"/esp-status/{node_id}", payload, timeout=1.0)
        if ok:
            self.cache[node_id] = dict(payload)
            mode = "REAL BACKEND" if SEND_TO_BACKEND else "MOCK BACKEND"
            print(
                f"[{mode}] Node {node_id}: {payload['state']} "
                f"(seq={payload['lastSeq']}, missed={payload['missedPackets']})"
            )
        else:
            print(f"[BACKEND] Failed to update node {node_id}: {result}")


def compute_noise(node_id, step, channel_scale):
    return channel_scale * (
        math.sin(0.37 * step + node_id * 1.11)
        + 0.5 * math.cos(0.19 * step + node_id * 0.73)
    )


def get_activity_mode(elapsed_seconds):
    block = int(elapsed_seconds // ACTIVITY_SWITCH_SECONDS)
    return "walking" if (block % 2 == 0) else "standing"


def generate_walking_sample(node_id, step):
    t_seconds = step / SAMPLE_RATE_HZ
    phase = node_id * 0.33
    w = 2.0 * math.pi * WALK_FREQ_HZ * t_seconds
    return {
        "ax": 1.4 * math.sin(w + phase) + compute_noise(node_id, step, ACC_NOISE),
        "ay": 0.6 * math.cos(w * 0.7 + phase * 0.5) + compute_noise(node_id, step + 3, ACC_NOISE * 0.7),
        "az": 9.8 + 0.9 * math.sin(w * 2.0 + phase * 0.25) + compute_noise(node_id, step + 7, ACC_NOISE * 0.5),
        "gx": GYRO_SCALE * math.cos(w + phase) + compute_noise(node_id, step + 11, GYRO_NOISE),
        "gy": 0.8 * math.sin(w * 1.2 + phase) + compute_noise(node_id, step + 17, GYRO_NOISE * 0.8),
        "gz": 0.5 * math.cos(w * 0.8 + phase * 0.8) + compute_noise(node_id, step + 23, GYRO_NOISE * 0.6),
    }


def generate_standing_sample(node_id, step):
    t_seconds = step / SAMPLE_RATE_HZ
    phase = node_id * 0.17
    return {
        "ax": 0.03 * math.sin(0.25 * t_seconds + phase) + compute_noise(node_id, step, STAND_ACC_NOISE),
        "ay": 0.03 * math.cos(0.21 * t_seconds + phase) + compute_noise(node_id, step + 5, STAND_ACC_NOISE),
        "az": 9.8 + 0.05 * math.sin(0.18 * t_seconds + phase) + compute_noise(node_id, step + 9, STAND_ACC_NOISE),
        "gx": 0.015 * math.sin(0.30 * t_seconds + phase) + compute_noise(node_id, step + 13, STAND_GYRO_NOISE),
        "gy": 0.015 * math.cos(0.27 * t_seconds + phase) + compute_noise(node_id, step + 17, STAND_GYRO_NOISE),
        "gz": 0.012 * math.sin(0.22 * t_seconds + phase) + compute_noise(node_id, step + 21, STAND_GYRO_NOISE),
    }


def generate_sample(node_id, step, activity_mode):
    if activity_mode == "standing":
        return generate_standing_sample(node_id, step)
    return generate_walking_sample(node_id, step)


@dataclass
class MockNode:
    node_id: int
    boot_id: int
    clock_scale: float
    pending_samples: List[Dict[str, object]] = field(default_factory=list)
    next_seq: int = 0
    next_step: int = 0
    last_generated_hub_time_us: int = 0
    sync_locked: bool = False
    hello_stage: int = 0

    def apply_ack(self, next_seq_expected: int):
        self.pending_samples = [
            sample for sample in self.pending_samples if int(sample["seq"]) >= int(next_seq_expected)
        ]

    def generate_until(self, hub_time_us: int, activity_mode: str, jitter_ms: float):
        while self.last_generated_hub_time_us <= hub_time_us:
            sample = generate_sample(self.node_id, self.next_step, activity_mode)
            jitter_offset_us = int(round(random.uniform(-jitter_ms, jitter_ms) * 1000.0))
            timestamp_us = int(round(self.last_generated_hub_time_us * self.clock_scale)) + jitter_offset_us
            self.pending_samples.append(
                {
                    "seq": self.next_seq,
                    "t_us": timestamp_us,
                    "sample": sample,
                }
            )
            self.next_seq += 1
            self.next_step += 1
            self.last_generated_hub_time_us += SAMPLE_PERIOD_US

    def next_hello_packet(self) -> Optional[bytes]:
        if self.hello_stage == 0:
            self.hello_stage = 1
            return pack_hello(self.node_id, self.boot_id, firmware_version=1, flags=0)
        if self.hello_stage == 1:
            self.sync_locked = True
            self.hello_stage = 2
            return pack_hello(
                self.node_id,
                self.boot_id,
                firmware_version=1,
                flags=HELLO_FLAG_SYNC_LOCKED,
            )
        return None

    def next_data_packet(self) -> Optional[bytes]:
        if not self.sync_locked or not self.pending_samples:
            return None
        batch = self.pending_samples[:MAX_BATCH_SAMPLES]
        first_seq = int(batch[0]["seq"])
        first_sample_time_us = int(batch[0]["t_us"])
        samples = [item["sample"] for item in batch]
        return pack_data(self.node_id, first_seq, first_sample_time_us, samples)


def predict_combined_window(active_nodes, node_windows, activity_mode):
    payload = {
        "node_ids": list(active_nodes),
        "windows_by_node": {str(node_id): readings for node_id, readings in node_windows.items()},
        "mock_activity_mode": activity_mode,
    }
    ok, result = backend_post("/predict", payload, timeout=2.5)
    if ok:
        suffix = " [mock backend]" if result.get("mock") else ""
        print(
            f"[PREDICT] Generated={activity_mode} | Predicted={result.get('activity', '?')} "
            f"({result.get('confidence', '?')}){suffix}"
        )
    else:
        print(f"[PREDICT] Generated={activity_mode} | Prediction failed: {result}")
    return ok, result


def scientific_row(data):
    t_ms = int(data["t"])
    ax_mg = int(round(data["ax"] / 9.80665 * 1000))
    ay_mg = int(round(data["ay"] / 9.80665 * 1000))
    az_mg = int(round(data["az"] / 9.80665 * 1000))
    gx_milli = int(round(data["gx"] * 1000))
    gy_milli = int(round(data["gy"] * 1000))
    gz_milli = int(round(data["gz"] * 1000))
    return t_ms, ax_mg, ay_mg, az_mg, gx_milli, gy_milli, gz_milli


def print_table(hub, active_nodes, activity_mode, elapsed_seconds):
    clear_console()
    print("===== TDMA Sensor Dashboard (MOCK WI-FI INPUT / REAL PREDICTION) =====")
    print(f"Generated mock activity : {activity_mode.upper()}")
    source = "MOCK" if not SEND_TO_BACKEND else "BACKEND"
    print(
        f"Predicted label        : {hub.prediction_state.get('label', 'WAITING')} "
        f"({hub.prediction_state.get('confidence', '-')}) [{source}]"
    )
    print(f"Elapsed seconds        : {elapsed_seconds:.1f}")
    print(f"Loss/jitter/drift      : drop={DROP_RATE:.2f}, jitter={JITTER_MS:.1f}ms, drift={CLOCK_DRIFT_PPM:.1f}ppm")
    print()
    header = (
        "Node | State        | Seen(ms) | Seq    | Miss | MILLISEC | "
        " accX    accY    accZ  |  gyroX   gyroY   gyroZ"
    )
    print(header)
    print("-" * len(header))
    latest = hub.latest_table_rows()
    for snapshot in hub.status_snapshots():
        node_id = snapshot["id"]
        if node_id not in active_nodes:
            continue
        seen = "---" if snapshot["lastSeenMs"] is None else f"{snapshot['lastSeenMs']:7d}"
        data = latest.get(node_id)
        if data is None:
            print(
                f"  {node_id:2d} | {snapshot['state']:<12} | {seen} | "
                f"{snapshot['lastSeq']:6d} | {snapshot['missedPackets']:4d} |"
                "   ---   |   ---    ---    --- |   ---    ---    ---"
            )
            continue
        t_ms, ax_mg, ay_mg, az_mg, gx_milli, gy_milli, gz_milli = scientific_row(data)
        print(
            f"  {node_id:2d} | {snapshot['state']:<12} | {seen} | "
            f"{snapshot['lastSeq']:6d} | {snapshot['missedPackets']:4d} | {t_ms:7d} | "
            f"{ax_mg:6d} {ay_mg:6d} {az_mg:6d} | {gx_milli:6d} {gy_milli:6d} {gz_milli:6d}"
        )


def node_in_outage(node_id, elapsed_seconds):
    if OUTAGE_DURATION_SECONDS <= 0 or OUTAGE_NODE != node_id:
        return False
    return OUTAGE_START_SECONDS <= elapsed_seconds < (OUTAGE_START_SECONDS + OUTAGE_DURATION_SECONDS)


def main():
    random.seed(RANDOM_SEED)
    active_nodes = choose_nodes()
    print(f"Using mock nodes: {active_nodes}")
    print(f"Backend mode: {'REAL' if SEND_TO_BACKEND else 'DRY RUN / MOCK'}")
    print(f"Activity switches every {ACTIVITY_SWITCH_SECONDS} seconds")
    print(f"Run duration: {RUN_SECONDS} seconds")

    reporter = BackendStatusReporter()
    hub = SoftTDMAHub(active_nodes, status_callback=reporter)
    for snapshot in hub.status_snapshots():
        reporter(snapshot)

    nodes = {}
    for node_id in active_nodes:
        drift_scale = 1.0 + ((CLOCK_DRIFT_PPM * node_id) / 1_000_000.0)
        nodes[node_id] = MockNode(node_id=node_id, boot_id=1000 + node_id, clock_scale=drift_scale)

    start = time.monotonic()
    next_render_at = start
    last_mode = None

    try:
        while (time.monotonic() - start) < RUN_SECONDS:
            frame_start = time.monotonic()
            elapsed = frame_start - start
            activity_mode = get_activity_mode(elapsed)
            if activity_mode != last_mode:
                print(f"\n[MOCK] Activity switched to: {activity_mode.upper()}\n")
                last_mode = activity_mode

            hub_time_us = int(round(elapsed * 1_000_000))
            superframe_id = int(hub_time_us // int(SUPERFRAME_SECONDS * 1_000_000))
            sync_packet = pack_sync(
                superframe_id,
                hub_time_us,
                {node_id: hub.node_states[node_id].next_seq_expected for node_id in active_nodes},
            )
            sync_info = decode_packet(sync_packet)
            ack_map = sync_info["next_seq_expected"]

            for node_id in active_nodes:
                node = nodes[node_id]
                node.apply_ack(ack_map[node_id])
                node.generate_until(hub_time_us, activity_mode, JITTER_MS)

                hello_packet = node.next_hello_packet()
                if hello_packet is not None:
                    hub.handle_packet(hello_packet, addr=(f"mock-node-{node_id}", 39001))

                if node_in_outage(node_id, elapsed):
                    continue
                if random.random() < DROP_RATE:
                    continue

                data_packet = node.next_data_packet()
                if data_packet is not None:
                    hub.handle_packet(data_packet, addr=(f"mock-node-{node_id}", 39001))

            now = time.monotonic()
            hub.refresh_states(now)
            hub.maybe_emit_streaming_status(now)
            hub.maybe_predict(
                lambda selected_nodes, windows: predict_combined_window(selected_nodes, windows, activity_mode),
                now,
            )

            if now >= next_render_at:
                print_table(hub, active_nodes, activity_mode, elapsed)
                next_render_at = now + RENDER_INTERVAL_SECONDS

            frame_end = frame_start + SUPERFRAME_SECONDS
            sleep_seconds = frame_end - time.monotonic()
            if sleep_seconds > 0:
                time.sleep(sleep_seconds)
    except KeyboardInterrupt:
        print("\nStopping mock Wi-Fi TDMA hub...")
    finally:
        for node_id in active_nodes:
            reporter(
                {
                    "id": node_id,
                    "isConnected": False,
                    "state": "disconnected",
                    "lastSeenMs": None,
                    "lastSeq": 0,
                    "missedPackets": 0,
                }
            )


if __name__ == "__main__":
    main()

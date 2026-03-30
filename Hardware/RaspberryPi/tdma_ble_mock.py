import json
import math
import os
import time

from tdma_ble_transport import (
    HELLO_FLAG_SYNC_LOCKED,
    PREDICT_MIN_INTERVAL_SECONDS,
    SAMPLE_PERIOD_US,
    SUPERFRAME_SECONDS,
    SoftTDMAHub,
    pack_data,
    pack_hello,
)

BACKEND_URL = os.getenv("HAR_BACKEND_URL", "http://127.0.0.1:3000")
SEND_TO_BACKEND = os.getenv("MOCK_SEND_TO_BACKEND", "1") == "1"
NODE_IDS = [1, 2, 3, 4, 5, 6, 7]
RUN_SECONDS = float(os.getenv("MOCK_RUN_SECONDS", "99999"))
ACTIVITY_SWITCH_SECONDS = float(os.getenv("MOCK_ACTIVITY_SWITCH_SECONDS", "30"))

WALK_FREQ_HZ = 1.8
ACC_NOISE = 0.12
GYRO_NOISE = 0.08
STAND_ACC_NOISE = 0.015
STAND_GYRO_NOISE = 0.01


def clear_console():
    print("\n" * 40)


def choose_nodes():
    raw = os.getenv("MOCK_NODE_IDS", "")
    if not raw.strip():
        return list(NODE_IDS)
    chosen = []
    for part in raw.split(","):
        try:
            chosen.append(int(part.strip()))
        except ValueError:
            pass
    chosen = sorted(set(chosen))
    return chosen or list(NODE_IDS)


def compute_noise(node_id, step, channel_scale):
    return channel_scale * (
        math.sin(0.37 * step + node_id * 1.11)
        + 0.5 * math.cos(0.19 * step + node_id * 0.73)
    )


def get_activity_mode(elapsed_seconds):
    block = int(elapsed_seconds // ACTIVITY_SWITCH_SECONDS)
    return "walking" if (block % 2 == 0) else "standing"


def generate_walking_sample(node_id, step):
    t_seconds = step * (SAMPLE_PERIOD_US / 1_000_000.0)
    phase = node_id * 0.33
    w = 2.0 * math.pi * WALK_FREQ_HZ * t_seconds
    return {
        "ax": 1.4 * math.sin(w + phase) + compute_noise(node_id, step, ACC_NOISE),
        "ay": 0.6 * math.cos(w * 0.7 + phase * 0.5) + compute_noise(node_id, step + 3, ACC_NOISE * 0.7),
        "az": 9.8 + 0.9 * math.sin(w * 2.0 + phase * 0.25) + compute_noise(node_id, step + 7, ACC_NOISE * 0.5),
        "gx": 1.4 * math.cos(w + phase) + compute_noise(node_id, step + 11, GYRO_NOISE),
        "gy": 0.8 * math.sin(w * 1.2 + phase) + compute_noise(node_id, step + 17, GYRO_NOISE * 0.8),
        "gz": 0.5 * math.cos(w * 0.8 + phase * 0.8) + compute_noise(node_id, step + 23, GYRO_NOISE * 0.6),
    }


def generate_standing_sample(node_id, step):
    t_seconds = step * (SAMPLE_PERIOD_US / 1_000_000.0)
    phase = node_id * 0.17
    return {
        "ax": 0.03 * math.sin(0.25 * t_seconds + phase) + compute_noise(node_id, step, STAND_ACC_NOISE),
        "ay": 0.03 * math.cos(0.21 * t_seconds + phase) + compute_noise(node_id, step + 5, STAND_ACC_NOISE),
        "az": 9.8 + 0.05 * math.sin(0.18 * t_seconds + phase) + compute_noise(node_id, step + 9, STAND_ACC_NOISE),
        "gx": 0.015 * math.sin(0.30 * t_seconds + phase) + compute_noise(node_id, step + 13, STAND_GYRO_NOISE),
        "gy": 0.015 * math.cos(0.27 * t_seconds + phase) + compute_noise(node_id, step + 17, STAND_GYRO_NOISE),
        "gz": 0.012 * math.sin(0.22 * t_seconds + phase) + compute_noise(node_id, step + 21, STAND_GYRO_NOISE),
    }


def generate_mock_sample(node_id, step, activity_mode):
    if activity_mode == "standing":
        return generate_standing_sample(node_id, step)
    return generate_walking_sample(node_id, step)


def backend_post(path, payload, timeout=1.0):
    if not SEND_TO_BACKEND:
        if path == "/predict":
            return True, {
                "activity": payload.get("mock_activity_mode", "walking"),
                "confidence": 0.98,
                "used_node_ids": payload.get("node_ids", []),
                "mock": True,
            }
        return True, {"ok": True, "mock": True}

    from urllib import error, request

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
            return True, json.loads(raw)
    except error.HTTPError as exc:
        return False, exc.read().decode("utf-8", errors="ignore")
    except error.URLError as exc:
        return False, str(exc)
    except Exception as exc:
        return False, str(exc)


def predict_combined_window(active_nodes, node_windows, activity_mode):
    payload = {
        "node_ids": list(active_nodes),
        "windows_by_node": {str(node_id): rows for node_id, rows in node_windows.items()},
        "mock_activity_mode": activity_mode,
    }
    ok, result = backend_post("/predict", payload, timeout=2.5)
    if ok:
        print(
            f"[PREDICT] Generated={activity_mode} | Predicted={result.get('activity')} "
            f"({result.get('confidence')})"
        )
    else:
        print(f"[PREDICT] Prediction failed: {result}")
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
    print("===== TDMA Sensor Dashboard (BLE MOCK INPUT / REAL PREDICTION) =====")
    print(
        f"Generated mock activity : {activity_mode.upper()} | "
        f"Predicted: {hub.prediction_state.get('label')} ({hub.prediction_state.get('confidence')})"
    )
    print(
        f"Superframe={SUPERFRAME_SECONDS:.3f}s | predict interval={PREDICT_MIN_INTERVAL_SECONDS:.1f}s | "
        f"elapsed={elapsed_seconds:.1f}s"
    )
    print()

    header = "Node | State        | Seq    | Miss | MILLISEC |  accX    accY    accZ  |  gyroX   gyroY   gyroZ"
    print(header)
    print("-" * len(header))

    latest = hub.latest_table_rows()
    for snapshot in hub.status_snapshots():
        node_id = snapshot["id"]
        if node_id not in active_nodes:
            continue
        data = latest.get(node_id)
        if data is None:
            print(
                f"  {node_id:2d} | {snapshot['state']:<12} | {snapshot['lastSeq']:6d} | "
                f"{snapshot['missedPackets']:4d} |   ---   |   ---    ---    --- |   ---    ---    ---"
            )
            continue
        t_ms, ax_mg, ay_mg, az_mg, gx_milli, gy_milli, gz_milli = scientific_row(data)
        print(
            f"  {node_id:2d} | {snapshot['state']:<12} | {snapshot['lastSeq']:6d} | "
            f"{snapshot['missedPackets']:4d} | {t_ms:7d} | {ax_mg:6d} {ay_mg:6d} {az_mg:6d} | "
            f"{gx_milli:6d} {gy_milli:6d} {gz_milli:6d}"
        )


def main():
    active_nodes = choose_nodes()
    hub = SoftTDMAHub(active_nodes, transport_name="ble")
    print(f"Using BLE mock nodes: {active_nodes}")
    print(f"Backend mode: {'REAL' if SEND_TO_BACKEND else 'DRY RUN / MOCK'}")

    start = time.monotonic()
    last_superframe_at = start
    last_predict_at = 0.0
    seq_by_node = {node_id: 0 for node_id in active_nodes}
    step_by_node = {node_id: 0 for node_id in active_nodes}

    for node_id in active_nodes:
        hub.handle_packet(pack_hello(node_id, boot_id=1000 + node_id, flags=HELLO_FLAG_SYNC_LOCKED))

    try:
        while (time.monotonic() - start) < RUN_SECONDS:
            now = time.monotonic()
            elapsed = now - start
            activity_mode = get_activity_mode(elapsed)

            if (now - last_superframe_at) >= SUPERFRAME_SECONDS:
                last_superframe_at = now
                for node_id in active_nodes:
                    batch = []
                    batch_start_seq = seq_by_node[node_id]
                    first_sample_time_us = step_by_node[node_id] * SAMPLE_PERIOD_US
                    for _ in range(7):
                        batch.append(generate_mock_sample(node_id, step_by_node[node_id], activity_mode))
                        seq_by_node[node_id] += 1
                        step_by_node[node_id] += 1
                    hub.handle_packet(
                        pack_data(
                            node_id=node_id,
                            first_seq=batch_start_seq,
                            first_sample_time_us=first_sample_time_us,
                            samples=batch,
                        )
                    )

            hub.refresh_states(now)

            if (now - last_predict_at) >= PREDICT_MIN_INTERVAL_SECONDS:
                windows = hub.build_prediction_windows()
                if windows is not None:
                    ok, result = predict_combined_window(active_nodes, windows, activity_mode)
                    hub.record_prediction_result(ok, result, now)
                    last_predict_at = now

            print_table(hub, active_nodes, activity_mode, elapsed)
            time.sleep(0.05)
    except KeyboardInterrupt:
        print("\nStopping BLE mock TDMA hub...")


if __name__ == "__main__":
    main()

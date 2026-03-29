import os
import time
import json
import math
from collections import deque
from urllib import request, error

# -----------------------------------------------------------------------------
# Mock TDMA hub for testing the "all ESPs together" prediction flow.
#
# What it does:
# - simulates multiple ESP nodes without serial/Bluetooth hardware
# - keeps the same general flow as tdma_formatted.py
# - builds a 32-sample window for each node
# - sends ONE combined /predict request using windows_by_node
# - alternates activity every 30 seconds:
#       walking -> standing -> walking -> standing -> ...
#
# Default behavior:
# - sends to real backend if MOCK_SEND_TO_BACKEND=1
# - otherwise returns a fake response locally
# -----------------------------------------------------------------------------

NODE_IDS = [1, 2, 3, 4, 5, 6, 7]
FRAME_PERIOD = 0.28
WINDOW_SIZE = 32
PREDICT_MIN_INTERVAL_SECONDS = 1.0
BACKEND_URL = os.getenv("HAR_BACKEND_URL", "http://127.0.0.1:3000")
SEND_TO_BACKEND = os.getenv("MOCK_SEND_TO_BACKEND", "1") == "1"
RUN_SECONDS = float(os.getenv("MOCK_RUN_SECONDS", "99999"))
ACTIVITY_SWITCH_SECONDS = float(os.getenv("MOCK_ACTIVITY_SWITCH_SECONDS", "30"))

# Walking waveform parameters
WALK_FREQ_HZ = 1.8
GYRO_SCALE = 1.4
ACC_NOISE = 0.12
GYRO_NOISE = 0.08

# Standing waveform parameters
STAND_ACC_NOISE = 0.015
STAND_GYRO_NOISE = 0.01

ESP_CONNECTED_CACHE = {}


def clear_console():
    print("\n" * 40)


def compute_noise(node_id, step, channel_scale):
    # deterministic pseudo-noise so behavior is repeatable
    return channel_scale * (
        math.sin(0.37 * step + node_id * 1.11)
        + 0.5 * math.cos(0.19 * step + node_id * 0.73)
    )


def choose_nodes():
    raw = os.getenv("MOCK_NODE_IDS", "")
    if not raw.strip():
        return list(NODE_IDS)

    chosen = []
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        try:
            chosen.append(int(part))
        except ValueError:
            pass

    chosen = sorted(set(chosen))
    return chosen or list(NODE_IDS)


def backend_post(path, payload, timeout=1.0):
    if not SEND_TO_BACKEND:
        if path == "/predict":
            used = payload.get("node_ids", [])
            mode = payload.get("mock_activity_mode", "walking")

            # dry-run mode fake label follows current activity mode
            fake_label = "walking" if mode == "walking" else "standing"

            return True, {
                "activity": fake_label,
                "confidence": 0.97 if fake_label == "walking" else 0.99,
                "used_node_ids": used,
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
    except error.HTTPError as e:
        try:
            err_body = e.read().decode("utf-8", errors="ignore")
            try:
                return False, json.loads(err_body)
            except Exception:
                return False, err_body
        except Exception:
            return False, f"HTTP Error {e.code}: {e.reason}"
    except error.URLError as e:
        return False, str(e)
    except Exception as e:
        return False, str(e)


def report_esp_status(node_id, is_connected):
    prev = ESP_CONNECTED_CACHE.get(node_id)
    if prev is is_connected:
        return

    ok, result = backend_post(
        f"/esp-status/{node_id}",
        {"isConnected": bool(is_connected)},
        timeout=1.0,
    )
    if ok:
        ESP_CONNECTED_CACHE[node_id] = bool(is_connected)
        state = "connected" if is_connected else "disconnected"
        mode = "REAL" if SEND_TO_BACKEND else "MOCK"
        print(f"[{mode} BACKEND] Node {node_id} marked {state}")
    else:
        print(f"[BACKEND] Failed to update ESP status for node {node_id}: {result}")


def get_activity_mode(elapsed_seconds):
    block = int(elapsed_seconds // ACTIVITY_SWITCH_SECONDS)
    return "walking" if (block % 2 == 0) else "standing"


def generate_walking_sample(node_id, step):
    t_seconds = step * FRAME_PERIOD
    phase = node_id * 0.33
    w = 2.0 * math.pi * WALK_FREQ_HZ * t_seconds

    ax = 1.4 * math.sin(w + phase) + compute_noise(node_id, step, ACC_NOISE)
    ay = 0.6 * math.cos(w * 0.7 + phase * 0.5) + compute_noise(node_id, step + 3, ACC_NOISE * 0.7)
    az = 9.8 + 0.9 * math.sin(w * 2.0 + phase * 0.25) + compute_noise(node_id, step + 7, ACC_NOISE * 0.5)

    gx = GYRO_SCALE * math.cos(w + phase) + compute_noise(node_id, step + 11, GYRO_NOISE)
    gy = 0.8 * math.sin(w * 1.2 + phase) + compute_noise(node_id, step + 17, GYRO_NOISE * 0.8)
    gz = 0.5 * math.cos(w * 0.8 + phase * 0.8) + compute_noise(node_id, step + 23, GYRO_NOISE * 0.6)

    t_ms = int(round(t_seconds * 1000))
    return {
        "node_id": node_id,
        "t": t_ms,
        "ax": round(ax, 4),
        "ay": round(ay, 4),
        "az": round(az, 4),
        "gx": round(gx, 4),
        "gy": round(gy, 4),
        "gz": round(gz, 4),
    }


def generate_standing_sample(node_id, step):
    t_seconds = step * FRAME_PERIOD
    phase = node_id * 0.17

    # Nearly constant gravity, very small movement/noise
    ax = 0.03 * math.sin(0.25 * t_seconds + phase) + compute_noise(node_id, step, STAND_ACC_NOISE)
    ay = 0.03 * math.cos(0.21 * t_seconds + phase) + compute_noise(node_id, step + 5, STAND_ACC_NOISE)
    az = 9.8 + 0.05 * math.sin(0.18 * t_seconds + phase) + compute_noise(node_id, step + 9, STAND_ACC_NOISE)

    gx = 0.015 * math.sin(0.30 * t_seconds + phase) + compute_noise(node_id, step + 13, STAND_GYRO_NOISE)
    gy = 0.015 * math.cos(0.27 * t_seconds + phase) + compute_noise(node_id, step + 17, STAND_GYRO_NOISE)
    gz = 0.012 * math.sin(0.22 * t_seconds + phase) + compute_noise(node_id, step + 21, STAND_GYRO_NOISE)

    t_ms = int(round(t_seconds * 1000))
    return {
        "node_id": node_id,
        "t": t_ms,
        "ax": round(ax, 4),
        "ay": round(ay, 4),
        "az": round(az, 4),
        "gx": round(gx, 4),
        "gy": round(gy, 4),
        "gz": round(gz, 4),
    }


def generate_mock_sample(node_id, step, activity_mode):
    if activity_mode == "standing":
        return generate_standing_sample(node_id, step)
    return generate_walking_sample(node_id, step)


def predict_combined_window(active_nodes, node_windows, activity_mode, prediction_state):
    windows_by_node = {}
    for node_id in active_nodes:
        window = node_windows[node_id]
        if len(window) < WINDOW_SIZE:
            return False
        windows_by_node[str(node_id)] = list(window)

    payload = {
        "node_ids": active_nodes,
        "windows_by_node": windows_by_node,
    }

    ok, result = backend_post("/predict", payload, timeout=2.5)
    if ok:
        label = result.get("activity", "?")
        conf = result.get("confidence", "?")
        used_nodes = result.get("used_node_ids", active_nodes)
        suffix = " [mock backend]" if result.get("mock") else ""

        prediction_state["label"] = label
        prediction_state["confidence"] = conf
        prediction_state["used_nodes"] = used_nodes
        prediction_state["is_mock_label"] = bool(result.get("mock"))

        print(f"[PREDICT] Generated={activity_mode} | Predicted={label} ({conf}){suffix}")
    else:
        prediction_state["label"] = "ERROR"
        prediction_state["confidence"] = "-"
        prediction_state["used_nodes"] = active_nodes
        prediction_state["is_mock_label"] = False
        print(f"[PREDICT] Generated={activity_mode} | Prediction failed: {result}")

    return ok


def maybe_predict(active_nodes, parsed, node_windows, last_predict_at, activity_mode, prediction_state):
    node_id = parsed["node_id"]
    node_windows[node_id].append(
        {
            "ax": parsed["ax"],
            "ay": parsed["ay"],
            "az": parsed["az"],
            "gx": parsed["gx"],
            "gy": parsed["gy"],
            "gz": parsed["gz"],
        }
    )

    if any(len(node_windows[nid]) < WINDOW_SIZE for nid in active_nodes):
        return

    now = time.monotonic()
    last = last_predict_at.get("combined", 0.0)
    if (now - last) < PREDICT_MIN_INTERVAL_SECONDS:
        return

    if predict_combined_window(active_nodes, node_windows, activity_mode, prediction_state):
        last_predict_at["combined"] = now


def scientific_row(data):
    t_ms = int(data["t"])
    ax_mg = int(round(data["ax"] / 9.8 * 1000))
    ay_mg = int(round(data["ay"] / 9.8 * 1000))
    az_mg = int(round(data["az"] / 9.8 * 1000))
    gx_milli = int(round(data["gx"] * 1000))
    gy_milli = int(round(data["gy"] * 1000))
    gz_milli = int(round(data["gz"] * 1000))
    return t_ms, ax_mg, ay_mg, az_mg, gx_milli, gy_milli, gz_milli


def print_table(latest, active_nodes, activity_mode, elapsed_seconds, prediction_state):
    clear_console()
    print("===== TDMA Sensor Dashboard (MOCK INPUT / REAL PREDICTION) =====")
    print(f"Generated mock activity : {activity_mode.upper()}")

    predicted_label = prediction_state.get("label", "WAITING")
    predicted_conf = prediction_state.get("confidence", "-")
    is_mock_label = prediction_state.get("is_mock_label", False)

    source = "MOCK" if is_mock_label else "BACKEND"
    print(f"Predicted label        : {predicted_label} ({predicted_conf}) [{source}]")

    print(f"Elapsed seconds        : {elapsed_seconds:.1f}")
    print(f"Switch interval        : {ACTIVITY_SWITCH_SECONDS:.1f} sec")
    print()

    header = "Node | MILLISEC |  accX    accY    accZ  |  gyroX   gyroY   gyroZ"
    print(header)
    print("-" * len(header))

    for node_id in active_nodes:
        data = latest.get(node_id)
        if data is None:
            print(f"  {node_id:2d} |   ---   |   ---    ---    --- |   ---    ---    ---")
        else:
            t_ms, ax_mg, ay_mg, az_mg, gx_milli, gy_milli, gz_milli = scientific_row(data)
            print(
                f"  {node_id:2d} | {t_ms:7d} | {ax_mg:6d} {ay_mg:6d} {az_mg:6d} | {gx_milli:6d} {gy_milli:6d} {gz_milli:6d}"
            )


def main():
    active_nodes = choose_nodes()
    print(f"Using mock nodes: {active_nodes}")
    print(f"Backend mode: {'REAL' if SEND_TO_BACKEND else 'DRY RUN / MOCK'}")
    print(f"Activity switches every {ACTIVITY_SWITCH_SECONDS} seconds")
    print(f"Run duration: {RUN_SECONDS} seconds")

    latest = {}
    node_windows = {nid: deque(maxlen=WINDOW_SIZE) for nid in active_nodes}
    last_predict_at = {"combined": 0.0}
    prediction_state = {
      "label": "WAITING",
      "confidence": "-",
      "used_nodes": [],
      "is_mock_label": False,
    }

    for nid in active_nodes:
        report_esp_status(nid, True)

    start = time.monotonic()
    step = 0
    last_mode = None

    try:
        while (time.monotonic() - start) < RUN_SECONDS:
            frame_start = time.perf_counter()
            elapsed = time.monotonic() - start
            activity_mode = get_activity_mode(elapsed)

            if activity_mode != last_mode:
                print(f"\n[MOCK] Activity switched to: {activity_mode.upper()}\n")
                last_mode = activity_mode

            for node_id in active_nodes:
                parsed = generate_mock_sample(node_id, step, activity_mode)
                latest[node_id] = parsed
                maybe_predict(active_nodes, parsed, node_windows, last_predict_at, activity_mode, prediction_state)

            print_table(latest, active_nodes, activity_mode, elapsed, prediction_state)
            step += 1

            now = time.perf_counter()
            frame_end = frame_start + FRAME_PERIOD
            if now < frame_end:
                time.sleep(frame_end - now)

    except KeyboardInterrupt:
        print("\nStopping mock TDMA hub...")
    finally:
        for nid in active_nodes:
            report_esp_status(nid, False)


if __name__ == "__main__":
    main()
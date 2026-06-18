import os
import time
import json
import math
from collections import deque
from urllib import request, error

# ============================================================
# Mock TDMA Hub
# 3-Node PAMAP2-Based Activity Recognition Test
#
# This file generates mock IMU sensor to test model.
# ============================================================

NODE_IDS = [1, 2, 3]

NODE_NAMES = {
    1: "wrist",
    2: "chest",
    3: "ankle",
}

WINDOW_SIZE = 200
PREDICT_EVERY = 20
FRAME_PERIOD = 0.01

BACKEND_URL = os.getenv("HAR_BACKEND_URL", "http://127.0.0.1:3000")
RUN_SECONDS = float(os.getenv("MOCK_RUN_SECONDS", "99999"))

ESP_CONNECTED_CACHE = {}


def clear_console():
    print("\n" * 40)


# ============================================================
# Backend Communication
# ============================================================

def backend_post(path, payload, timeout=5.0):
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
            raw = e.read().decode("utf-8", errors="ignore")
            try:
                return False, json.loads(raw) if raw else {}
            except Exception:
                return False, raw
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
        print(f"[BACKEND] Node {node_id} marked {state}")
    else:
        print(f"[BACKEND] Failed to update ESP status for node {node_id}: {result}")


# ============================================================
# Mock Data Generation
# ============================================================

def small_noise(node_id, step, scale):
    return scale * (
        math.sin(0.031 * step + node_id * 0.71)
        + 0.5 * math.cos(0.017 * step + node_id * 1.13)
    )


def generate_lying_sample(node_id, step):
    """
    Generates lying data using a real PAMAP2 activity_id = 1 frame
    as baseline, while keeping small synthetic noise.
    """

    t_ms = int(round(step * FRAME_PERIOD * 1000))

    if node_id == 1:  # wrist / hand
        base_ax, base_ay, base_az = 3.72596, -3.96060, -8.24250
        base_gx, base_gy, base_gz = -0.00507522, 0.00820694, -0.0146042
        base_mx, base_my, base_mz = 20.0353, 52.0082, 29.7961

    elif node_id == 2:  # chest
        base_ax, base_ay, base_az = 9.06493, 3.82318, -1.50962
        base_gx, base_gy, base_gz = -0.0117584, -0.00514985, -0.0405058
        base_mx, base_my, base_mz = -40.6677, -4.86343, -42.5858

    else:  # ankle
        base_ax, base_ay, base_az = -1.33751, 2.25156, -9.88421
        base_gx, base_gy, base_gz = 0.0592152, -0.00101313, 0.0257830
        base_mx, base_my, base_mz = -21.4566, 20.0167, 40.5645

    ax = base_ax + small_noise(node_id, step, 0.025)
    ay = base_ay + small_noise(node_id, step + 7, 0.025)
    az = base_az + small_noise(node_id, step + 13, 0.035)

    gx = base_gx + small_noise(node_id, step + 19, 0.004)
    gy = base_gy + small_noise(node_id, step + 23, 0.004)
    gz = base_gz + small_noise(node_id, step + 29, 0.004)

    mx = base_mx + small_noise(node_id, step + 31, 0.15)
    my = base_my + small_noise(node_id, step + 37, 0.15)
    mz = base_mz + small_noise(node_id, step + 41, 0.15)

    return {
        "node_id": node_id,
        "t": t_ms,
        "ax": round(ax, 4),
        "ay": round(ay, 4),
        "az": round(az, 4),
        "gx": round(gx, 5),
        "gy": round(gy, 5),
        "gz": round(gz, 5),
        "mx": round(mx, 4),
        "my": round(my, 4),
        "mz": round(mz, 4),
    }

def generate_sitting_sample(node_id, step):
    """
    Generates sitting data using a real PAMAP2 activity_id = 2 frame
    as baseline, while keeping small synthetic noise.
    """

    t_ms = int(round(step * FRAME_PERIOD * 1000))

    if node_id == 1:  # wrist / hand
        base_ax, base_ay, base_az = 1.10390, 8.17010, 5.14789
        base_gx, base_gy, base_gz = 0.00161208, 0.0312746, -0.0313198
        base_mx, base_my, base_mz = -37.9553, -14.2363, -49.1807

    elif node_id == 2:  # chest
        base_ax, base_ay, base_az = 0.764927, 9.70145, 0.682878
        base_gx, base_gy, base_gz = -0.00445911, 0.0293547, -0.00818763
        base_mx, base_my, base_mz = 11.8492, -61.4718, -43.7041

    else:  # ankle
        base_ax, base_ay, base_az = 8.42614, 2.56652, -4.76939
        base_gx, base_gy, base_gz = 0.0165592, -0.00130253, 0.00912554
        base_mx, base_my, base_mz = -79.7468, 22.8792, 29.5603

    ax = base_ax + small_noise(node_id, step, 0.025)
    ay = base_ay + small_noise(node_id, step + 7, 0.025)
    az = base_az + small_noise(node_id, step + 13, 0.035)

    gx = base_gx + small_noise(node_id, step + 19, 0.004)
    gy = base_gy + small_noise(node_id, step + 23, 0.004)
    gz = base_gz + small_noise(node_id, step + 29, 0.004)

    mx = base_mx + small_noise(node_id, step + 31, 0.15)
    my = base_my + small_noise(node_id, step + 37, 0.15)
    mz = base_mz + small_noise(node_id, step + 41, 0.15)

    return {
        "node_id": node_id,
        "t": t_ms,
        "ax": round(ax, 4),
        "ay": round(ay, 4),
        "az": round(az, 4),
        "gx": round(gx, 5),
        "gy": round(gy, 5),
        "gz": round(gz, 5),
        "mx": round(mx, 4),
        "my": round(my, 4),
        "mz": round(mz, 4),
    }

def generate_standing_sample(node_id, step):
    """
    Generates standing data using a real PAMAP2 activity_id = 3 frame
    as baseline, while keeping small synthetic noise.
    """

    t_ms = int(round(step * FRAME_PERIOD * 1000))

    if node_id == 1:  # wrist / hand
        base_ax, base_ay, base_az = -7.86721, 3.89851, 3.29599
        base_gx, base_gy, base_gz = -0.612009, 0.129754, 0.0198302
        base_mx, base_my, base_mz = 67.3496, -28.0015, 13.1157

    elif node_id == 2:  # chest
        base_ax, base_ay, base_az = 0.544786, 9.61133, -1.60535
        base_gx, base_gy, base_gz = -0.139862, 0.102807, -0.109782
        base_mx, base_my, base_mz = -32.2691, -50.5239, 32.0073

    else:  # ankle
        base_ax, base_ay, base_az = 9.80775, -2.72104, 0.0626966
        base_gx, base_gy, base_gz = -0.77064, -0.147612, 0.736703
        base_mx, base_my, base_mz = -97.7765, -30.7244, 34.8298

    ax = base_ax + small_noise(node_id, step, 0.025)
    ay = base_ay + small_noise(node_id, step + 7, 0.025)
    az = base_az + small_noise(node_id, step + 13, 0.035)

    gx = base_gx + small_noise(node_id, step + 19, 0.004)
    gy = base_gy + small_noise(node_id, step + 23, 0.004)
    gz = base_gz + small_noise(node_id, step + 29, 0.004)

    mx = base_mx + small_noise(node_id, step + 31, 0.15)
    my = base_my + small_noise(node_id, step + 37, 0.15)
    mz = base_mz + small_noise(node_id, step + 41, 0.15)

    return {
        "node_id": node_id,
        "t": t_ms,
        "ax": round(ax, 4),
        "ay": round(ay, 4),
        "az": round(az, 4),
        "gx": round(gx, 5),
        "gy": round(gy, 5),
        "gz": round(gz, 5),
        "mx": round(mx, 4),
        "my": round(my, 4),
        "mz": round(mz, 4),
    }


# ============================================================
# Window Building
# ============================================================

def append_to_node_window(parsed, node_windows):
    node_id = parsed["node_id"]

    node_windows[node_id].append({
        "ax": parsed["ax"],
        "ay": parsed["ay"],
        "az": parsed["az"],
        "gx": parsed["gx"],
        "gy": parsed["gy"],
        "gz": parsed["gz"],
        "mx": parsed["mx"],
        "my": parsed["my"],
        "mz": parsed["mz"],
    })


def all_windows_ready(active_nodes, node_windows):
    return all(len(node_windows[nid]) >= WINDOW_SIZE for nid in active_nodes)


# ============================================================
# HAR Prediction
# ============================================================

def predict_combined_window(active_nodes, node_windows, prediction_state):
    if not all_windows_ready(active_nodes, node_windows):
        return False

    windows_by_node = {
        str(node_id): list(node_windows[node_id])
        for node_id in active_nodes
    }

    payload = {
        "node_ids": active_nodes,
        "windows_by_node": windows_by_node,
    }

    ok, result = backend_post("/predict", payload, timeout=5.0)

    if ok:
        label = (
            result.get("activity")
            or result.get("predicted_label")
            or result.get("label")
            or "unknown"
        )

        confidence = result.get("confidence", "?")
        used_nodes = result.get("used_node_ids", active_nodes)

        prediction_state["label"] = label
        prediction_state["confidence"] = confidence
        prediction_state["used_nodes"] = used_nodes

        print(f"[PREDICT] Predicted={label} ({confidence})")

    else:
        prediction_state["label"] = "ERROR"
        prediction_state["confidence"] = "-"
        prediction_state["used_nodes"] = active_nodes

        print(f"[PREDICT] Prediction failed: {result}")

    return ok


# ============================================================
# Console Dashboard
# ============================================================

def print_table(latest, active_nodes, elapsed_seconds, prediction_state, window_len, source_mode):
    clear_console()

    print("===== TDMA Sensor Dashboard (MOCK SENSOR INPUT / REAL MODEL PREDICTION) =====")
    print("Node 1 = Wrist / Hand")
    print("Node 2 = Chest")
    print("Node 3 = Ankle")
    print()

    predicted_label = prediction_state.get("label", "WAITING")
    predicted_conf = prediction_state.get("confidence", "-")

    print(f"Mock source     : {source_mode} (switches every 10s)")
    print(f"Predicted label : {predicted_label} ({predicted_conf})")
    print(f"Elapsed seconds : {elapsed_seconds:.1f}")
    print(f"Window          : {window_len}/{WINDOW_SIZE}")
    print()

    header = "Node | Place | t(ms)  |  ax      ay      az   |  gx      gy      gz   |  mx      my      mz"
    print(header)
    print("-" * len(header))

    for node_id in active_nodes:
        data = latest.get(node_id)

        if data is None:
            print(
                f"{node_id:4d} | {NODE_NAMES[node_id]:5s} |  ---   |"
                f"   ---    ---    --- |"
                f"   ---    ---    --- |"
                f"   ---    ---    ---"
            )
        else:
            print(
                f"{node_id:4d} | {NODE_NAMES[node_id]:5s} | {data['t']:6d} | "
                f"{data['ax']:6.2f} {data['ay']:6.2f} {data['az']:6.2f} | "
                f"{data['gx']:6.3f} {data['gy']:6.3f} {data['gz']:6.3f} | "
                f"{data['mx']:6.2f} {data['my']:6.2f} {data['mz']:6.2f}"
            )

# ============================================================
# Cycle source every 10 seconds: lying -> sitting -> standing 
# ============================================================

SAMPLE_MODES = [
    ("lying", generate_lying_sample),
    ("sitting", generate_sitting_sample),
    ("standing", generate_standing_sample),
]


# ============================================================
# Main Mock Runtime Loop
# ============================================================

def main():
    active_nodes = NODE_IDS

    print("Using mock 3-node PAMAP2 layout:")
    print("1 = Wrist / Hand")
    print("2 = Chest")
    print("3 = Ankle")
    print(f"Backend URL: {BACKEND_URL}")
    print(f"Run duration: {RUN_SECONDS} seconds")
    print()

    latest = {}

    node_windows = {
        node_id: deque(maxlen=WINDOW_SIZE)
        for node_id in active_nodes
    }

    prediction_state = {
        "label": "WAITING",
        "confidence": "-",
        "used_nodes": [],
    }

    rows_since_prediction = 0

    for node_id in active_nodes:
        report_esp_status(node_id, True)

    start = time.monotonic()
    step = 0

    try:
        while (time.monotonic() - start) < RUN_SECONDS:
            frame_start = time.perf_counter()
            elapsed = time.monotonic() - start

            mode_idx = int(elapsed // 10) % len(SAMPLE_MODES)
            mode_name, mode_fn = SAMPLE_MODES[mode_idx]

            for node_id in active_nodes:
                parsed = mode_fn(node_id, step)
                latest[node_id] = parsed
                append_to_node_window(parsed, node_windows)

            if all_windows_ready(active_nodes, node_windows):
                rows_since_prediction += 1

            if all_windows_ready(active_nodes, node_windows) and rows_since_prediction >= PREDICT_EVERY:
                predict_combined_window(active_nodes, node_windows, prediction_state)
                rows_since_prediction = 0

            window_len = min(len(node_windows[nid]) for nid in active_nodes)

            print_table(
                latest,
                active_nodes,
                elapsed,
                prediction_state,
                window_len,
                mode_name,
            )

            step += 1

            frame_end = frame_start + FRAME_PERIOD
            now = time.perf_counter()

            if now < frame_end:
                time.sleep(frame_end - now)

    except KeyboardInterrupt:
        print("\nStopping mock TDMA hub...")

    finally:
        for node_id in active_nodes:
            report_esp_status(node_id, False)


if __name__ == "__main__":
    main()

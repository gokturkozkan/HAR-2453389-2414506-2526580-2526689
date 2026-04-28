import json
import os
import time
import urllib.error
import urllib.request
from collections import deque

import serial

NODE_PORTS = {
    1: "/dev/rfcomm0",  # Wrist / hand
    2: "/dev/rfcomm1",  # Chest
    3: "/dev/rfcomm2",  # Ankle
}

NODE_NAMES = {
    1: "wrist",
    2: "chest",
    3: "ankle",
}

BAUDRATE = 115200
TIMEOUT = 0.05
FRAME_PERIOD = 0.30

WARMUP_SECONDS = 60.0
POLL_SLEEP = 0.03

EARLY_EIO_WINDOW = 2.0
EARLY_EIO_RETRY_DELAY = 0.25

BACKOFF_BASE = 0.5
BACKOFF_MAX = 10.0
RESET_ERRORS_AFTER_OK_SECONDS = 5.0

# PAMAP2 training used 100Hz, 2 seconds = 200 samples
WINDOW_SIZE = 200
PREDICT_EVERY = 20

FEATURE_KEYS = ("ax", "ay", "az", "gx", "gy", "gz", "mx", "my", "mz")
REQUIRE_ALL_NODES_FOR_FUSION = True

PREDICT_URL = os.getenv("HAR_PREDICT_URL", "http://127.0.0.1:3000/predict")

# ============================================================
# Serial Connection Utilities
# ============================================================

def compute_backoff(errors):
    delay = BACKOFF_BASE * (2 ** min(max(0, int(errors)), 6))
    return min(delay, BACKOFF_MAX)


def close_one(ser):
    try:
        if ser is not None and getattr(ser, "is_open", False):
            ser.close()
    except Exception:
        pass


def open_one(node_id):
    port = NODE_PORTS[node_id]
    try:
        ser = serial.Serial(port, BAUDRATE, timeout=TIMEOUT, write_timeout=TIMEOUT)
        time.sleep(0.15)
        try:
            ser.reset_input_buffer()
            ser.reset_output_buffer()
        except Exception:
            pass
        return ser
    except Exception:
        return None

# ============================================================
# Node Health / Auto Reconnect Logic
# ============================================================

def make_health(active_nodes):
    now = time.monotonic()
    return {
        nid: {
            "errors": 0,
            "next_try": now,
            "last_ok": 0.0,
            "opened_at": 0.0,
        }
        for nid in active_nodes
    }


def mark_ok(node_id, health):
    h = health[node_id]
    now = time.monotonic()

    if h["last_ok"] and (now - h["last_ok"]) > RESET_ERRORS_AFTER_OK_SECONDS:
        h["errors"] = 0

    h["last_ok"] = now
    h["next_try"] = now


def mark_error(node_id, serials, health, early=False):
    h = health[node_id]
    now = time.monotonic()

    if early:
        h["next_try"] = now + EARLY_EIO_RETRY_DELAY
    else:
        h["errors"] += 1
        h["next_try"] = now + compute_backoff(h["errors"])

    close_one(serials.get(node_id))
    serials[node_id] = None
    h["opened_at"] = 0.0


def try_reconnect(node_id, serials, health):
    now = time.monotonic()
    h = health[node_id]

    if now < h["next_try"]:
        return False

    ser = serials.get(node_id)
    if ser is not None and getattr(ser, "is_open", False):
        return True

    ser = open_one(node_id)

    if ser is None:
        mark_error(node_id, serials, health, early=False)
        return False

    serials[node_id] = ser
    h["opened_at"] = now
    h["next_try"] = now
    return True

# ============================================================
# TDMA Sensor Polling / Sample Requests
# ============================================================

def request_sample(node_id, serials, health):
    if not try_reconnect(node_id, serials, health):
        return ""

    ser = serials.get(node_id)

    if ser is None or not getattr(ser, "is_open", False):
        return ""

    h = health[node_id]

    try:
        ser.write(b"R")
        line = ser.readline().decode(errors="ignore").strip()

        if line:
            mark_ok(node_id, health)

        return line

    except (OSError, serial.SerialException) as e:
        now = time.monotonic()
        early = (now - h["opened_at"]) <= EARLY_EIO_WINDOW

        if isinstance(e, OSError) and getattr(e, "errno", None) == 5 and early:
            mark_error(node_id, serials, health, early=True)
        else:
            mark_error(node_id, serials, health, early=False)

        return ""

# ============================================================
# Sensor Data Parsing
# ============================================================

def parse_frame(line):
    """
    Expected ESP format:

    node_id,t,ax,ay,az,gx,gy,gz,mx,my,mz

    If your ESP currently sends only:
    node_id,t,ax,ay,az,gx,gy,gz

    then mx/my/mz are filled as 0.0.
    But for best PAMAP2 compatibility, send magnetometer too.
    """
    try:
        parts = line.split(",")

        if len(parts) < 8:
            return None

        node_id = int(parts[0])

        if node_id not in NODE_PORTS:
            return None

        t = int(parts[1])

        ax, ay, az = map(float, parts[2:5])
        gx, gy, gz = map(float, parts[5:8])

        mx = float(parts[8]) if len(parts) > 8 else 0.0
        my = float(parts[9]) if len(parts) > 9 else 0.0
        mz = float(parts[10]) if len(parts) > 10 else 0.0

        return {
            "node_id": node_id,
            "t": t,
            "ax": ax,
            "ay": ay,
            "az": az,
            "gx": gx,
            "gy": gy,
            "gz": gz,
            "mx": mx,
            "my": my,
            "mz": mz,
        }

    except Exception:
        return None

# ============================================================
# Multi-Node Feature Fusion
# Combines Wrist + Chest + Ankle into one timestep
# ============================================================

def build_fused_timestep(active_nodes, latest):
    timestep = {"nodes": {}}

    for node_id in active_nodes:
        sample = latest.get(node_id)

        if sample is None:
            if REQUIRE_ALL_NODES_FOR_FUSION:
                return None

            timestep["nodes"][str(node_id)] = {key: 0.0 for key in FEATURE_KEYS}
            continue

        timestep["nodes"][str(node_id)] = {
            key: sample[key]
            for key in FEATURE_KEYS
        }

    return timestep

# ============================================================
# HAR Model Prediction API
# Sends window to backend model in /model
# ============================================================

def post_predict(window_payload):
    payload = {
        "node_ids": [1, 2, 3],
        "windows_by_node": {
            "1": [],
            "2": [],
            "3": [],
        },
        "model_path": "model/pamap2_basic_har_model.keras",
        "scaler_path": "model/pamap2_basic_scaler.pkl",
        "label_encoder_path": "model/pamap2_basic_label_encoder.pkl",
    }

    for timestep in window_payload:
        nodes = timestep["nodes"]

        for node_id in ["1", "2", "3"]:
            payload["windows_by_node"][node_id].append(nodes[node_id])

    body = json.dumps(payload).encode("utf-8")

    req = urllib.request.Request(
        PREDICT_URL,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=5.0) as response:
            raw = response.read().decode("utf-8", errors="ignore")
            return json.loads(raw) if raw else {}, None

    except urllib.error.URLError as exc:
        return None, str(exc)

    except Exception as exc:
        return None, str(exc)

# ============================================================
# Console Dashboard Output
# ============================================================

def print_table(latest, active_nodes, health, fused_window_len, last_prediction):
    os.system("clear")

    print("===== TDMA HAR Dashboard - 3 Node PAMAP2 Setup =====")
    print("Node 1 = Wrist / Hand")
    print("Node 2 = Chest")
    print("Node 3 = Ankle")
    print()
    print(f"Fused window: {fused_window_len}/{WINDOW_SIZE}")
    print(f"Last prediction: {last_prediction}")
    print()

    header = "Node | Place | t(ms)  |  ax      ay      az   |  gx      gy      gz   |  mx      my      mz   | err | wait"
    print(header)
    print("-" * len(header))

    now = time.monotonic()

    for node_id in active_nodes:
        data = latest.get(node_id)
        h = health[node_id]
        wait = max(0.0, h["next_try"] - now)

        if data is None:
            print(
                f"{node_id:4d} | {NODE_NAMES[node_id]:5s} |  ---   |"
                f"   ---    ---    --- |"
                f"   ---    ---    --- |"
                f"   ---    ---    --- |"
                f" {h['errors']:3d} | {wait:4.1f}s"
            )
        else:
            print(
                f"{node_id:4d} | {NODE_NAMES[node_id]:5s} | {data['t']:6d} | "
                f"{data['ax']:6.2f} {data['ay']:6.2f} {data['az']:6.2f} | "
                f"{data['gx']:6.2f} {data['gy']:6.2f} {data['gz']:6.2f} | "
                f"{data['mx']:6.2f} {data['my']:6.2f} {data['mz']:6.2f} | "
                f"{h['errors']:3d} | {wait:4.1f}s"
            )

# ============================================================
# Initial Warmup Phase
# Waits for first samples from all nodes
# ============================================================

def warmup(active_nodes, serials, latest, health):
    print("\nWaiting for initial data from wrist, chest, and ankle...")
    deadline = time.monotonic() + WARMUP_SECONDS
    got = set()

    while time.monotonic() < deadline and len(got) < len(active_nodes):
        for node_id in active_nodes:
            if node_id in got:
                continue

            line = request_sample(node_id, serials, health)
            parsed = parse_frame(line)

            if parsed is not None and parsed["node_id"] == node_id:
                latest[node_id] = parsed
                got.add(node_id)
                print(f"  Node {node_id} ({NODE_NAMES[node_id]}): first sample received.")

        time.sleep(POLL_SLEEP)

    missing = [node_id for node_id in active_nodes if node_id not in got]

    if missing:
        print(f"[WARN] No initial data from nodes: {missing}")

    print("Starting main loop...\n")
    time.sleep(0.5)

# ============================================================
# Main TDMA Runtime Loop
# Poll nodes -> Build window -> Predict -> Display
# ============================================================

def main():
    active_nodes = [1, 2, 3]

    print("Using fixed 3-node PAMAP2 layout:")
    print("1 = Wrist / Hand")
    print("2 = Chest")
    print("3 = Ankle")

    serials = {node_id: None for node_id in active_nodes}
    health = make_health(active_nodes)
    latest = {}

    fused_window = deque(maxlen=WINDOW_SIZE)
    rows_since_prediction = 0
    last_prediction = "WAITING"

    for node_id in active_nodes:
        try_reconnect(node_id, serials, health)
        time.sleep(0.05)

    warmup(active_nodes, serials, latest, health)

    try:
        while True:
            frame_start = time.perf_counter()

            slot_period = FRAME_PERIOD / len(active_nodes)

            for slot_index, node_id in enumerate(active_nodes):
                slot_start = frame_start + slot_index * slot_period
                now = time.perf_counter()

                if now < slot_start:
                    time.sleep(slot_start - now)

                line = request_sample(node_id, serials, health)

                if not line:
                    continue

                parsed = parse_frame(line)

                if parsed is not None and parsed["node_id"] == node_id:
                    latest[node_id] = parsed

            fused_timestep = build_fused_timestep(active_nodes, latest)

            if fused_timestep is not None:
                fused_window.append(fused_timestep)
                rows_since_prediction += 1

            if len(fused_window) == WINDOW_SIZE and rows_since_prediction >= PREDICT_EVERY:
                response, err = post_predict(list(fused_window))
                rows_since_prediction = 0

                if err:
                    last_prediction = f"predict error: {err}"
                else:
                    activity = (
                        response.get("activity")
                        or response.get("predicted_label")
                        or response.get("label")
                        or "unknown"
                    )

                    confidence = response.get("confidence", None)

                    if confidence is not None:
                        last_prediction = f"{activity} ({confidence})"
                    else:
                        last_prediction = activity

            now = time.perf_counter()
            frame_end = frame_start + FRAME_PERIOD

            if now < frame_end:
                time.sleep(frame_end - now)

            print_table(
                latest,
                active_nodes,
                health,
                len(fused_window),
                last_prediction
            )

    except KeyboardInterrupt:
        print("\nStopping TDMA hub...")

    finally:
        for ser in serials.values():
            close_one(ser)


if __name__ == "__main__":
    main()
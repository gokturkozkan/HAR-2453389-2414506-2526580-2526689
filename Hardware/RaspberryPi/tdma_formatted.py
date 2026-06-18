import serial
import time
import os
import json
from collections import deque
from urllib import request, error

# ============================================================
# 3 NODE PAMAP2 SYSTEM
# Node 1 = Wrist / Hand
# Node 2 = Chest
# Node 3 = Ankle
# ============================================================

NODE_PORTS = {
    1: "/dev/rfcomm0",
    2: "/dev/rfcomm1",
    3: "/dev/rfcomm2",
}

BAUDRATE = 115200
TIMEOUT = 0.05
FRAME_PERIOD = 0.30

MAX_WAIT_PER_NODE = 25.0

BACKEND_URL = os.getenv("HAR_BACKEND_URL", "http://127.0.0.1:3000")

# Restored PAMAP2 Keras model profile.
WINDOW_SIZE = 200

PREDICT_MIN_INTERVAL_SECONDS = 1.0

ESP_CONNECTED_CACHE = {}

# ============================================================
# Utility
# ============================================================

def clear_console():
    print("\n" * 40)


def close_one(ser):
    try:
        if ser and ser.is_open:
            ser.close()
    except:
        pass


# ============================================================
# Backend API
# ============================================================

def backend_post(path, payload, timeout=3.0):
    url = f"{BACKEND_URL}{path}"

    body = json.dumps(payload).encode("utf-8")

    req = request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST"
    )

    try:
        with request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8")

            if raw:
                try:
                    return True, json.loads(raw)
                except:
                    return True, {"raw": raw}

            return True, {}

    except Exception as e:
        return False, str(e)


def report_esp_status(node_id, is_connected):
    prev = ESP_CONNECTED_CACHE.get(node_id)

    if prev == is_connected:
        return

    ok, result = backend_post(
        f"/esp-status/{node_id}",
        {"isConnected": bool(is_connected)},
        timeout=1.0
    )

    if ok:
        ESP_CONNECTED_CACHE[node_id] = is_connected


# ============================================================
# Serial
# ============================================================

def open_one(node_id):
    port = NODE_PORTS[node_id]

    try:
        ser = serial.Serial(
            port,
            BAUDRATE,
            timeout=TIMEOUT,
            write_timeout=TIMEOUT
        )

        time.sleep(0.15)

        try:
            ser.reset_input_buffer()
            ser.reset_output_buffer()
        except:
            pass

        print(f"[OK] Node {node_id} opened on {port}")
        return ser

    except Exception as e:
        print(f"[ERROR] Node {node_id}: {e}")
        return None


def request_sample(node_id, serials):
    ser = serials[node_id]

    if ser is None:
        return ""

    try:
        ser.write(b"R")
        line = ser.readline().decode(errors="ignore").strip()
        return line

    except Exception:
        close_one(ser)
        serials[node_id] = None
        report_esp_status(node_id, False)
        return ""


# ============================================================
# Data Parsing
# Expected:
# node_id,time,ax,ay,az,gx,gy,gz,mx,my,mz
# ============================================================

def parse_frame(line):
    try:
        parts = line.split(",")

        if len(parts) < 8:
            return None

        node_id = int(parts[0])
        t = int(parts[1])

        ax = float(parts[2])
        ay = float(parts[3])
        az = float(parts[4])

        gx = float(parts[5])
        gy = float(parts[6])
        gz = float(parts[7])

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
            "mz": mz
        }

    except:
        return None


# ============================================================
# Prediction Payload
# Must match PAMAP2 model input:
# Node1 Wrist
# Node2 Chest
# Node3 Ankle
# Backend uses ax, ay, az, gx, gy, gz, mx, my, mz.
# ============================================================

def predict_combined_window(active_nodes, node_windows, prediction_state):
    if len(active_nodes) != 3:
        return False

    for nid in active_nodes:
        if len(node_windows[nid]) < WINDOW_SIZE:
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
        prediction_state["label"] = result.get("activity", "?")
        prediction_state["confidence"] = result.get("confidence", "?")
    else:
        prediction_state["label"] = "ERROR"
        prediction_state["confidence"] = "-"

    return ok


def maybe_predict(active_nodes, parsed, node_windows, last_predict_at, prediction_state):
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
        "mz": parsed["mz"]
    })

    if any(len(node_windows[n]) < WINDOW_SIZE for n in active_nodes):
        return

    now = time.monotonic()

    if now - last_predict_at["combined"] < PREDICT_MIN_INTERVAL_SECONDS:
        return

    if predict_combined_window(active_nodes, node_windows, prediction_state):
        last_predict_at["combined"] = now


# ============================================================
# Display
# ============================================================

def print_table(latest, prediction_state):
    clear_console()

    print("========== HAR HUB ==========")
    print("Nodes:")
    print("1 = Wrist")
    print("2 = Chest")
    print("3 = Ankle")
    print()

    print(
        f"Prediction: {prediction_state['label']} "
        f"({prediction_state['confidence']})"
    )
    print()

    header = "Node | Time | accX accY accZ | gyroX gyroY gyroZ"
    print(header)
    print("-" * len(header))

    for node_id in [1, 2, 3]:
        d = latest.get(node_id)

        if d is None:
            print(f"{node_id:>4} | --- | ---")
        else:
            print(
                f"{node_id:>4} | "
                f"{d['t']:>4} | "
                f"{d['ax']:>4.1f} {d['ay']:>4.1f} {d['az']:>4.1f} | "
                f"{d['gx']:>5.1f} {d['gy']:>5.1f} {d['gz']:>5.1f}"
            )


# ============================================================
# Main
# ============================================================

def main():
    active_nodes = [1, 2, 3]

    serials = {}

    for nid in active_nodes:
        serials[nid] = open_one(nid)

    latest = {}

    node_windows = {
        nid: deque(maxlen=WINDOW_SIZE)
        for nid in active_nodes
    }

    last_predict_at = {
        "combined": 0.0
    }

    prediction_state = {
        "label": "WAITING",
        "confidence": "-"
    }

    print("Waiting for first samples...")

    try:
        while True:
            frame_start = time.perf_counter()

            for node_id in active_nodes:
                line = request_sample(node_id, serials)

                if not line:
                    continue

                parsed = parse_frame(line)

                if parsed and parsed["node_id"] == node_id:
                    latest[node_id] = parsed
                    report_esp_status(node_id, True)

                    maybe_predict(
                        active_nodes,
                        parsed,
                        node_windows,
                        last_predict_at,
                        prediction_state
                    )

            print_table(latest, prediction_state)

            elapsed = time.perf_counter() - frame_start

            if elapsed < FRAME_PERIOD:
                time.sleep(FRAME_PERIOD - elapsed)

    except KeyboardInterrupt:
        print("Stopping...")

    finally:
        for nid in active_nodes:
            report_esp_status(nid, False)

        for ser in serials.values():
            close_one(ser)


if __name__ == "__main__":
    main()

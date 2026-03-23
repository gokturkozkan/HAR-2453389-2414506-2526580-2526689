import serial
import time
import os
import json
from collections import deque
from urllib import request, error

NODE_PORTS = {
    1: "/dev/rfcomm0",
    2: "/dev/rfcomm1",
    3: "/dev/rfcomm2",
    4: "/dev/rfcomm3",
    5: "/dev/rfcomm4",
    6: "/dev/rfcomm5",
    7: "/dev/rfcomm6",
}

BAUDRATE = 115200
TIMEOUT = 0.05
FRAME_PERIOD = 0.28

MAX_WAIT_PER_NODE = 25.0

EARLY_EIO_WINDOW = 2.0
EARLY_EIO_RETRY_DELAY = 0.25

BACKOFF_BASE = 0.5
BACKOFF_MAX = 10.0
RESET_ERRORS_AFTER_OK_SECONDS = 5.0

BACKEND_URL = os.getenv("HAR_BACKEND_URL", "http://127.0.0.1:3000")
WINDOW_SIZE = 32
PREDICT_MIN_INTERVAL_SECONDS = 1.0

# Keeps last status we reported to backend so we don't spam identical updates.
ESP_CONNECTED_CACHE = {}


def choose_nodes():
    available = sorted(NODE_PORTS.keys())
    print("Available nodes:", ", ".join(map(str, available)))
    raw = input(
        f"Enter comma-separated node IDs to use (e.g. {','.join(map(str, available))}). "
        "Leave empty for all: "
    ).strip()

    if not raw:
        return available

    nodes = []
    for part in raw.split(","):
        p = part.strip()
        if not p:
            continue
        try:
            nid = int(p)
            if nid in NODE_PORTS:
                nodes.append(nid)
            else:
                print(f"Ignoring unknown node id {nid}")
        except ValueError:
            print(f"Ignoring invalid entry '{p}'")

    nodes = sorted(set(nodes))
    if not nodes:
        print("No valid nodes selected, defaulting to all.")
        nodes = available
    return nodes


def compute_backoff(errors):
    e = max(0, int(errors))
    delay = BACKOFF_BASE * (2 ** min(e, 6))
    return min(delay, BACKOFF_MAX)


def close_one(ser):
    try:
        if ser is not None and getattr(ser, "is_open", False):
            ser.close()
    except Exception:
        pass


def backend_post(path, payload, timeout=1.0):
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


def predict_combined_window(active_nodes, node_windows):
    windows_by_node = {}
    for node_id in active_nodes:
        window = node_windows[node_id]
        if len(window) < WINDOW_SIZE:
            return False
        windows_by_node[str(node_id)] = list(window)

    ok, result = backend_post(
        "/predict",
        {
            "node_ids": active_nodes,
            "windows_by_node": windows_by_node,
        },
        timeout=2.5,
    )
    if ok:
        label = result.get("activity", "?")
        conf = result.get("confidence", "?")
        used_nodes = result.get("used_node_ids", active_nodes)
        print(f"[PREDICT] Combined nodes {used_nodes}: {label} ({conf})")
    else:
        print(f"[PREDICT] Combined prediction failed: {result}")
    return ok


def maybe_predict(active_nodes, parsed, node_windows, last_predict_at):
    node_id = parsed["node_id"]
    window = node_windows[node_id]
    window.append(
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

    if predict_combined_window(active_nodes, node_windows):
        last_predict_at["combined"] = now


def open_one(node_id):
    port = NODE_PORTS[node_id]
    try:
        ser = serial.Serial(port, BAUDRATE, timeout=TIMEOUT, write_timeout=TIMEOUT)
        time.sleep(0.12)
        try:
            ser.reset_input_buffer()
            ser.reset_output_buffer()
        except Exception:
            pass
        return ser
    except Exception:
        return None


def make_health(active_nodes):
    now = time.monotonic()
    return {
        nid: {
            "errors": 0,
            "next_try": now,
            "opened_at": 0.0,
            "last_ok": 0.0,
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
    report_esp_status(node_id, False)


def try_reconnect(node_id, serials, health):
    h = health[node_id]
    now = time.monotonic()
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


def open_ports(active_nodes):
    serials = {nid: None for nid in active_nodes}
    for node_id in active_nodes:
        port = NODE_PORTS[node_id]
        ser = open_one(node_id)
        if ser is not None:
            print(f"Opened node {node_id} on {port}")
            serials[node_id] = ser
        else:
            print(f"[ERROR] Could not open {port} for node {node_id}")
            serials[node_id] = None
            report_esp_status(node_id, False)
    return serials


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
        errno = getattr(e, "errno", None)
        if errno == 5 and early:
            print(f"[ERROR] Node {node_id}: serial I/O error: {e}")
            mark_error(node_id, serials, health, early=True)
        else:
            print(f"[ERROR] Node {node_id}: serial I/O error: {e}")
            mark_error(node_id, serials, health, early=False)
        return ""


def parse_frame(line):
    try:
        parts = line.split(",")
        # Accept frames that include at least node_id, time, accel, and gyro values.
        # Extra values (e.g., magnetometer/temp) are ignored.
        if len(parts) < 8:
            return None
        node_id = int(parts[0])
        t = int(parts[1])
        ax, ay, az = map(float, parts[2:5])
        gx, gy, gz = map(float, parts[5:8])
        return {
            "node_id": node_id,
            "t": t,
            "ax": ax,
            "ay": ay,
            "az": az,
            "gx": gx,
            "gy": gy,
            "gz": gz,
        }
    except Exception:
        return None


def scientific_row(data):
    t_ms = int(data["t"])
    ax_mg = int(round(data["ax"] / 9.8 * 1000))
    ay_mg = int(round(data["ay"] / 9.8 * 1000))
    az_mg = int(round(data["az"] / 9.8 * 1000))
    gx_milli = int(round(data["gx"] * 1000))
    gy_milli = int(round(data["gy"] * 1000))
    gz_milli = int(round(data["gz"] * 1000))
    return (
        t_ms,
        ax_mg,
        ay_mg,
        az_mg,
        gx_milli,
        gy_milli,
        gz_milli,
    )


def print_table(latest, active_nodes):
    os.system("clear")
    print("===== TDMA Sensor Dashboard =====")
    print()
    header = "Node | MILLISEC |  accX    accY    accZ  |  gyroX   gyroY   gyroZ"
    print(header)
    print("-" * len(header))

    for node_id in active_nodes:
        data = latest.get(node_id)
        if data is None:
            print(
                f"  {node_id:2d} |   ---   |   ---    ---    --- |   ---    ---    ---"
            )
        else:
            (
                t_ms,
                ax_mg,
                ay_mg,
                az_mg,
                gx_milli,
                gy_milli,
                gz_milli,
            ) = scientific_row(data)
            print(
                f"  {node_id:2d} | {t_ms:7d} | {ax_mg:6d} {ay_mg:6d} {az_mg:6d} | {gx_milli:6d} {gy_milli:6d} {gz_milli:6d}"
            )


def wait_for_initial_frames(
    active_nodes, serials, latest, health, node_windows, last_predict_at
):
    print("\nWaiting for initial data from all selected nodes...")
    for node_id in active_nodes:
        start = time.monotonic()
        while True:
            if time.monotonic() - start > MAX_WAIT_PER_NODE:
                print(f"[WARN] Node {node_id}: initial data not found, continuing.")
                break

            line = request_sample(node_id, serials, health)
            parsed = parse_frame(line)
            if parsed is not None and parsed["node_id"] == node_id:
                report_esp_status(node_id, True)
                latest[node_id] = parsed
                maybe_predict(active_nodes, parsed, node_windows, last_predict_at)
                print(f"  Node {node_id}: first sample received.")
                break
            else:
                print(f"  Node {node_id}: no valid data yet, retrying...")
                time.sleep(0.5)

    print("Starting main loop...\n")
    time.sleep(0.5)


def main():
    active_nodes = choose_nodes()
    print(f"Using nodes: {active_nodes}")

    serials = open_ports(active_nodes)
    health = make_health(active_nodes)
    latest = {}
    node_windows = {nid: deque(maxlen=WINDOW_SIZE) for nid in active_nodes}
    last_predict_at = {"combined": 0.0}

    for nid in active_nodes:
        if serials.get(nid) is not None:
            health[nid]["opened_at"] = time.monotonic()

    wait_for_initial_frames(
        active_nodes,
        serials,
        latest,
        health,
        node_windows,
        last_predict_at,
    )

    try:
        while True:
            frame_start = time.perf_counter()
            num_nodes = len(active_nodes)
            if num_nodes == 0:
                print("[ERROR] No active nodes selected; exiting.")
                break

            slot_period = FRAME_PERIOD / num_nodes

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
                    report_esp_status(node_id, True)
                    latest[node_id] = parsed
                    maybe_predict(active_nodes, parsed, node_windows, last_predict_at)

            now = time.perf_counter()
            frame_end = frame_start + FRAME_PERIOD
            if now < frame_end:
                time.sleep(frame_end - now)

            print_table(latest, active_nodes)

    except KeyboardInterrupt:
        print("\nStopping TDMA hub...")
    finally:
        for nid in active_nodes:
            report_esp_status(nid, False)
        for ser in serials.values():
            close_one(ser)


if __name__ == "__main__":
    main()
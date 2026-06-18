import json
import os
import re
import time
import urllib.error
import urllib.request
from itertools import permutations, product
from collections import deque
from datetime import datetime, timezone
import uuid

import serial

NODE_PORTS = {
    1: "/dev/rfcomm0",  # Wrist
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

WARMUP_SECONDS = float(os.getenv("HAR_WARMUP_SECONDS", "10.0"))
POLL_SLEEP = 0.03
WARMUP_STATUS_INTERVAL = 1.0

EARLY_EIO_WINDOW = 2.0
EARLY_EIO_RETRY_DELAY = 0.25

BACKOFF_BASE = 0.5
BACKOFF_MAX = 10.0
RESET_ERRORS_AFTER_OK_SECONDS = 5.0

WINDOW_SIZE = 200
PREDICT_EVERY = 10

FEATURE_KEYS = ("ax", "ay", "az", "gx", "gy", "gz", "mx", "my", "mz")
REQUIRE_ALL_NODES_FOR_FUSION = os.getenv("HAR_REQUIRE_ALL_NODES", "1") not in ("0", "false", "False")

PREDICT_URL = os.getenv("HAR_PREDICT_URL", "http://127.0.0.1:3000/predict")
NODE_ORDER_ENV = os.getenv("PAMAP2_NODE_ORDER", "1,2,3")
AXIS_TRANSFORM_ENV = os.getenv("PAMAP2_AXIS_TRANSFORM", "+x+y+z")
NODE_AXIS_TRANSFORMS_ENV = os.getenv("PAMAP2_NODE_AXIS_TRANSFORMS", "")
MAG_MODE_ENV = os.getenv("PAMAP2_MAG_MODE", "raw")
SENSOR_LOG_PATH = os.getenv(
    "TDMA_SENSOR_LOG_PATH",
    os.path.join(os.path.dirname(__file__), "HAR-backend", "logs", "tdma_sensor_raw.jsonl"),
)
PREDICTION_LOG_PATH = os.getenv(
    "TDMA_PREDICTION_LOG_PATH",
    os.path.join(os.path.dirname(__file__), "HAR-backend", "logs", "tdma_predictions.jsonl"),
)


def write_sensor_log(status, **metadata):
    try:
        log_path = os.path.abspath(SENSOR_LOG_PATH)
        os.makedirs(os.path.dirname(log_path), exist_ok=True)

        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "status": status,
            **metadata,
        }

        with open(log_path, "a", encoding="utf-8") as log_file:
            log_file.write(json.dumps(entry, ensure_ascii=False, default=str))
            log_file.write("\n")
    except Exception as error:
        print(f"[WARN] Failed to write TDMA sensor log: {error}", flush=True)


def parse_node_order(value):
    try:
        order = tuple(int(item.strip()) for item in str(value).split(","))
    except Exception:
        return (1, 2, 3)

    if sorted(order) != [1, 2, 3]:
        return (1, 2, 3)

    return order


AXIS_NAMES = ("x", "y", "z")
AXIS_TRANSFORM_OPTIONS = tuple(
    "".join(
        ("+" if sign > 0 else "-") + AXIS_NAMES[index]
        for index, sign in zip(axis_perm, signs)
    )
    for axis_perm in permutations(range(3))
    for signs in product((-1, 1), repeat=3)
)
MAG_MODE_OPTIONS = (
    "raw",
    "zero",
    "center",
    "div100",
    "div1000",
    "center_div100",
    "center_div1000",
)


def parse_axis_transform(value):
    text = str(value or "+x+y+z").strip().lower().replace(",", "").replace(" ", "")

    if text in ("", "identity", "none", "raw"):
        text = "+x+y+z"

    matches = re.findall(r"([+-]?)([xyz])", text)

    if len(matches) != 3:
        return "+x+y+z"

    axes = [axis for _, axis in matches]

    if len(set(axes)) != 3:
        return "+x+y+z"

    return "".join(
        ("-" if sign == "-" else "+") + axis
        for sign, axis in matches
    )


def parse_node_axis_transforms(value=None, axis_transform=None):
    fallback_axis = parse_axis_transform(axis_transform or PAMAP2_AXIS_TRANSFORM if "PAMAP2_AXIS_TRANSFORM" in globals() else "+x+y+z")

    if value in (None, ""):
        return {
            node_id: fallback_axis
            for node_id in (1, 2, 3)
        }

    if isinstance(value, dict):
        parsed = {
            int(node_id): parse_axis_transform(node_axis)
            for node_id, node_axis in value.items()
        }
    elif isinstance(value, (list, tuple)):
        parsed = {
            node_id: parse_axis_transform(value[index])
            for index, node_id in enumerate((1, 2, 3))
        }
    else:
        text = str(value).strip()

        try:
            return parse_node_axis_transforms(json.loads(text), axis_transform=fallback_axis)
        except Exception:
            pass

        if ":" not in text:
            return {
                node_id: parse_axis_transform(text)
                for node_id in (1, 2, 3)
            }

        parsed = {}
        for item in re.split(r"[;|]", text):
            item = item.strip()

            if not item:
                continue

            node_id_text, node_axis = item.split(":", 1)
            parsed[int(node_id_text.strip())] = parse_axis_transform(node_axis)

    for node_id in (1, 2, 3):
        parsed.setdefault(node_id, fallback_axis)

    return {
        node_id: parsed[node_id]
        for node_id in (1, 2, 3)
    }


def parse_mag_mode(value):
    mode = str(value or "raw").strip().lower().replace("-", "_")
    aliases = {
        "none": "raw",
        "off": "raw",
        "normal": "raw",
        "divide100": "div100",
        "div_100": "div100",
        "divide1000": "div1000",
        "div_1000": "div1000",
        "center_div_100": "center_div100",
        "center_div_1000": "center_div1000",
    }
    mode = aliases.get(mode, mode)
    return mode if mode in MAG_MODE_OPTIONS else "raw"


PAMAP2_NODE_ORDER = parse_node_order(NODE_ORDER_ENV)
PAMAP2_AXIS_TRANSFORM = parse_axis_transform(AXIS_TRANSFORM_ENV)
PAMAP2_NODE_AXIS_TRANSFORMS = parse_node_axis_transforms(
    NODE_AXIS_TRANSFORMS_ENV,
    axis_transform=PAMAP2_AXIS_TRANSFORM,
)
PAMAP2_MAG_MODE = parse_mag_mode(MAG_MODE_ENV)
NODE_ORDER_OPTIONS = tuple(",".join(str(node_id) for node_id in order) for order in permutations((1, 2, 3)))


def make_prediction_id():
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    return f"tdma-{stamp}-{uuid.uuid4().hex[:8]}"


def write_prediction_log(status, **metadata):
    try:
        log_path = os.path.abspath(PREDICTION_LOG_PATH)
        os.makedirs(os.path.dirname(log_path), exist_ok=True)

        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "status": status,
            "predict_url": PREDICT_URL,
            "window_size": WINDOW_SIZE,
            "features": list(FEATURE_KEYS),
            **metadata,
        }

        with open(log_path, "a", encoding="utf-8") as log_file:
            log_file.write(json.dumps(entry, ensure_ascii=False, default=str))
            log_file.write("\n")
    except Exception as error:
        print(f"[WARN] Failed to write TDMA prediction log: {error}", flush=True)


def summarize_values(values):
    if not values:
        return {
            "min": None,
            "mean": None,
            "max": None,
        }

    return {
        "min": round(min(values), 6),
        "mean": round(sum(values) / len(values), 6),
        "max": round(max(values), 6),
    }


def summarize_predict_payload(payload):
    windows_by_node = payload.get("windows_by_node", {})
    summary = {
        "resampled_window": payload.get("resampled_window"),
        "nodes": {},
    }

    for node_id, readings in windows_by_node.items():
        feature_values = {
            key: []
            for key in FEATURE_KEYS
        }

        for reading in readings:
            for key in FEATURE_KEYS:
                try:
                    feature_values[key].append(float(reading.get(key, 0.0)))
                except Exception:
                    pass

        summary["nodes"][str(node_id)] = {
            "count": len(readings),
            "first": readings[0] if readings else None,
            "last": readings[-1] if readings else None,
            "feature_stats": {
                key: summarize_values(values)
                for key, values in feature_values.items()
            },
        }

    return summary


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
        except Exception:
            pass

        return ser

    except Exception as error:
        write_sensor_log(
            "serial_open_error",
            node_id=node_id,
            port=port,
            error=str(error),
        )
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
            write_sensor_log(
                "raw_sample",
                node_id=node_id,
                port=NODE_PORTS[node_id],
                line=line,
            )

        return line

    except (OSError, serial.SerialException) as e:
        now = time.monotonic()
        early = (now - h["opened_at"]) <= EARLY_EIO_WINDOW

        if isinstance(e, OSError) and getattr(e, "errno", None) == 5 and early:
            mark_error(node_id, serials, health, early=True)
        else:
            mark_error(node_id, serials, health, early=False)

        write_sensor_log(
            "sample_error",
            node_id=node_id,
            port=NODE_PORTS[node_id],
            error=repr(e),
        )

        return ""


# ============================================================
# Calibration
# ============================================================

def calibrate_node_sample(sample):
    """
    Keep this as light as possible.

    The restored PAMAP2 model expects ax, ay, az, gx, gy, gz, mx, my, mz.
    Only apply real axis corrections if needed.

    For now this returns the sample unchanged.
    """

    return sample


# ============================================================
# Sensor Data Parsing
# ============================================================

def parse_frame(line):
    """
    Expected ESP format:

    node_id,t,ax,ay,az,gx,gy,gz,mx,my,mz

    If a device is still sending only IMU values, magnetometer values default to 0.0.
    """

    try:
        parts = line.split(",")

        if len(parts) < 8:
            return None

        node_id = int(parts[0])

        if node_id not in NODE_PORTS:
            return None

        t = int(float(parts[1]))

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
            "mz": mz,
        }

    except Exception:
        return None


# ============================================================
# Multi-Node Feature Fusion
# ============================================================

def build_fused_timestep(active_nodes, latest):
    timestep = {"nodes": {}}

    for node_id in active_nodes:
        sample = latest.get(node_id)

        if sample is None:
            if REQUIRE_ALL_NODES_FOR_FUSION:
                return None

            timestep["nodes"][str(node_id)] = {
                key: 0.0
                for key in FEATURE_KEYS
            }

            continue

        timestep["nodes"][str(node_id)] = {
            key: float(sample.get(key, 0.0))
            for key in FEATURE_KEYS
        }

    return timestep


# ============================================================
# HAR Model Prediction API
# ============================================================

def build_predict_payload(
    window_payload,
    node_order=None,
    axis_transform=None,
    node_axis_transforms=None,
    mag_mode=None,
):
    node_order = tuple(node_order or PAMAP2_NODE_ORDER)
    axis_transform = parse_axis_transform(axis_transform or PAMAP2_AXIS_TRANSFORM)
    node_axis_transforms = parse_node_axis_transforms(
        node_axis_transforms or PAMAP2_NODE_AXIS_TRANSFORMS,
        axis_transform=axis_transform,
    )
    mag_mode = parse_mag_mode(mag_mode or PAMAP2_MAG_MODE)
    prediction_id = make_prediction_id()
    payload = {
        "node_order": list(node_order),
        "axis_transform": axis_transform,
        "node_axis_transforms": {
            str(node_id): node_axis
            for node_id, node_axis in node_axis_transforms.items()
        },
        "mag_mode": mag_mode,
        "windows_by_node": {
            "1": [],
            "2": [],
            "3": [],
        }
    }

    for timestep in window_payload:
        nodes = timestep["nodes"]

        for node_id in ("1", "2", "3"):
            if node_id not in nodes:
                write_prediction_log(
                    "payload_error",
                    prediction_id=prediction_id,
                    node_order=list(node_order),
                    axis_transform=axis_transform,
                    node_axis_transforms=payload["node_axis_transforms"],
                    mag_mode=mag_mode,
                    error=f"Missing node {node_id} in fused timestep",
                )
                return prediction_id, None, f"Missing node {node_id} in fused timestep"

            payload["windows_by_node"][node_id].append(nodes[node_id])

    for node_id in ("1", "2", "3"):
        count = len(payload["windows_by_node"][node_id])

        if count != WINDOW_SIZE:
            write_prediction_log(
                "payload_error",
                prediction_id=prediction_id,
                node_order=list(node_order),
                axis_transform=axis_transform,
                node_axis_transforms=payload["node_axis_transforms"],
                mag_mode=mag_mode,
                node_id=node_id,
                count=count,
                expected=WINDOW_SIZE,
            )
            return prediction_id, None, f"Node {node_id} payload has {count} rows, expected {WINDOW_SIZE}"

    return prediction_id, payload, None


def post_predict(window_payload, node_order=None, axis_transform=None, node_axis_transforms=None, mag_mode=None):
    axis_transform = parse_axis_transform(axis_transform or PAMAP2_AXIS_TRANSFORM)
    node_axis_transforms = parse_node_axis_transforms(
        node_axis_transforms or PAMAP2_NODE_AXIS_TRANSFORMS,
        axis_transform=axis_transform,
    )
    mag_mode = parse_mag_mode(mag_mode or PAMAP2_MAG_MODE)
    prediction_id, payload, build_error = build_predict_payload(
        window_payload,
        node_order=node_order,
        axis_transform=axis_transform,
        node_axis_transforms=node_axis_transforms,
        mag_mode=mag_mode,
    )

    if build_error:
        return None, build_error

    body = json.dumps(payload).encode("utf-8")
    payload_summary = summarize_predict_payload(payload)
    write_prediction_log(
        "request",
        prediction_id=prediction_id,
        node_order=list(node_order or PAMAP2_NODE_ORDER),
        axis_transform=axis_transform,
        node_axis_transforms=payload.get("node_axis_transforms"),
        mag_mode=mag_mode,
        payload_summary=payload_summary,
        body_bytes=len(body),
    )

    req = urllib.request.Request(
        PREDICT_URL,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        started_at = time.perf_counter()
        with urllib.request.urlopen(req, timeout=5.0) as response:
            raw = response.read().decode("utf-8", errors="ignore")
            parsed = json.loads(raw) if raw else {}

        write_prediction_log(
            "success",
            prediction_id=prediction_id,
            node_order=list(node_order or PAMAP2_NODE_ORDER),
            axis_transform=axis_transform,
            node_axis_transforms=payload.get("node_axis_transforms"),
            mag_mode=mag_mode,
            latency_ms=round((time.perf_counter() - started_at) * 1000.0, 2),
            response=parsed,
        )
        return parsed, None

    except urllib.error.HTTPError as exc:
        error_body = exc.read().decode("utf-8", errors="ignore")
        write_prediction_log(
            "http_error",
            prediction_id=prediction_id,
            node_order=list(node_order or PAMAP2_NODE_ORDER),
            axis_transform=axis_transform,
            node_axis_transforms=payload.get("node_axis_transforms") if payload else None,
            mag_mode=mag_mode,
            http_status=exc.code,
            error=error_body,
        )
        return None, f"HTTP {exc.code}: {error_body}"

    except urllib.error.URLError as exc:
        write_prediction_log(
            "url_error",
            prediction_id=prediction_id,
            node_order=list(node_order or PAMAP2_NODE_ORDER),
            axis_transform=axis_transform,
            node_axis_transforms=payload.get("node_axis_transforms") if payload else None,
            mag_mode=mag_mode,
            error=str(exc),
        )
        return None, str(exc)

    except Exception as exc:
        write_prediction_log(
            "error",
            prediction_id=prediction_id,
            node_order=list(node_order or PAMAP2_NODE_ORDER),
            axis_transform=axis_transform,
            node_axis_transforms=payload.get("node_axis_transforms") if payload else None,
            mag_mode=mag_mode,
            error=str(exc),
        )
        return None, str(exc)


# ============================================================
# Console Dashboard Output
# ============================================================

def print_table(latest, active_nodes, health, fused_window_len, last_prediction):
    os.system("clear" if os.name != "nt" else "cls")

    print("===== TDMA HAR Dashboard - PAMAP2 3-Node Dataset =====")
    print("Node 1 = Wrist")
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
# ============================================================

def warmup(active_nodes, serials, latest, health):
    print("\nWaiting for initial data from wrist, chest, and ankle...")
    print(f"Warmup timeout: {WARMUP_SECONDS:.1f}s. Dashboard starts even if some nodes are missing.")

    deadline = time.monotonic() + WARMUP_SECONDS
    got = set()
    last_status_at = 0.0

    while time.monotonic() < deadline and len(got) < len(active_nodes):
        for node_id in active_nodes:
            if node_id in got:
                continue

            line = request_sample(node_id, serials, health)
            parsed = parse_frame(line)

            if parsed is not None and parsed["node_id"] == node_id:
                parsed = calibrate_node_sample(parsed)
                latest[node_id] = parsed
                got.add(node_id)
                print(f"  Node {node_id} ({NODE_NAMES[node_id]}): first sample received.")
                write_sensor_log("first_sample", node_id=node_id, sample=parsed)

        now = time.monotonic()

        if now - last_status_at >= WARMUP_STATUS_INTERVAL:
            missing = [node_id for node_id in active_nodes if node_id not in got]
            seconds_left = max(0.0, deadline - now)
            print(
                f"  Warmup status: got={sorted(got) or '-'} "
                f"missing={missing or '-'} left={seconds_left:.1f}s"
            )
            write_sensor_log(
                "warmup_status",
                got=sorted(got),
                missing=missing,
                seconds_left=round(seconds_left, 1),
            )
            last_status_at = now

        time.sleep(POLL_SLEEP)

    missing = [node_id for node_id in active_nodes if node_id not in got]

    if missing:
        print(f"[WARN] No initial data from nodes: {missing}")
        print("[WARN] Prediction will wait until all 3 nodes provide samples.")
        write_sensor_log("warmup_missing_nodes", missing=missing)

    print("Starting main loop...\n")
    time.sleep(0.5)


# ============================================================
# Main TDMA Runtime Loop
# ============================================================

def main():
    active_nodes = [1, 2, 3]

    print("Using fixed 3-node layout:")
    print("1 = Wrist")
    print("2 = Chest")
    print("3 = Ankle")
    print(f"PAMAP2 model node order: {','.join(str(node_id) for node_id in PAMAP2_NODE_ORDER)}")
    print(f"PAMAP2 axis transform: {PAMAP2_AXIS_TRANSFORM}")
    print(
        "PAMAP2 node axes: "
        + ", ".join(f"{node_id}={axis}" for node_id, axis in PAMAP2_NODE_AXIS_TRANSFORMS.items())
    )
    print(f"PAMAP2 mag mode: {PAMAP2_MAG_MODE}")

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
                    parsed = calibrate_node_sample(parsed)
                    latest[node_id] = parsed
                    write_sensor_log("parsed_sample", node_id=node_id, sample=parsed)

            fused_timestep = build_fused_timestep(active_nodes, latest)

            if fused_timestep is not None:
                fused_window.append(fused_timestep)
                rows_since_prediction += 1

            if len(fused_window) == WINDOW_SIZE and rows_since_prediction >= PREDICT_EVERY:
                response, err = post_predict(list(fused_window))
                rows_since_prediction = 0

                if err:
                    last_prediction = f"predict error: {err}"
                    print(last_prediction)
                else:
                    activity = (
                        response.get("activity")
                        or response.get("predicted_label")
                        or response.get("label")
                        or "unknown"
                    )

                    confidence = response.get("confidence")

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

import serial
import time
import os
import csv
from datetime import datetime

NODE_PORTS = {
    1: "/dev/rfcomm0",
    2: "/dev/rfcomm1",
    3: "/dev/rfcomm2",
    4: "/dev/rfcomm3",
    5: "/dev/rfcomm4",
    6: "/dev/rfcomm5",
}

BAUDRATE = 115200
TIMEOUT = 0.05
FRAME_PERIOD = 0.28

WARMUP_SECONDS = 60.0
POLL_SLEEP = 0.03

EARLY_EIO_WINDOW = 2.0
EARLY_EIO_RETRY_DELAY = 0.25

BACKOFF_BASE = 0.5
BACKOFF_MAX = 10.0
RESET_ERRORS_AFTER_OK_SECONDS = 5.0


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


def parse_frame(line):
    try:
        parts = line.split(",")
        if len(parts) != 12:
            return None
        node_id = int(parts[0])
        t = int(parts[1])
        ax, ay, az = map(float, parts[2:5])
        gx, gy, gz = map(float, parts[5:8])
        mx, my, mz = map(float, parts[8:11])
        temp = float(parts[11])
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
            "temp": temp,
        }
    except Exception:
        return None


def print_table(latest, active_nodes, health):
    os.system("clear")
    print("===== TDMA Sensor Dashboard =====")
    print()
    header = "Node | t(ms)  |  ax      ay      az   |  gx      gy      gz   | err | wait"
    print(header)
    print("-" * len(header))

    now = time.monotonic()
    for node_id in active_nodes:
        data = latest.get(node_id)
        h = health[node_id]
        wait = max(0.0, h["next_try"] - now)
        if data is None:
            print(
                f"  {node_id:2d} |  ---   |   ---    ---    --- |"
                f"   ---    ---    --- | {h['errors']:3d} | {wait:4.1f}s"
            )
        else:
            print(
                f"  {node_id:2d} | {data['t']:6d} | "
                f"{data['ax']:6.2f} {data['ay']:6.2f} {data['az']:6.2f} | "
                f"{data['gx']:6.2f} {data['gy']:6.2f} {data['gz']:6.2f} | "
                f"{h['errors']:3d} | {wait:4.1f}s"
            )


def warmup(active_nodes, serials, latest, health):
    print("\nWaiting for initial data (non-blocking warmup)...")
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
                print(f"  Node {node_id}: first sample received.")
        time.sleep(POLL_SLEEP)

    missing = [n for n in active_nodes if n not in got]
    if missing:
        print(f"[WARN] No initial data from: {missing} (will keep trying in main loop)")
    print("Starting main loop...\n")
    time.sleep(0.5)


def make_log_writer(label, active_nodes):
    os.makedirs("data", exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = f"data/session_{label}_{ts}.csv"
    f = open(path, "w", newline="")
    w = csv.writer(f)
    header = ["host_ts"]
    for nid in active_nodes:
        header += [f"n{nid}_ax", f"n{nid}_ay", f"n{nid}_az", f"n{nid}_gx", f"n{nid}_gy", f"n{nid}_gz"]
    header += ["label"]
    w.writerow(header)
    f.flush()
    print(f"[LOG] {path}")
    return f, w


def main():
    active_nodes = choose_nodes()
    print(f"Using nodes: {active_nodes}")

    label = input("Enter label for this recording (idle/walk/sit) or leave empty for no logging: ").strip()
    log_file = None
    log_writer = None
    if label:
        log_file, log_writer = make_log_writer(label, active_nodes)

    serials = {nid: None for nid in active_nodes}
    health = make_health(active_nodes)
    latest = {}

    for nid in active_nodes:
        try_reconnect(nid, serials, health)
        time.sleep(0.05)

    warmup(active_nodes, serials, latest, health)

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
                    latest[node_id] = parsed

            now = time.perf_counter()
            frame_end = frame_start + FRAME_PERIOD
            if now < frame_end:
                time.sleep(frame_end - now)

            if log_writer is not None and all(nid in latest for nid in active_nodes):
                row = [time.time()]
                for nid in active_nodes:
                    d = latest[nid]
                    row += [d["ax"], d["ay"], d["az"], d["gx"], d["gy"], d["gz"]]
                row += [label]
                log_writer.writerow(row)
                log_file.flush()

            print_table(latest, active_nodes, health)

    except KeyboardInterrupt:
        print("\nStopping TDMA hub...")
    finally:
        for ser in serials.values():
            close_one(ser)
        if log_file is not None:
            log_file.close()


if __name__ == "__main__":
    main()

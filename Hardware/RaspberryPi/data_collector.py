import os
import time
import serial

# =========================
# CONFIG
# =========================

NODE_PORTS = {
    1: "/dev/rfcomm0",
    2: "/dev/rfcomm1",
    3: "/dev/rfcomm2",
}

NODE_NAMES = {
    1: "wrist",
    2: "chest",
    3: "ankle",
}

BAUDRATE = 115200
TIMEOUT = 0.05

FRAME_PERIOD = 0.03  # ~30Hz
COLLECTION_DURATION_SECONDS = 180  # 3 minutes

OUTPUT_DIR = "dataset"

# =========================
# CALIBRATION (FROM TDMA HUB)
# =========================

CALIBRATION_OFFSETS = {
    2: {  # chest node, align roughly to node 1
        "ax": -0.06,
        "ay": 0.58,
        "az": -0.23,
        "gx": 0.02,
        "gy": 0.01,
        "gz": 0.08,
    },
    3: {  # ankle node, align roughly to node 1
        "ax": 0.40,
        "ay": 0.90,
        "az": -0.70,
        "gx": 0.14,
        "gy": 0.04,
        "gz": 0.03,
    }
}

def apply_calibration(node_id, data):
    ax, ay, az, gx, gy, gz = data

    offsets = CALIBRATION_OFFSETS.get(node_id, {})

    ax += offsets.get("ax", 0.0)
    ay += offsets.get("ay", 0.0)
    az += offsets.get("az", 0.0)
    gx += offsets.get("gx", 0.0)
    gy += offsets.get("gy", 0.0)
    gz += offsets.get("gz", 0.0)

    return (ax, ay, az, gx, gy, gz)

# =========================
# SERIAL UTILS
# =========================

def open_serial(port):
    try:
        ser = serial.Serial(port, BAUDRATE, timeout=TIMEOUT)
        time.sleep(0.2)
        ser.reset_input_buffer()
        return ser
    except Exception as e:
        print(f"[ERROR] Cannot open {port}: {e}")
        return None


def close_serial(ser):
    try:
        if ser and ser.is_open:
            ser.close()
    except:
        pass

# =========================
# PARSER
# =========================

def parse_line(line):
    try:
        parts = line.strip().split(",")

        if len(parts) < 8:
            return None

        node_id = int(parts[0])

        ax, ay, az = map(float, parts[2:5])
        gx, gy, gz = map(float, parts[5:8])

        return node_id, (ax, ay, az, gx, gy, gz)

    except:
        return None

# =========================
# FILE WRITER
# =========================

def create_files(label=None):
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    files = {}

    for node_id, name in NODE_NAMES.items():
        filename = f"{name}.txt"

        if label is not None:
            filename = f"{label}_{filename}"

        path = os.path.join(OUTPUT_DIR, filename)
        f = open(path, "a")
        files[node_id] = f

    return files


def write_sample(f, data, label=None):
    ax, ay, az, gx, gy, gz = data

    if label is not None:
        line = f"{label},{ax:.4f},{ay:.4f},{az:.4f},{gx:.4f},{gy:.4f},{gz:.4f}\n"
    else:
        line = f"{ax:.4f},{ay:.4f},{az:.4f},{gx:.4f},{gy:.4f},{gz:.4f}\n"

    f.write(line)

# =========================
# WARMUP
# =========================

def warmup(active_nodes, serials):
    print("\nWaiting for nodes to send first data...\n")

    got = set()
    start = time.monotonic()

    while len(got) < len(active_nodes):
        for node_id in active_nodes:
            if node_id in got:
                continue

            ser = serials[node_id]
            if ser is None:
                continue

            try:
                ser.write(b"R")
                line = ser.readline().decode(errors="ignore")

                parsed = parse_line(line)

                if parsed is None:
                    continue

                nid, _ = parsed

                if nid == node_id:
                    got.add(node_id)
                    print(f"✅ Node {node_id} ({NODE_NAMES[node_id]}) is sending data")

            except:
                continue

        time.sleep(0.02)

        if time.monotonic() - start > 15:
            print("⚠️ Timeout: some nodes not responding")
            break

    print("\nStarting data collection...\n")

# =========================
# MAIN
# =========================

def main():
    print("=== DATA COLLECTION MODE ===")
    print("Press CTRL+C to stop\n")

    label = input("Enter activity label (e.g. 1=walk, 2=sit): ").strip()
    if label == "":
        label = None

    print("\nConnecting to nodes...\n")

    serials = {}

    for node_id, port in NODE_PORTS.items():
        ser = open_serial(port)

        if ser:
            print(f"🟢 Node {node_id} ({NODE_NAMES[node_id]}) connected on {port}")
        else:
            print(f"🔴 Node {node_id} ({NODE_NAMES[node_id]}) FAILED on {port}")

        serials[node_id] = ser

    active_nodes = list(NODE_PORTS.keys())

    warmup(active_nodes, serials)

    files = create_files(label)

    samples_written = {1: 0, 2: 0, 3: 0}
    collection_start = time.monotonic()

    try:
        while time.monotonic() - collection_start < COLLECTION_DURATION_SECONDS:
            frame_start = time.perf_counter()

            for node_id in active_nodes:
                ser = serials[node_id]

                if ser is None:
                    continue

                try:
                    ser.write(b"R")
                    line = ser.readline().decode(errors="ignore")

                    parsed = parse_line(line)

                    if parsed is None:
                        continue

                    nid, data = parsed

                    if nid != node_id:
                        continue

                    # ✅ APPLY CALIBRATION HERE
                    data = apply_calibration(node_id, data)

                    write_sample(files[node_id], data, label)

                    samples_written[node_id] += 1

                except:
                    continue

            print(
                f"W:{samples_written[1]}  C:{samples_written[2]}  A:{samples_written[3]}",
                end="\r"
            )

            elapsed = time.perf_counter() - frame_start
            if elapsed < FRAME_PERIOD:
                time.sleep(FRAME_PERIOD - elapsed)

        print("\n3 minutes completed. Stopping data collection...")

    except KeyboardInterrupt:
        print("\nStopping data collection...")

    finally:
        for ser in serials.values():
            close_serial(ser)

        for f in files.values():
            f.close()

        print(f"\nFiles saved in: {OUTPUT_DIR}/")


if __name__ == "__main__":
    main()

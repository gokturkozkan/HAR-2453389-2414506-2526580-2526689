import serial
import time
import os

NODE_PORTS = {
    1: "/dev/rfcomm0",
    2: "/dev/rfcomm1",
    3: "/dev/rfcomm2",
    4: "/dev/rfcomm3",
}

BAUDRATE = 115200
TIMEOUT = 0.2
FRAME_PERIOD = 1.0


def choose_nodes():
    print("Available nodes: 1, 2, 3, 4")
    raw = input(
        "Enter comma-separated node IDs to use (e.g. 1,2,3,4). "
        "Leave empty for all: "
    ).strip()

    if not raw:
        return sorted(NODE_PORTS.keys())

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
        print("No valid nodes selected, defaulting to all 1-4.")
        nodes = sorted(NODE_PORTS.keys())
    return nodes


def open_ports(active_nodes):
    serials = {}
    for node_id in active_nodes:
        port = NODE_PORTS[node_id]
        try:
            ser = serial.Serial(port, BAUDRATE, timeout=TIMEOUT)
            print(f"Opened node {node_id} on {port}")
            serials[node_id] = ser
        except Exception as e:
            print(f"[ERROR] Could not open {port} for node {node_id}: {e}")
            serials[node_id] = None
    return serials


def request_sample(node_id, ser):
    if ser is None:
        return ""
    try:
        ser.write(b"R")
        line = ser.readline().decode(errors="ignore").strip()
        return line
    except (OSError, serial.SerialException) as e:
        print(f"[ERROR] Node {node_id}: serial I/O error: {e}")
        try:
            ser.close()
        except Exception:
            pass
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


def print_table(latest, active_nodes):
    os.system("clear")
    print("===== TDMA Sensor Dashboard =====")
    print()
    header = (
        "Node | t(ms)  |  ax      ay      az   |  mx      my      mz   | temp(C)"
    )
    print(header)
    print("-" * len(header))

    for node_id in active_nodes:
        data = latest.get(node_id)
        if data is None:
            print(
                f"  {node_id:2d} |  ---   |   ---    ---    --- |"
                f"   ---    ---    --- |  ---"
            )
        else:
            print(
                f"  {node_id:2d} | {data['t']:6d} | "
                f"{data['ax']:6.2f} {data['ay']:6.2f} {data['az']:6.2f} | "
                f"{data['mx']:6.1f} {data['my']:6.1f} {data['mz']:6.1f} | "
                f"{data['temp']:6.2f}"
            )


def wait_for_initial_frames(active_nodes, serials, latest):
    print("\nWaiting for initial data from all selected nodes...")
    for node_id in active_nodes:
        ser = serials.get(node_id)
        if ser is None:
            print(f"[WARN] Node {node_id}: no serial opened, skipping.")
            continue

        while True:
            line = request_sample(node_id, ser)
            parsed = parse_frame(line)
            if parsed is not None:
                latest[node_id] = parsed
                print(f"  Node {node_id}: first sample received.")
                break
            else:
                print(f"  Node {node_id}: no valid data yet, retrying...")
                time.sleep(0.5)

    print("Initial TDMA lock acquired. Starting main loop...\n")
    time.sleep(1.0)


def main():
    active_nodes = choose_nodes()
    print(f"Using nodes: {active_nodes}")

    serials = open_ports(active_nodes)
    latest = {}

    wait_for_initial_frames(active_nodes, serials, latest)

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

                ser = serials.get(node_id)
                if ser is None:
                    continue

                line = request_sample(node_id, ser)
                if not line:
                    continue

                parsed = parse_frame(line)
                if parsed is not None:
                    latest[node_id] = parsed

            now = time.perf_counter()
            frame_end = frame_start + FRAME_PERIOD
            if now < frame_end:
                time.sleep(frame_end - now)

            print_table(latest, active_nodes)

    except KeyboardInterrupt:
        print("\nStopping TDMA hub...")
    finally:
        for ser in serials.values():
            if ser is not None and ser.is_open:
                ser.close()


if __name__ == "__main__":
    main()

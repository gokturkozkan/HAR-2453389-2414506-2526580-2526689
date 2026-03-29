import json
import os
import time
from urllib import error, request

from tdma_wifi_transport import (
    PREDICT_MIN_INTERVAL_SECONDS,
    SUPERFRAME_SECONDS,
    SYNC_LEAD_MS,
    NODE_SLOT_MS,
    SoftTDMAHub,
    ProtocolError,
    broadcast_socket,
    listening_socket,
)

BACKEND_URL = os.getenv("HAR_BACKEND_URL", "http://127.0.0.1:3000")
SYNC_PORT = int(os.getenv("HAR_WIFI_SYNC_PORT", "39000"))
DATA_PORT = int(os.getenv("HAR_WIFI_DATA_PORT", "39001"))
SYNC_BROADCAST_HOST = os.getenv("HAR_WIFI_BROADCAST_HOST", "255.255.255.255")
RENDER_INTERVAL_SECONDS = float(os.getenv("HAR_RENDER_INTERVAL_SECONDS", "0.5"))


def clear_console():
    print("\n" * 40)


def choose_nodes():
    env_nodes = os.getenv("HAR_ACTIVE_NODES", "").strip()
    available = list(range(1, 8))
    if env_nodes:
        nodes = []
        for part in env_nodes.split(","):
            try:
                node_id = int(part.strip())
            except ValueError:
                continue
            if node_id in available:
                nodes.append(node_id)
        nodes = sorted(set(nodes))
        return nodes or available
    return available


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
    except error.HTTPError as exc:
        try:
            raw = exc.read().decode("utf-8", errors="ignore")
            try:
                return False, json.loads(raw) if raw else {}
            except Exception:
                return False, raw
        except Exception:
            return False, f"HTTP Error {exc.code}: {exc.reason}"
    except error.URLError as exc:
        return False, str(exc)
    except Exception as exc:
        return False, str(exc)


class BackendStatusReporter:
    def __init__(self):
        self.cache = {}

    def __call__(self, payload):
        node_id = payload["id"]
        previous = self.cache.get(node_id)
        if previous == payload:
            return
        ok, result = backend_post(f"/esp-status/{node_id}", payload, timeout=1.0)
        if ok:
            self.cache[node_id] = dict(payload)
            print(
                f"[BACKEND] Node {node_id}: {payload['state']} "
                f"(seq={payload['lastSeq']}, missed={payload['missedPackets']})"
            )
        else:
            print(f"[BACKEND] Failed to update node {node_id}: {result}")


def predict_combined_window(active_nodes, node_windows):
    payload = {
        "node_ids": list(active_nodes),
        "windows_by_node": {str(node_id): readings for node_id, readings in node_windows.items()},
    }
    ok, result = backend_post("/predict", payload, timeout=2.5)
    if ok:
        print(
            f"[PREDICT] Combined nodes {result.get('used_node_ids', active_nodes)}: "
            f"{result.get('activity', '?')} ({result.get('confidence', '?')})"
        )
    else:
        print(f"[PREDICT] Combined prediction failed: {result}")
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


def print_table(hub, active_nodes):
    clear_console()
    print("===== TDMA Sensor Dashboard (WI-FI INPUT / REAL PREDICTION) =====")
    print(
        f"Soft TDMA: superframe={SUPERFRAME_SECONDS:.3f}s, sync lead={SYNC_LEAD_MS}ms, "
        f"slot={NODE_SLOT_MS}ms, predict interval={PREDICT_MIN_INTERVAL_SECONDS:.1f}s"
    )
    print(
        f"Predicted label : {hub.prediction_state.get('label', 'WAITING')} "
        f"({hub.prediction_state.get('confidence', '-')}) [BACKEND]"
    )
    print()
    header = (
        "Node | State        | Seen(ms) | Seq    | Miss | MILLISEC | "
        " accX    accY    accZ  |  gyroX   gyroY   gyroZ"
    )
    print(header)
    print("-" * len(header))

    latest = hub.latest_table_rows()
    for snapshot in hub.status_snapshots():
        node_id = snapshot["id"]
        if node_id not in active_nodes:
            continue
        seen = "---" if snapshot["lastSeenMs"] is None else f"{snapshot['lastSeenMs']:7d}"
        data = latest.get(node_id)
        if data is None:
            print(
                f"  {node_id:2d} | {snapshot['state']:<12} | {seen} | "
                f"{snapshot['lastSeq']:6d} | {snapshot['missedPackets']:4d} |"
                "   ---   |   ---    ---    --- |   ---    ---    ---"
            )
            continue
        t_ms, ax_mg, ay_mg, az_mg, gx_milli, gy_milli, gz_milli = scientific_row(data)
        print(
            f"  {node_id:2d} | {snapshot['state']:<12} | {seen} | "
            f"{snapshot['lastSeq']:6d} | {snapshot['missedPackets']:4d} | {t_ms:7d} | "
            f"{ax_mg:6d} {ay_mg:6d} {az_mg:6d} | {gx_milli:6d} {gy_milli:6d} {gz_milli:6d}"
        )


def mark_all_disconnected(reporter, active_nodes):
    for node_id in active_nodes:
        reporter(
            {
                "id": node_id,
                "isConnected": False,
                "state": "disconnected",
                "lastSeenMs": None,
                "lastSeq": 0,
                "missedPackets": 0,
            }
        )


def main():
    active_nodes = choose_nodes()
    print(f"Using nodes: {active_nodes}")
    reporter = BackendStatusReporter()
    hub = SoftTDMAHub(active_nodes, status_callback=reporter)
    for snapshot in hub.status_snapshots():
        reporter(snapshot)

    inbound = listening_socket(DATA_PORT)
    sync_sock = broadcast_socket()
    print(f"Listening for HELLO/DATA on UDP {DATA_PORT}")
    print(f"Broadcasting SYNC on {SYNC_BROADCAST_HOST}:{SYNC_PORT}")

    next_sync_at = time.monotonic()
    next_render_at = time.monotonic()

    try:
        while True:
            now = time.monotonic()
            if now >= next_sync_at:
                sync_packet = hub.build_sync_packet()
                sync_sock.sendto(sync_packet, (SYNC_BROADCAST_HOST, SYNC_PORT))
                next_sync_at += SUPERFRAME_SECONDS
                if next_sync_at < now:
                    next_sync_at = now + SUPERFRAME_SECONDS

            while True:
                try:
                    raw, addr = inbound.recvfrom(4096)
                except BlockingIOError:
                    break
                try:
                    packet = hub.handle_packet(raw, addr=addr)
                    if packet["type"] == "hello":
                        print(
                            f"[HELLO] Node {packet['node_id']} from {addr[0]} "
                            f"sync_locked={packet['sync_locked']}"
                        )
                except ProtocolError as exc:
                    print(f"[WARN] Ignoring invalid packet from {addr}: {exc}")

            hub.refresh_states(now)
            hub.maybe_emit_streaming_status(now)
            hub.maybe_predict(predict_combined_window, now)

            if now >= next_render_at:
                print_table(hub, active_nodes)
                next_render_at = now + RENDER_INTERVAL_SECONDS

            time.sleep(0.01)
    except KeyboardInterrupt:
        print("\nStopping Wi-Fi TDMA hub...")
    finally:
        mark_all_disconnected(reporter, active_nodes)
        inbound.close()
        sync_sock.close()


if __name__ == "__main__":
    main()

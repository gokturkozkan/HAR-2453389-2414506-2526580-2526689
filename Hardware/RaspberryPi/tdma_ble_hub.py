import asyncio
import json
import os
import time
from pathlib import Path
from urllib import error, request

try:
    from bleak import BleakClient
except ImportError:  # pragma: no cover - exercised only on machines without bleak installed
    BleakClient = None

from tdma_ble_transport import (
    NODE_SLOT_MS,
    PREDICT_MIN_INTERVAL_SECONDS,
    SUPERFRAME_MS,
    SUPERFRAME_SECONDS,
    SYNC_LEAD_MS,
    ProtocolError,
    SoftTDMAHub,
)

BACKEND_URL = os.getenv("HAR_BACKEND_URL", "http://127.0.0.1:3000")
REGISTRY_PATH = Path(
    os.getenv(
        "HAR_BLE_NODE_REGISTRY",
        Path(__file__).with_name("ble_node_registry.json"),
    )
)
HAR_SERVICE_UUID = "8c3a1000-7f8f-4f4a-9a91-0c2f83dd0001"
CONTROL_CHAR_UUID = "8c3a1001-7f8f-4f4a-9a91-0c2f83dd0001"
STREAM_CHAR_UUID = "8c3a1002-7f8f-4f4a-9a91-0c2f83dd0001"
RENDER_INTERVAL_SECONDS = float(os.getenv("HAR_RENDER_INTERVAL_SECONDS", "0.5"))
RECONNECT_BASE_SECONDS = float(os.getenv("HAR_BLE_RECONNECT_BASE_SECONDS", "1.0"))
RECONNECT_MAX_SECONDS = float(os.getenv("HAR_BLE_RECONNECT_MAX_SECONDS", "10.0"))
SYNC_WRITE_TIMEOUT_SECONDS = float(os.getenv("HAR_BLE_SYNC_WRITE_TIMEOUT_SECONDS", "2.0"))


def clear_console():
    print("\n" * 40)


def load_registry(path: Path) -> dict[int, dict[str, object]]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    nodes = raw.get("nodes", [])
    registry = {}
    for row in nodes:
        node_id = int(row["id"])
        registry[node_id] = {
            "id": node_id,
            "name": str(row["name"]),
            "mac": str(row["mac"]),
        }
    return registry


def choose_nodes(registry: dict[int, dict[str, object]]) -> list[int]:
    env_nodes = os.getenv("HAR_ACTIVE_NODES", "").strip()
    available = sorted(registry.keys())
    if not env_nodes:
        return available

    chosen = []
    for part in env_nodes.split(","):
        try:
            node_id = int(part.strip())
        except ValueError:
            continue
        if node_id in registry:
            chosen.append(node_id)
    chosen = sorted(set(chosen))
    return chosen or available


def backend_post(path: str, payload: dict, timeout: float = 1.0):
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
    except Exception as exc:  # pragma: no cover - defensive
        return False, str(exc)


class AsyncBackendStatusReporter:
    def __init__(self):
        self._cache: dict[int, tuple] = {}
        self._queue: asyncio.Queue[dict] = asyncio.Queue()

    def __call__(self, payload: dict[str, object]) -> None:
        payload = dict(payload)
        key = payload["id"]
        fingerprint = tuple(sorted(payload.items()))
        if self._cache.get(key) == fingerprint:
            return
        self._cache[key] = fingerprint
        self._queue.put_nowait(payload)

    async def run(self) -> None:
        while True:
            payload = await self._queue.get()
            ok, result = await asyncio.to_thread(
                backend_post,
                f"/esp-status/{payload['id']}",
                payload,
                1.0,
            )
            if ok:
                print(
                    f"[BACKEND] Node {payload['id']}: {payload.get('state')} "
                    f"(seq={payload.get('lastSeq')}, missed={payload.get('missedPackets')})"
                )
            else:
                print(f"[BACKEND] Failed to update node {payload['id']}: {result}")


def predict_combined_window(active_nodes, node_windows):
    payload = {
        "node_ids": list(active_nodes),
        "windows_by_node": {
            str(node_id): readings for node_id, readings in node_windows.items()
        },
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


def print_table(hub: SoftTDMAHub, active_nodes, registry):
    clear_console()
    print("===== TDMA Sensor Dashboard (BLE INPUT / REAL PREDICTION) =====")
    print(
        f"Soft TDMA: superframe={SUPERFRAME_MS}ms, sync lead={SYNC_LEAD_MS}ms, "
        f"slot={NODE_SLOT_MS}ms, predict interval={PREDICT_MIN_INTERVAL_SECONDS:.1f}s"
    )
    print(
        f"Predicted label : {hub.prediction_state.get('label', 'WAITING')} "
        f"({hub.prediction_state.get('confidence', '-')}) [BACKEND]"
    )
    print()
    header = (
        "Node | Name         | State        | Seen(ms) | Seq    | Miss | "
        "MILLISEC |  accX    accY    accZ  |  gyroX   gyroY   gyroZ"
    )
    print(header)
    print("-" * len(header))

    latest = hub.latest_table_rows()
    for snapshot in hub.status_snapshots():
        node_id = snapshot["id"]
        if node_id not in active_nodes:
            continue
        seen = "---" if snapshot["lastSeenMs"] is None else f"{snapshot['lastSeenMs']:7d}"
        name = str(registry[node_id]["name"])[:12]
        data = latest.get(node_id)
        if data is None:
            print(
                f"  {node_id:2d} | {name:<12} | {snapshot['state']:<12} | {seen} | "
                f"{snapshot['lastSeq']:6d} | {snapshot['missedPackets']:4d} |"
                "   ---   |   ---    ---    --- |   ---    ---    ---"
            )
            continue
        t_ms, ax_mg, ay_mg, az_mg, gx_milli, gy_milli, gz_milli = scientific_row(data)
        print(
            f"  {node_id:2d} | {name:<12} | {snapshot['state']:<12} | {seen} | "
            f"{snapshot['lastSeq']:6d} | {snapshot['missedPackets']:4d} | {t_ms:7d} | "
            f"{ax_mg:6d} {ay_mg:6d} {az_mg:6d} | {gx_milli:6d} {gy_milli:6d} {gz_milli:6d}"
        )


async def maybe_predict_async(hub: SoftTDMAHub, active_nodes, now: float) -> bool:
    if (now - hub.last_predict_monotonic) < PREDICT_MIN_INTERVAL_SECONDS:
        return False
    windows = hub.build_prediction_windows()
    if windows is None:
        return False
    ok, result = await asyncio.to_thread(predict_combined_window, active_nodes, windows)
    hub.record_prediction_result(ok, result, now)
    return ok


async def ble_node_worker(
    node_id: int,
    registry_entry: dict[str, object],
    hub: SoftTDMAHub,
) -> None:
    if BleakClient is None:
        raise RuntimeError(
            "bleak is not installed. Install dependencies from Hardware/RaspberryPi/requirements-ble.txt"
        )

    mac = str(registry_entry["mac"])
    loop = asyncio.get_running_loop()
    backoff = RECONNECT_BASE_SECONDS

    while True:
        hub.mark_joining(node_id, address=(mac, 0))

        def handle_disconnect(_client):
            loop.call_soon_threadsafe(hub.mark_disconnected, node_id, "BLE link dropped")

        try:
            async with BleakClient(mac, disconnected_callback=handle_disconnect) as client:
                def handle_stream(_characteristic, data):
                    try:
                        hub.handle_packet(bytes(data), addr=(mac, 0))
                    except ProtocolError as exc:
                        hub.mark_transport_error(
                            node_id, f"Protocol error: {exc}", disconnected=False
                        )

                await client.start_notify(STREAM_CHAR_UUID, handle_stream)
                next_sync_at = time.monotonic()
                backoff = RECONNECT_BASE_SECONDS

                while client.is_connected:
                    now = time.monotonic()
                    if now >= next_sync_at:
                        sync_packet = hub.build_sync_packet(node_id)
                        await asyncio.wait_for(
                            client.write_gatt_char(CONTROL_CHAR_UUID, sync_packet, response=True),
                            timeout=SYNC_WRITE_TIMEOUT_SECONDS,
                        )
                        next_sync_at += SUPERFRAME_SECONDS
                        if next_sync_at < now:
                            next_sync_at = now + SUPERFRAME_SECONDS
                    await asyncio.sleep(0.01)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            hub.mark_transport_error(node_id, str(exc), disconnected=True)
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2.0, RECONNECT_MAX_SECONDS)
        else:
            hub.mark_disconnected(node_id, "BLE link closed")
            await asyncio.sleep(backoff)


def mark_all_disconnected(reporter, active_nodes):
    for node_id in active_nodes:
        reporter(
            {
                "id": node_id,
                "transport": "ble",
                "isConnected": False,
                "state": "disconnected",
                "lastSeenMs": None,
                "lastSeq": 0,
                "missedPackets": 0,
                "bootId": None,
                "firmwareVersion": None,
                "lastError": "hub shutdown",
            }
        )


async def main() -> None:
    registry = load_registry(REGISTRY_PATH)
    active_nodes = choose_nodes(registry)
    print(f"Using BLE nodes: {active_nodes}")
    print(f"Registry path: {REGISTRY_PATH}")
    print(f"BLE service UUID: {HAR_SERVICE_UUID}")

    reporter = AsyncBackendStatusReporter()
    hub = SoftTDMAHub(active_nodes, transport_name="ble", status_callback=reporter)

    reporter_task = asyncio.create_task(reporter.run(), name="backend-status-reporter")
    node_tasks = [
        asyncio.create_task(
            ble_node_worker(node_id, registry[node_id], hub),
            name=f"ble-node-{node_id}",
        )
        for node_id in active_nodes
    ]

    next_render_at = time.monotonic()

    try:
        while True:
            now = time.monotonic()
            hub.refresh_states(now)
            hub.maybe_emit_streaming_status(now)
            await maybe_predict_async(hub, active_nodes, now)

            if now >= next_render_at:
                print_table(hub, active_nodes, registry)
                next_render_at = now + RENDER_INTERVAL_SECONDS

            await asyncio.sleep(0.05)
    except KeyboardInterrupt:
        print("\nStopping BLE TDMA hub...")
    finally:
        for task in node_tasks:
            task.cancel()
        await asyncio.gather(*node_tasks, return_exceptions=True)
        mark_all_disconnected(reporter, active_nodes)
        await asyncio.sleep(0.2)
        reporter_task.cancel()
        await asyncio.gather(reporter_task, return_exceptions=True)


if __name__ == "__main__":
    asyncio.run(main())

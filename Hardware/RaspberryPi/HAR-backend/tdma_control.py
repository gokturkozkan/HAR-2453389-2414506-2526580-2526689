import json
import os
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Tuple

from database import db_get, db_run


RASPBERRY_PI_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

if RASPBERRY_PI_DIR not in sys.path:
    sys.path.insert(0, RASPBERRY_PI_DIR)

try:
    import serial  # type: ignore
except Exception as exc:  # pragma: no cover - depends on Raspberry Pi runtime
    serial = None  # type: ignore
    SERIAL_IMPORT_ERROR = exc
else:
    SERIAL_IMPORT_ERROR = None

try:
    import tdma_hub as hub  # type: ignore
except Exception as exc:  # pragma: no cover - depends on Raspberry Pi runtime
    hub = None  # type: ignore
    HUB_IMPORT_ERROR = exc
else:
    HUB_IMPORT_ERROR = None


DEFAULT_NODE_PORTS = {
    1: "/dev/rfcomm0",
    2: "/dev/rfcomm1",
    3: "/dev/rfcomm2",
}

DEFAULT_NODE_NAMES = {
    1: "wrist",
    2: "chest",
    3: "ankle",
}

NODE_MACS = {
    1: os.getenv("TDMA_NODE_1_MAC", "08:A6:F7:47:4C:CE"),
    2: os.getenv("TDMA_NODE_2_MAC", "08:D1:F9:DF:D7:BA"),
    3: os.getenv("TDMA_NODE_3_MAC", "08:A6:F7:47:43:72"),
}

NODE_PORTS = getattr(hub, "NODE_PORTS", DEFAULT_NODE_PORTS)
NODE_NAMES = getattr(hub, "NODE_NAMES", DEFAULT_NODE_NAMES)
BAUDRATE = getattr(hub, "BAUDRATE", 115200)


def read_int_env(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except ValueError:
        return default


def read_float_env(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except ValueError:
        return default


PROBE_ATTEMPTS = max(1, read_int_env("TDMA_PROBE_ATTEMPTS", 5))
PROBE_RETRY_DELAY_SECONDS = max(
    0.0,
    read_float_env("TDMA_PROBE_RETRY_DELAY_SECONDS", 0.15),
)

SENSOR_LOG_PATH = os.getenv(
    "TDMA_SENSOR_LOG_PATH",
    os.path.join(os.path.dirname(__file__), "logs", "tdma_sensor_raw.jsonl"),
)


class TdmaControlError(Exception):
    def __init__(
        self,
        message: str,
        status_code: int = 500,
        node: Optional[Dict[str, Any]] = None,
    ):
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.node = node

    def to_response(self) -> Dict[str, Any]:
        response = {"message": self.message}

        if self.node:
            response["node"] = self.node

        return response


@dataclass
class NodeRuntime:
    node_id: int
    port: str
    name: str
    mac: str
    ser: Any = None
    status: str = "Closed"
    detail: str = ""
    errors: int = 0
    latest_line: str = ""
    latest_sample: Dict[str, Any] = field(default_factory=dict)
    updated_at: str = ""

    def serial_open(self) -> bool:
        return bool(self.ser is not None and getattr(self.ser, "is_open", False))

    def is_connected(self) -> bool:
        return self.serial_open() and self.status in (
            "Open",
            "Ready",
            "Open - no data",
            "Open - unreadable",
        )

    def to_response(self) -> Dict[str, Any]:
        response: Dict[str, Any] = {
            "id": self.node_id,
            "name": self.name,
            "port": self.port,
            "status": self.status,
            "detail": self.detail,
            "isConnected": self.is_connected(),
            "updatedAt": self.updated_at,
        }

        if self.latest_line:
            response["latestLine"] = self.latest_line

        if self.latest_sample:
            response["latestSample"] = self.latest_sample

        return response


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def parse_frame(line: str) -> Optional[Dict[str, Any]]:
    if hub is not None and hasattr(hub, "parse_frame"):
        return hub.parse_frame(line)

    parts = [part.strip() for part in line.split(",")]

    if len(parts) < 8:
        return None

    try:
        node_id = int(parts[0])

        if node_id not in DEFAULT_NODE_PORTS:
            return None

        values = {
            "node_id": node_id,
            "t": int(float(parts[1])),
            "ax": float(parts[2]),
            "ay": float(parts[3]),
            "az": float(parts[4]),
            "gx": float(parts[5]),
            "gy": float(parts[6]),
            "gz": float(parts[7]),
            "mx": float(parts[8]) if len(parts) > 8 else 0.0,
            "my": float(parts[9]) if len(parts) > 9 else 0.0,
            "mz": float(parts[10]) if len(parts) > 10 else 0.0,
        }
    except Exception:
        return None

    return values


def write_sensor_log(status: str, **metadata: Any) -> None:
    if hub is not None and hasattr(hub, "write_sensor_log"):
        hub.write_sensor_log(status, **metadata)
        return

    try:
        log_path = os.path.abspath(SENSOR_LOG_PATH)
        os.makedirs(os.path.dirname(log_path), exist_ok=True)

        entry = {
            "timestamp": utc_now_iso(),
            "status": status,
            **metadata,
        }

        with open(log_path, "a", encoding="utf-8") as log_file:
            log_file.write(json.dumps(entry, ensure_ascii=False, default=str))
            log_file.write("\n")
    except Exception as error:  # pragma: no cover - best effort diagnostics
        print(f"[WARN] Failed to write TDMA sensor log: {error}", flush=True)


class TdmaBackendController:
    def __init__(self) -> None:
        self.lock = threading.RLock()
        self.nodes = {
            node_id: NodeRuntime(
                node_id=node_id,
                port=NODE_PORTS[node_id],
                name=NODE_NAMES[node_id],
                mac=NODE_MACS[node_id],
            )
            for node_id in (1, 2, 3)
        }

    def get_status(self, node_id: int) -> Dict[str, Any]:
        node = self._node_or_error(node_id)

        with self.lock:
            return node.to_response()

    def connect_node(self, node_id: int) -> Dict[str, Any]:
        node = self._node_or_error(node_id)

        with self.lock:
            if node.serial_open():
                self._set_node_status(node, node.status, "Already open")
                self._set_database_status(node_id, True)
                return node.to_response()

            self._set_node_status(node, "Opening", f"Opening {node.port}")

        try:
            ser = self._open_serial(node)
        except Exception as first_error:
            self._set_node_status(node, "Open failed", str(first_error))
            write_sensor_log(
                "backend_open_error",
                node_id=node_id,
                port=node.port,
                error=repr(first_error),
            )

            if serial is None:
                self._set_database_status(node_id, False)
                raise TdmaControlError(
                    f"Node {node_id} open failed: {first_error}",
                    status_code=503,
                    node=node.to_response(),
                )

            self.bluetooth_connect_node(node_id)
            time.sleep(0.5)
            self.rebind_one_node(node_id)
            time.sleep(0.2)

            try:
                ser = self._open_serial(node)
            except Exception as retry_error:
                with self.lock:
                    node.errors += 1
                    self._set_node_status(node, "Open failed", str(retry_error))

                self._set_database_status(node_id, False)
                write_sensor_log(
                    "backend_open_retry_error",
                    node_id=node_id,
                    port=node.port,
                    error=repr(retry_error),
                    first_error=repr(first_error),
                )
                raise TdmaControlError(
                    f"Node {node_id} open failed: {retry_error}",
                    status_code=503,
                    node=node.to_response(),
                )

        with self.lock:
            node.ser = ser
            self._set_node_status(node, "Open", "Serial opened; probing once.")

        self._set_database_status(node_id, True)
        write_sensor_log("backend_connect", node_id=node_id, port=node.port)

        return self.probe_node(node_id)

    def disconnect_node(self, node_id: int) -> Dict[str, Any]:
        node = self._node_or_error(node_id)

        self.close_node_serial(node_id)
        self._set_database_status(node_id, False)
        write_sensor_log("backend_disconnect", node_id=node_id, port=node.port)

        with self.lock:
            return node.to_response()

    def reconnect_node(self, node_id: int) -> Dict[str, Any]:
        node = self._node_or_error(node_id)

        self.close_node_serial(node_id)
        self._set_database_status(node_id, False)
        self._set_node_status(node, "Closed", "Reconnecting...")
        write_sensor_log("backend_reconnect", node_id=node_id, port=node.port)

        self.rebind_one_node(node_id)
        time.sleep(0.2)

        return self.connect_node(node_id)

    def probe_node(self, node_id: int) -> Dict[str, Any]:
        node = self._node_or_error(node_id)
        latest_unreadable_line = ""

        for attempt in range(1, PROBE_ATTEMPTS + 1):
            try:
                line = self.request_line(node_id)
            except Exception as error:
                with self.lock:
                    node.errors += 1
                    self._set_node_status(node, "Probe failed", str(error))

                self._set_database_status(node_id, False)
                write_sensor_log(
                    "backend_probe_error",
                    node_id=node_id,
                    port=node.port,
                    attempt=attempt,
                    attempts=PROBE_ATTEMPTS,
                    error=repr(error),
                )
                raise TdmaControlError(
                    f"Node {node_id} probe failed: {error}",
                    status_code=503,
                    node=node.to_response(),
                )

            if not line:
                write_sensor_log(
                    "backend_probe_empty",
                    node_id=node_id,
                    port=node.port,
                    attempt=attempt,
                    attempts=PROBE_ATTEMPTS,
                )

                if attempt < PROBE_ATTEMPTS:
                    time.sleep(PROBE_RETRY_DELAY_SECONDS)

                continue

            parsed = parse_frame(line)
            write_sensor_log(
                "backend_probe_raw",
                node_id=node_id,
                port=node.port,
                attempt=attempt,
                attempts=PROBE_ATTEMPTS,
                line=line,
            )

            with self.lock:
                node.latest_line = line
                node.latest_sample = parsed or {}

                if parsed:
                    self._set_node_status(
                        node,
                        "Ready",
                        f"Initial sample received after {attempt} probe attempt(s).",
                    )
                    self._set_database_status(node_id, True)
                    return node.to_response()

                latest_unreadable_line = line
                self._set_node_status(node, "Open - unreadable", line)

            if attempt < PROBE_ATTEMPTS:
                time.sleep(PROBE_RETRY_DELAY_SECONDS)

        with self.lock:
            if latest_unreadable_line:
                self._set_node_status(node, "Open - unreadable", latest_unreadable_line)
            else:
                self._set_node_status(
                    node,
                    "Open - no data",
                    f"No line returned after {PROBE_ATTEMPTS} probe attempt(s). Connection kept open.",
                )

        self._set_database_status(node_id, True)
        return node.to_response()

    def close_all(self) -> None:
        for node_id in list(self.nodes):
            try:
                self.close_node_serial(node_id)
                self._set_database_status(node_id, False)
            except Exception:
                pass

    def rebind_rfcomm(self) -> Dict[str, Any]:
        self.close_all()

        for node in self.nodes.values():
            self._set_node_status(
                node,
                "Rebinding",
                f"{node.port} | {node.mac}",
            )

        script = os.path.join(RASPBERRY_PI_DIR, "rfcommstarter.sh")
        write_sensor_log("backend_rfcomm_rebind_all", script=script)

        try:
            code, output = self._run_command(("bash", script), timeout=25)
        except Exception as error:
            for node in self.nodes.values():
                self._set_node_status(node, "Rebind failed", str(error))

            write_sensor_log(
                "backend_rfcomm_rebind_all_error",
                script=script,
                error=repr(error),
            )
            raise TdmaControlError(
                f"rfcomm rebind failed: {error}",
                status_code=503,
            )

        status = "Rebound" if code == 0 else "Rebind failed"
        detail = output.strip().splitlines()[-1] if output.strip() else f"exit code {code}"

        for node in self.nodes.values():
            self._set_node_status(node, status, f"{node.port} | {node.mac} | {detail}")
            self._set_database_status(node.node_id, False)

        write_sensor_log(
            "backend_rfcomm_rebind_all_done",
            script=script,
            return_code=code,
            output=output,
        )

        return {
            "message": "rfcomm rebind completed",
            "returnCode": code,
            "output": output,
            "nodes": [
                self.nodes[node_id].to_response()
                for node_id in sorted(self.nodes)
            ],
        }

    def close_node_serial(self, node_id: int) -> None:
        node = self._node_or_error(node_id)

        with self.lock:
            ser = node.ser
            node.ser = None
            node.latest_line = ""
            node.latest_sample = {}
            self._set_node_status(node, "Closed", f"Port: {node.port}")

        try:
            if ser is not None and getattr(ser, "is_open", False):
                ser.close()
        except Exception as error:
            write_sensor_log(
                "backend_close_error",
                node_id=node_id,
                port=node.port,
                error=repr(error),
            )

    def request_line(self, node_id: int) -> str:
        node = self._node_or_error(node_id)

        with self.lock:
            ser = node.ser

            if ser is None or not getattr(ser, "is_open", False):
                raise RuntimeError("serial is not open")

            ser.write(b"R")
            raw_line = ser.readline()

        if isinstance(raw_line, bytes):
            return raw_line.decode(errors="ignore").strip()

        return str(raw_line or "").strip()

    def bluetooth_connect_node(self, node_id: int) -> bool:
        node = self._node_or_error(node_id)

        try:
            code, output = self._run_command(
                ["timeout", "12s", "bluetoothctl", "connect", node.mac],
                timeout=15,
            )
        except Exception as error:
            self._set_node_status(node, "BT connect failed", str(error))
            write_sensor_log(
                "backend_bt_connect_error",
                node_id=node_id,
                mac=node.mac,
                error=repr(error),
            )
            return False

        write_sensor_log(
            "backend_bt_connect",
            node_id=node_id,
            mac=node.mac,
            return_code=code,
            output=output,
        )

        if "Connection successful" in output or "Connected: yes" in output:
            self._set_node_status(node, "BT connected", node.mac)
            return True

        if "Failed to connect" in output or code != 0:
            detail = output.splitlines()[-1] if output.splitlines() else output
            self._set_node_status(node, "BT connect failed", detail)
            return False

        self._set_node_status(node, "BT connect attempted", node.mac)
        return True

    def rebind_one_node(self, node_id: int) -> Dict[str, Any]:
        node = self._node_or_error(node_id)
        index = node_id - 1

        self.close_node_serial(node_id)
        self._set_node_status(node, "Rebinding", f"rfcomm{index} -> {node.mac}")

        commands = [
            ["sudo", "rfcomm", "release", str(index)],
            ["sudo", "rfcomm", "bind", str(index), node.mac, "1"],
        ]

        command_results = []

        for command in commands:
            try:
                code, output = self._run_command(command, timeout=10)
            except Exception as error:
                code = -1
                output = str(error)

            command_results.append(
                {
                    "command": " ".join(command),
                    "returnCode": code,
                    "output": output,
                }
            )

        write_sensor_log(
            "backend_rfcomm_rebind",
            node_id=node_id,
            port=node.port,
            mac=node.mac,
            commands=command_results,
        )
        self._set_node_status(node, "Rebound", f"{node.port} | {node.mac}")

        return node.to_response()

    def _open_serial(self, node: NodeRuntime) -> Any:
        if serial is None:
            reason = (
                f"pyserial import failed: {SERIAL_IMPORT_ERROR}"
                if SERIAL_IMPORT_ERROR
                else "pyserial is not available"
            )
            raise RuntimeError(reason)

        ser = serial.Serial(
            node.port,
            BAUDRATE,
            timeout=0.25,
            write_timeout=0.35,
        )
        time.sleep(0.15)

        try:
            ser.reset_input_buffer()
            ser.reset_output_buffer()
        except Exception:
            pass

        return ser

    def _run_command(self, command: Tuple[str, ...], timeout: int = 15) -> Tuple[int, str]:
        proc = subprocess.run(
            list(command),
            cwd=RASPBERRY_PI_DIR,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return proc.returncode, (proc.stdout or "") + (proc.stderr or "")

    def _node_or_error(self, node_id: int) -> NodeRuntime:
        node = self.nodes.get(node_id)

        if not node:
            raise TdmaControlError(
                f"TDMA node {node_id} is not configured. Expected one of 1, 2, 3.",
                status_code=404,
            )

        return node

    def _set_node_status(self, node: NodeRuntime, status: str, detail: str = "") -> None:
        node.status = status
        node.detail = detail or ""
        node.updated_at = utc_now_iso()

    def _set_database_status(self, node_id: int, is_connected: bool) -> None:
        try:
            exists = db_get("SELECT id FROM esp_devices WHERE id = ?", [node_id])

            if exists:
                db_run(
                    "UPDATE esp_devices SET is_connected = ? WHERE id = ?",
                    [1 if is_connected else 0, node_id],
                )
            else:
                db_run(
                    "INSERT INTO esp_devices (id, is_connected) VALUES (?, ?)",
                    [node_id, 1 if is_connected else 0],
                )
        except Exception as error:
            write_sensor_log(
                "backend_status_db_error",
                node_id=node_id,
                is_connected=is_connected,
                error=repr(error),
            )

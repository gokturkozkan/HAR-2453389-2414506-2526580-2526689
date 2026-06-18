import json
import os
import subprocess
import sys
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

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
FRAME_PERIOD = getattr(hub, "FRAME_PERIOD", 0.1)
WINDOW_SIZE = getattr(hub, "WINDOW_SIZE", 200)
PREDICT_EVERY = getattr(hub, "PREDICT_EVERY", 10)
FEATURE_KEYS = getattr(
    hub,
    "FEATURE_KEYS",
    ("ax", "ay", "az", "gx", "gy", "gz", "mx", "my", "mz"),
)


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
            "Receiving",
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
        self.receiving = False
        self.receiver_thread: Optional[threading.Thread] = None
        self.nodes = {
            node_id: NodeRuntime(
                node_id=node_id,
                port=NODE_PORTS[node_id],
                name=NODE_NAMES[node_id],
                mac=NODE_MACS[node_id],
            )
            for node_id in (1, 2, 3)
        }
        self.node_windows = {
            node_id: deque(maxlen=WINDOW_SIZE)
            for node_id in self.nodes
        }
        self.resample_seconds = max(
            0.1,
            read_float_env("PAMAP2_RESAMPLE_SECONDS", 6.0),
        )
        self.min_resample_seconds = max(
            0.0,
            read_float_env("PAMAP2_MIN_RESAMPLE_SECONDS", 2.5),
        )
        self.min_raw_samples = max(1, read_int_env("PAMAP2_MIN_RAW_SAMPLES", 8))
        self.rows_since_prediction = 0
        self.latest_prediction: Dict[str, Any] = {}
        self.window_status = f"0.0s/{self.resample_seconds:.1f}s"

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

    def start_receiving(self) -> Dict[str, Any]:
        with self.lock:
            if self.receiving:
                return {
                    "message": "Receiving is already running",
                    "receiving": True,
                    "prediction": self.latest_prediction,
                    "windowStatus": self.window_status,
                    "nodes": self._nodes_response_locked(),
                }

            self._clear_prediction_window_locked()
            self.receiving = True
            thread = threading.Thread(target=self.receive_loop, daemon=True)
            self.receiver_thread = thread

        thread.start()
        write_sensor_log("backend_receiving_start")

        with self.lock:
            return {
                "message": "Receiving started",
                "receiving": True,
                "prediction": self.latest_prediction,
                "windowStatus": self.window_status,
                "nodes": self._nodes_response_locked(),
            }

    def stop_receiving(self) -> Dict[str, Any]:
        with self.lock:
            if not self.receiving:
                return {
                    "message": "Receiving is already stopped",
                    "receiving": False,
                    "prediction": self.latest_prediction,
                    "windowStatus": self.window_status,
                    "nodes": self._nodes_response_locked(),
                }

            self.receiving = False
            thread = self.receiver_thread

        if thread and thread is not threading.current_thread():
            thread.join(timeout=1.0)

        with self.lock:
            self.receiver_thread = None
            nodes = self._nodes_response_locked()

        write_sensor_log("backend_receiving_stop")

        return {
            "message": "Receiving stopped",
            "receiving": False,
            "prediction": self.latest_prediction,
            "windowStatus": self.window_status,
            "nodes": nodes,
        }

    def receive_loop(self) -> None:
        while True:
            with self.lock:
                is_receiving = self.receiving

            if not is_receiving:
                break

            frame_start = time.perf_counter()

            for node_id in (1, 2, 3):
                with self.lock:
                    if not self.receiving:
                        break

                    node = self.nodes[node_id]
                    ser_open = node.serial_open()

                if not ser_open:
                    continue

                try:
                    line = self.request_line(node_id)
                except Exception as error:
                    with self.lock:
                        node.errors += 1
                        self._set_node_status(node, "Read failed", str(error))

                    self._set_database_status(node_id, False)
                    write_sensor_log(
                        "backend_read_error",
                        node_id=node_id,
                        port=node.port,
                        error=repr(error),
                    )
                    continue

                if not line:
                    write_sensor_log(
                        "backend_read_empty",
                        node_id=node_id,
                        port=node.port,
                    )
                    continue

                parsed = parse_frame(line)
                write_sensor_log(
                    "backend_raw_sample",
                    node_id=node_id,
                    port=node.port,
                    line=line,
                )

                if not parsed:
                    with self.lock:
                        node.latest_line = line
                        node.latest_sample = {}
                        self._set_node_status(node, "Open - unreadable", line)
                    continue

                if hub is not None and hasattr(hub, "calibrate_node_sample"):
                    parsed = hub.calibrate_node_sample(parsed)

                self.append_window(parsed)

                with self.lock:
                    should_update_database = node.status != "Receiving"
                    node.latest_line = line
                    node.latest_sample = parsed
                    self._set_node_status(node, "Receiving", "Receiving samples.")

                if should_update_database:
                    self._set_database_status(node_id, True)

            try:
                self.maybe_predict()
            except Exception as error:
                write_sensor_log(
                    "backend_prediction_loop_error",
                    error=repr(error),
                )

            elapsed = time.perf_counter() - frame_start
            time.sleep(max(0.02, FRAME_PERIOD - elapsed))

    def append_window(self, parsed: Dict[str, Any]) -> None:
        node_id = int(parsed.get("node_id", 0))

        if node_id not in self.node_windows:
            return

        sample = {
            key: float(parsed.get(key, 0.0))
            for key in FEATURE_KEYS
        }
        sample["_host_time"] = time.monotonic()

        with self.lock:
            self.node_windows[node_id].append(sample)

    def get_resample_status(self) -> Tuple[bool, str, Optional[float], Dict[int, List[Dict[str, Any]]]]:
        with self.lock:
            windows = {
                node_id: list(self.node_windows[node_id])
                for node_id in (1, 2, 3)
            }

        if any(not windows[node_id] for node_id in (1, 2, 3)):
            counts = [len(windows[node_id]) for node_id in (1, 2, 3)]
            status = f"raw {min(counts)}/{self.min_raw_samples}"

            with self.lock:
                self.window_status = status

            return False, status, None, {}

        common_end = min(
            readings[-1].get("_host_time", 0.0)
            for readings in windows.values()
        )
        cutoff = common_end - self.resample_seconds
        recent_by_node: Dict[int, List[Dict[str, Any]]] = {}
        spans = []
        counts = []

        for node_id, readings in windows.items():
            recent = [
                reading
                for reading in readings
                if cutoff <= reading.get("_host_time", 0.0) <= common_end
            ]
            recent_by_node[node_id] = recent
            counts.append(len(recent))

            if recent:
                spans.append(recent[-1]["_host_time"] - recent[0]["_host_time"])
            else:
                spans.append(0.0)

        min_count = min(counts) if counts else 0
        min_span = min(spans) if spans else 0.0
        ready = min_count >= self.min_raw_samples and min_span >= self.min_resample_seconds
        status = (
            f"{min(min_span, self.resample_seconds):.1f}s/{self.resample_seconds:.1f}s "
            f"({min_count} raw)"
        )

        with self.lock:
            self.window_status = status

        return ready, status, common_end, recent_by_node

    def resample_node_readings(
        self,
        readings: List[Dict[str, Any]],
        common_end: float,
    ) -> List[Dict[str, float]]:
        cutoff = common_end - self.resample_seconds
        ordered = sorted(
            (
                reading
                for reading in readings
                if cutoff <= reading.get("_host_time", 0.0) <= common_end
            ),
            key=lambda reading: reading.get("_host_time", 0.0),
        )

        if not ordered:
            raise ValueError("No readings available for resampling")

        if len(ordered) == 1:
            return [
                {key: float(ordered[0].get(key, 0.0)) for key in FEATURE_KEYS}
                for _ in range(WINDOW_SIZE)
            ]

        target_times = [
            cutoff + (self.resample_seconds * index / (WINDOW_SIZE - 1))
            for index in range(WINDOW_SIZE)
        ]
        result = []
        source_index = 0

        for target_time in target_times:
            while (
                source_index < len(ordered) - 2
                and ordered[source_index + 1].get("_host_time", 0.0) < target_time
            ):
                source_index += 1

            left = ordered[source_index]
            right = ordered[min(source_index + 1, len(ordered) - 1)]
            left_time = left.get("_host_time", 0.0)
            right_time = right.get("_host_time", left_time)

            if target_time <= left_time or right_time <= left_time:
                ratio = 0.0
            elif target_time >= right_time:
                ratio = 1.0
            else:
                ratio = (target_time - left_time) / (right_time - left_time)

            result.append({
                key: (
                    float(left.get(key, 0.0))
                    + (float(right.get(key, 0.0)) - float(left.get(key, 0.0))) * ratio
                )
                for key in FEATURE_KEYS
            })

        return result

    def build_resampled_windows_by_node(self) -> Dict[str, List[Dict[str, float]]]:
        ready, status, common_end, recent_by_node = self.get_resample_status()

        if not ready or common_end is None:
            raise ValueError(f"Prediction window is not ready: {status}")

        return {
            str(node_id): self.resample_node_readings(recent_by_node[node_id], common_end)
            for node_id in (1, 2, 3)
        }

    def build_prediction_payload(self) -> Dict[str, Any]:
        node_order = tuple(getattr(hub, "PAMAP2_NODE_ORDER", (1, 2, 3)))
        axis_transform = getattr(hub, "PAMAP2_AXIS_TRANSFORM", "+x+y+z")
        node_axis_transforms = getattr(
            hub,
            "PAMAP2_NODE_AXIS_TRANSFORMS",
            {node_id: axis_transform for node_id in (1, 2, 3)},
        )
        mag_mode = getattr(hub, "PAMAP2_MAG_MODE", "raw")

        return {
            "node_order": list(node_order),
            "axis_transform": axis_transform,
            "node_axis_transforms": {
                str(node_id): node_axis
                for node_id, node_axis in node_axis_transforms.items()
            },
            "mag_mode": mag_mode,
            "order_sweep": False,
            "use_live_calibration": False,
            "windows_by_node": self.build_resampled_windows_by_node(),
            "resampled_window": {
                "source": "backend_recent_seconds",
                "seconds": self.resample_seconds,
                "model_timesteps": WINDOW_SIZE,
            },
        }

    def maybe_predict(self, force: bool = False) -> None:
        ready, status, _, _ = self.get_resample_status()

        if not ready:
            if force:
                write_sensor_log("backend_prediction_not_ready", window_status=status)
            return

        if not force:
            self.rows_since_prediction += 1

        if not force and self.rows_since_prediction < PREDICT_EVERY:
            return

        self.rows_since_prediction = 0
        prediction_id = self._make_prediction_id()
        payload = self.build_prediction_payload()

        try:
            result = self.post_prediction_payload(payload, prediction_id)
        except Exception as error:
            write_sensor_log(
                "backend_prediction_error",
                prediction_id=prediction_id,
                window_status=self.window_status,
                error=repr(error),
            )
            return

        with self.lock:
            self.latest_prediction = result

    def post_prediction_payload(
        self,
        payload: Dict[str, Any],
        prediction_id: str,
    ) -> Dict[str, Any]:
        from routes import activity as activity_module

        started_at = time.perf_counter()
        payload_summary = (
            hub.summarize_predict_payload(payload)
            if hub is not None and hasattr(hub, "summarize_predict_payload")
            else {}
        )

        if hub is not None and hasattr(hub, "write_prediction_log"):
            hub.write_prediction_log(
                "request",
                prediction_id=prediction_id,
                source="backend_tdma_auto",
                node_order=payload.get("node_order"),
                axis_transform=payload.get("axis_transform"),
                node_axis_transforms=payload.get("node_axis_transforms"),
                mag_mode=payload.get("mag_mode"),
                payload_summary=payload_summary,
            )

        (
            node_order,
            axis_transform,
            node_axis_transforms,
            mag_mode,
            forced_identity_preprocess,
        ) = activity_module.resolve_prediction_preprocess(
            payload.get("node_order"),
            payload.get("axis_transform"),
            payload.get("node_axis_transforms"),
            payload.get("mag_mode"),
        )
        validated_windows = activity_module.validate_windows_by_node(
            payload.get("windows_by_node")
        )
        prediction_result = activity_module.predict_activity(
            validated_windows,
            node_order=node_order,
            axis_transform=axis_transform,
            node_axis_transforms=node_axis_transforms,
            mag_mode=mag_mode,
        )

        if len(prediction_result) == 2:
            activity, confidence = prediction_result
            prob_map = {}
            top_predictions = [
                {
                    "label": activity,
                    "probability": confidence,
                }
            ]
            model_debug = {}
        else:
            activity, confidence, prob_map, top_predictions, model_debug = prediction_result

        classifier = "pamap2"
        pamap2_activity = activity
        pamap2_confidence = confidence
        use_live_calibration = self._parse_bool(
            payload.get("use_live_calibration"),
            default=False,
        )
        calibrated_result = (
            activity_module.predict_live_calibrated(validated_windows)
            if use_live_calibration
            else None
        )

        if calibrated_result is not None:
            classifier = "live_calibrated"
            activity = calibrated_result["activity"]
            confidence = calibrated_result["confidence"]
            prob_map = calibrated_result["probabilities"]
            top_predictions = calibrated_result["top_predictions"]

        activity_module.upsert_current_label(activity)
        activity_module.remember_latest_combined_window(
            activity_module.NODE_IDS,
            validated_windows,
            activity,
        )

        for node_id, node_readings in validated_windows.items():
            activity_module.remember_latest_window(node_id, node_readings, activity)
            activity_module.mark_esp_connected_if_known(node_id)

        result = {
            "prediction_id": prediction_id,
            "activity": activity,
            "confidence": round(float(confidence), 4),
            "classifier": classifier,
            "pamap2_activity": pamap2_activity,
            "pamap2_confidence": round(float(pamap2_confidence), 4),
            "forced_identity_preprocess": forced_identity_preprocess,
            "node_order": list(node_order),
            "axis_transform": axis_transform,
            "node_axis_transforms": {
                str(node_id): node_axis
                for node_id, node_axis in node_axis_transforms.items()
            },
            "mag_mode": mag_mode,
            "resampled_window": payload.get("resampled_window"),
            "probabilities": {
                label: round(float(probability), 6)
                for label, probability in prob_map.items()
            },
            "top_predictions": top_predictions[:3],
            "model_debug": model_debug,
            "inference_ms": round((time.perf_counter() - started_at) * 1000.0, 2),
        }

        if hub is not None and hasattr(hub, "write_prediction_log"):
            hub.write_prediction_log(
                "success",
                prediction_id=prediction_id,
                source="backend_tdma_auto",
                node_order=result["node_order"],
                axis_transform=axis_transform,
                node_axis_transforms=result["node_axis_transforms"],
                mag_mode=mag_mode,
                latency_ms=result["inference_ms"],
                response=result,
            )

        write_sensor_log(
            "backend_prediction_success",
            prediction_id=prediction_id,
            activity=activity,
            confidence=result["confidence"],
            window_status=self.window_status,
        )

        return result

    def close_all(self) -> None:
        self.stop_receiving()

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

    def _clear_prediction_window_locked(self) -> None:
        self.node_windows = {
            node_id: deque(maxlen=WINDOW_SIZE)
            for node_id in self.nodes
        }
        self.rows_since_prediction = 0
        self.latest_prediction = {}
        self.window_status = f"0.0s/{self.resample_seconds:.1f}s"

    def _make_prediction_id(self) -> str:
        if hub is not None and hasattr(hub, "make_prediction_id"):
            return hub.make_prediction_id()

        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
        return f"tdma-backend-{stamp}"

    def _parse_bool(self, value: Any, default: bool = False) -> bool:
        if value is None:
            return default

        if isinstance(value, bool):
            return value

        return str(value).strip().lower() not in ("", "0", "false", "no", "off")

    def _nodes_response_locked(self) -> List[Dict[str, Any]]:
        return [
            self.nodes[node_id].to_response()
            for node_id in sorted(self.nodes)
        ]

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

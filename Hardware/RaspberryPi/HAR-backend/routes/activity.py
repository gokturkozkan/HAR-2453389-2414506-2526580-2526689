import os
import copy
import json
import joblib
import numpy as np
import tensorflow as tf
from datetime import datetime, timezone

from flask import Blueprint, request, jsonify
from database import db_run, db_get

activity_bp = Blueprint("activity", __name__)


MODEL = None
SCALER = None
LABEL_ENCODER = None

WINDOW_SIZE = 200
NODE_IDS = [1, 2, 3]
COMBINED_KEY = "_combined"
MODEL_PROFILE = "pamap2_basic_keras"

FEATURES_PER_NODE = ("ax", "ay", "az", "gx", "gy", "gz", "mx", "my", "mz")

LATEST_WINDOWS_BY_NODE = {}
LAST_NODE_ID = None


def get_sensor_log_path():
    configured_path = os.getenv("SENSOR_LOG_PATH")

    if configured_path:
        return os.path.abspath(configured_path)

    base_dir = os.path.dirname(__file__)
    return os.path.abspath(os.path.join(base_dir, "..", "logs", "sensor_readings.jsonl"))


def write_sensor_debug_log(payload, status, **metadata):
    try:
        log_path = get_sensor_log_path()
        os.makedirs(os.path.dirname(log_path), exist_ok=True)

        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "status": status,
            "remote_addr": request.remote_addr,
            "model": MODEL_PROFILE,
            "window_size": WINDOW_SIZE,
            "features_per_node": list(FEATURES_PER_NODE),
            "payload": payload,
            **metadata,
        }

        with open(log_path, "a", encoding="utf-8") as log_file:
            log_file.write(json.dumps(entry, ensure_ascii=False, default=str))
            log_file.write("\n")
    except Exception as error:
        print(f"Failed to write sensor debug log: {error}", flush=True)


def load_model():
    global MODEL, SCALER, LABEL_ENCODER

    base_dir = os.path.dirname(__file__)
    model_dir = os.path.abspath(os.path.join(base_dir, "..", "..", "model"))

    model_path = os.path.join(model_dir, "pamap2_basic_har_model.keras")
    scaler_path = os.path.join(model_dir, "pamap2_basic_scaler.pkl")
    label_encoder_path = os.path.join(model_dir, "pamap2_basic_label_encoder.pkl")

    print("model_path exists:", os.path.exists(model_path), model_path)
    print("scaler_path exists:", os.path.exists(scaler_path), scaler_path)
    print("label_encoder_path exists:", os.path.exists(label_encoder_path), label_encoder_path)

    MODEL = tf.keras.models.load_model(model_path)
    SCALER = joblib.load(scaler_path)
    LABEL_ENCODER = joblib.load(label_encoder_path)

    print("PAMAP2 HAR model loaded")
    print("Model input shape:", MODEL.input_shape)
    print("Classes:", list(LABEL_ENCODER.classes_))


def validate_node_readings(readings, node_id):
    if not isinstance(readings, list):
        raise ValueError(f"Node {node_id} readings must be a list")

    if len(readings) != WINDOW_SIZE:
        raise ValueError(
            f"Node {node_id} must have exactly {WINDOW_SIZE} readings, got {len(readings)}"
        )

    for i, reading in enumerate(readings):
        if not isinstance(reading, dict):
            raise ValueError(f"Node {node_id}, reading {i} must be an object")

        for key in FEATURES_PER_NODE:
            if key not in reading:
                raise ValueError(f"Node {node_id}, reading {i} is missing '{key}'")

            try:
                float(reading[key])
            except (TypeError, ValueError):
                raise ValueError(f"Node {node_id}, reading {i} has non-numeric '{key}'")


def validate_windows_by_node(windows_by_node):
    if not isinstance(windows_by_node, dict):
        raise ValueError("windows_by_node must be an object")

    normalized = {}

    for node_id in NODE_IDS:
        readings = windows_by_node.get(str(node_id), windows_by_node.get(node_id))

        if readings is None:
            raise ValueError(f"Missing node {node_id} window")

        validate_node_readings(readings, node_id)
        normalized[node_id] = readings

    return normalized


def build_model_input(windows_by_node):
    rows = []

    for timestep in range(WINDOW_SIZE):
        row = []

        for node_id in NODE_IDS:
            reading = windows_by_node[node_id][timestep]

            for feature in FEATURES_PER_NODE:
                row.append(float(reading[feature]))

        rows.append(row)

    data_array = np.array(rows, dtype=np.float32)

    print("INPUT SHAPE BEFORE SCALER:", data_array.shape, flush=True)
    print("INPUT FIRST ROW:", data_array[0], flush=True)
    print("INPUT LAST ROW:", data_array[-1], flush=True)

    expected_shape = MODEL.input_shape
    expected_timesteps = expected_shape[1]
    expected_features = expected_shape[2]

    if data_array.shape[0] != expected_timesteps:
        raise ValueError(
            f"Window size mismatch. Backend built {data_array.shape[0]} timesteps, "
            f"but model expects {expected_timesteps}."
        )

    if data_array.shape[1] != expected_features:
        raise ValueError(
            f"Feature mismatch. Backend built {data_array.shape[1]} features, "
            f"but model expects {expected_features}."
        )

    data_array = SCALER.transform(data_array)
    data_array = np.nan_to_num(
        data_array,
        nan=0.0,
        posinf=0.0,
        neginf=0.0,
    )
    data_array = np.clip(data_array, -10.0, 10.0)

    model_input = np.expand_dims(data_array, axis=0)

    print("MODEL INPUT SHAPE:", model_input.shape, "EXPECTED:", expected_shape, flush=True)

    return model_input


def predict_activity(windows_by_node):
    if MODEL is None or SCALER is None or LABEL_ENCODER is None:
        raise RuntimeError("Model, scaler, or label encoder not loaded")

    model_input = build_model_input(windows_by_node)

    probs = MODEL.predict(model_input, verbose=0)[0]
    prob_map = {
        str(label): float(prob)
        for label, prob in zip(LABEL_ENCODER.classes_, probs)
    }

    print("\n=== CLASS PROBABILITIES ===", flush=True)
    print(prob_map, flush=True)

    activity_idx = int(np.argmax(probs))
    confidence = float(probs[activity_idx])
    activity = LABEL_ENCODER.inverse_transform([activity_idx])[0]

    return str(activity), confidence


def upsert_current_label(label):
    row = db_get("SELECT id FROM labels WHERE id = 1")

    if row:
        db_run("UPDATE labels SET name = ? WHERE id = 1", [label])
    else:
        db_run("INSERT INTO labels (id, name) VALUES (1, ?)", [label])


def mark_esp_connected_if_known(node_id):
    if node_id is None:
        return

    row = db_get("SELECT id FROM esp_devices WHERE id = ?", [node_id])

    if row:
        db_run("UPDATE esp_devices SET is_connected = 1 WHERE id = ?", [node_id])
    else:
        db_run("INSERT INTO esp_devices (id, is_connected) VALUES (?, 1)", [node_id])


def remember_latest_window(node_id, readings, predicted_label):
    global LAST_NODE_ID

    LATEST_WINDOWS_BY_NODE[node_id] = {
        "node_id": node_id,
        "predicted_label": predicted_label,
        "readings": copy.deepcopy(readings),
    }

    LAST_NODE_ID = node_id


def remember_latest_combined_window(node_ids, windows_by_node, predicted_label):
    global LAST_NODE_ID

    LATEST_WINDOWS_BY_NODE[COMBINED_KEY] = {
        "node_id": None,
        "node_ids": list(node_ids),
        "predicted_label": predicted_label,
        "windows_by_node": copy.deepcopy(windows_by_node),
    }

    LAST_NODE_ID = COMBINED_KEY


def get_latest_window(node_id=None):
    key = node_id if node_id is not None else LAST_NODE_ID

    if key is None:
        return None

    item = LATEST_WINDOWS_BY_NODE.get(key)

    if item is None and node_id is None:
        item = LATEST_WINDOWS_BY_NODE.get(COMBINED_KEY)

    return copy.deepcopy(item) if item is not None else None


def get_all_latest_node_windows():
    windows = []

    for key, value in LATEST_WINDOWS_BY_NODE.items():
        if isinstance(key, int):
            windows.append(copy.deepcopy(value))

    windows.sort(key=lambda item: item.get("node_id", 0))
    return windows


@activity_bp.route("/predict", methods=["POST"])
def predict_endpoint():
    data = None
    windows_by_node = None

    try:
        data = request.get_json(silent=True)

        if data is None:
            write_sensor_debug_log(
                None,
                "invalid_json",
                error="Invalid JSON body",
            )
            return jsonify({"error": "Invalid JSON body"}), 400

        windows_by_node = data.get("windows_by_node")

        if windows_by_node is None:
            write_sensor_debug_log(
                data,
                "missing_windows_by_node",
                received_keys=list(data.keys()),
            )
            return jsonify({
                "error": "windows_by_node is required for the PAMAP2 model",
                "received_keys": list(data.keys()),
            }), 400

        validated_windows = validate_windows_by_node(windows_by_node)

        activity, confidence = predict_activity(validated_windows)

        upsert_current_label(activity)
        remember_latest_combined_window(NODE_IDS, validated_windows, activity)

        for node_id, node_readings in validated_windows.items():
            remember_latest_window(node_id, node_readings, activity)
            mark_esp_connected_if_known(node_id)

        write_sensor_debug_log(
            validated_windows,
            "success",
            used_node_ids=NODE_IDS,
            activity=activity,
            confidence=round(confidence, 4),
        )

        return jsonify({
            "used_node_ids": NODE_IDS,
            "activity": activity,
            "confidence": round(confidence, 4),
            "fusion": "pamap2_3_node_feature_concat",
            "model": MODEL_PROFILE,
            "window_size": WINDOW_SIZE,
            "features_per_node": list(FEATURES_PER_NODE),
        })

    except ValueError as e:
        print("PREDICT 400:", str(e), flush=True)
        write_sensor_debug_log(
            windows_by_node if windows_by_node is not None else data,
            "validation_error",
            error=str(e),
        )
        return jsonify({"error": str(e)}), 400

    except Exception as e:
        import traceback
        print("PREDICT ERROR:", repr(e), flush=True)
        traceback.print_exc()
        write_sensor_debug_log(
            windows_by_node if windows_by_node is not None else data,
            "prediction_error",
            error=str(e),
        )
        return jsonify({"error": str(e)}), 500

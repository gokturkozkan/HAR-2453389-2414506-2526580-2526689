import os
import copy
import joblib
import numpy as np
import tensorflow as tf

from flask import Blueprint, request, jsonify
from database import db_run, db_get

activity_bp = Blueprint("activity", __name__)

MODEL = None
SCALER = None
LABEL_ENCODER = None

WINDOW_SIZE = 200
NODE_IDS = [1, 2, 3]
COMBINED_KEY = "_combined"

FEATURES_PER_NODE = ("ax", "ay", "az", "gx", "gy", "gz", "mx", "my", "mz")

LATEST_WINDOWS_BY_NODE = {}
LAST_NODE_ID = None


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

    print("✓ PAMAP2 HAR model loaded")


def validate_node_readings(readings, node_id):
    if not isinstance(readings, list):
        raise ValueError(f"Node {node_id} readings must be a list")

    if len(readings) != WINDOW_SIZE:
        raise ValueError(f"Node {node_id} must have exactly {WINDOW_SIZE} readings")

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
        key = str(node_id)

        if key not in windows_by_node:
            raise ValueError(f"Missing node {node_id} window")

        readings = windows_by_node[key]
        validate_node_readings(readings, node_id)
        normalized[node_id] = readings

    return normalized


def build_model_input(windows_by_node):
    rows = []

    for t in range(WINDOW_SIZE):
        row = []

        for node_id in NODE_IDS:
            reading = windows_by_node[node_id][t]

            for feature in FEATURES_PER_NODE:
                row.append(float(reading[feature]))

        rows.append(row)

    data_array = np.array(rows, dtype=np.float32)

    print("INPUT SHAPE BEFORE SCALER:", data_array.shape, flush=True)
    print("INPUT FIRST ROW:", data_array[0], flush=True)
    print("INPUT LAST ROW:", data_array[-1], flush=True)

    data_array = SCALER.transform(data_array)
    data_array = np.nan_to_num(data_array, nan=0.0, posinf=0.0, neginf=0.0)
    data_array = np.clip(data_array, -10.0, 10.0)

    return np.expand_dims(data_array, axis=0)


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

    return activity, confidence


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
    try:
        data = request.get_json() or {}

        windows_by_node = data.get("windows_by_node")

        if windows_by_node is None:
            return jsonify({"error": "windows_by_node is required"}), 400

        validated_windows = validate_windows_by_node(windows_by_node)

        activity, confidence = predict_activity(validated_windows)

        upsert_current_label(activity)

        remember_latest_combined_window(NODE_IDS, validated_windows, activity)

        for node_id, node_readings in validated_windows.items():
            remember_latest_window(node_id, node_readings, activity)
            mark_esp_connected_if_known(node_id)

        return jsonify({
            "used_node_ids": NODE_IDS,
            "activity": activity,
            "confidence": round(confidence, 4),
            "fusion": "pamap2_3_node_feature_concat"
        })

    except ValueError as e:
        return jsonify({"error": str(e)}), 400

    except Exception as e:
        import traceback
        print("PREDICT ERROR:", repr(e))
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500
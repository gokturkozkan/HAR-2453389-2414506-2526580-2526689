import os
import copy
import json
import re
import joblib
import numpy as np
import tensorflow as tf
import threading
import time
import uuid
from datetime import datetime, timezone
from itertools import permutations, product

from flask import Blueprint, request, jsonify
from database import db_run, db_get

activity_bp = Blueprint("activity", __name__)


MODEL = None
SCALER = None
LABEL_ENCODER = None
MODEL_PATH = None
SCALER_PATH = None
LABEL_ENCODER_PATH = None

WINDOW_SIZE = 200
NODE_IDS = [1, 2, 3]
COMBINED_KEY = "_combined"
MODEL_PROFILE = os.getenv("HAR_MODEL_PROFILE", "pamap2_basic_keras")

FEATURES_PER_NODE = ("ax", "ay", "az", "gx", "gy", "gz", "mx", "my", "mz")
VECTOR_FEATURE_GROUPS = (
    ("ax", "ay", "az"),
    ("gx", "gy", "gz"),
    ("mx", "my", "mz"),
)
MAG_FEATURES = ("mx", "my", "mz")
AXIS_NAMES = ("x", "y", "z")
AXIS_INDEX = {axis: index for index, axis in enumerate(AXIS_NAMES)}
IDENTITY_AXIS_TRANSFORM = "+x+y+z"
MAG_MODE_OPTIONS = (
    "raw",
    "zero",
    "center",
    "div100",
    "div1000",
    "center_div100",
    "center_div1000",
)
PAMAP2_CALIBRATION_MAG_MODES = ("raw", "zero", "center", "div100", "center_div100")
NODE_ORDER_OPTIONS = tuple(permutations(NODE_IDS))
AXIS_TRANSFORM_OPTIONS = tuple(
    "".join(
        ("+" if sign > 0 else "-") + AXIS_NAMES[index]
        for index, sign in zip(axis_perm, signs)
    )
    for axis_perm in permutations(range(3))
    for signs in product((-1, 1), repeat=3)
)
ORDER_SWEEP_ENABLED = os.getenv("PAMAP2_ORDER_SWEEP", "1") not in ("0", "false", "False")
LIVE_CALIBRATION_ENABLED = os.getenv("HAR_LIVE_CALIBRATION", "1") not in ("0", "false", "False")
LIVE_CALIBRATION_MIN_LABELS = int(os.getenv("HAR_LIVE_CALIBRATION_MIN_LABELS", "2"))

LATEST_WINDOWS_BY_NODE = {}
LAST_NODE_ID = None
PAMAP2_CALIBRATION_SWEEP_LOCK = threading.Lock()


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


def get_prediction_log_path():
    configured_path = os.getenv("PAMAP2_PREDICTION_LOG_PATH")

    if configured_path:
        return os.path.abspath(configured_path)

    base_dir = os.path.dirname(__file__)
    return os.path.abspath(os.path.join(base_dir, "..", "logs", "pamap2_predictions.jsonl"))


def get_live_calibration_path():
    configured_path = os.getenv("HAR_LIVE_CALIBRATION_PATH")

    if configured_path:
        return os.path.abspath(configured_path)

    base_dir = os.path.dirname(__file__)
    return os.path.abspath(os.path.join(base_dir, "..", "logs", "live_calibration.json"))


def get_pamap2_calibration_path():
    configured_path = os.getenv("PAMAP2_CALIBRATION_PATH")

    if configured_path:
        return os.path.abspath(configured_path)

    base_dir = os.path.dirname(__file__)
    return os.path.abspath(os.path.join(base_dir, "..", "logs", "pamap2_calibration_windows.json"))


def get_pamap2_best_config_path():
    configured_path = os.getenv("PAMAP2_BEST_CONFIG_PATH")

    if configured_path:
        return os.path.abspath(configured_path)

    base_dir = os.path.dirname(__file__)
    return os.path.abspath(os.path.join(base_dir, "..", "logs", "pamap2_best_config.json"))


def get_backend_dir():
    return os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


def get_default_model_dir():
    return os.path.abspath(os.path.join(get_backend_dir(), "..", "model"))


def default_model_files_for_profile(profile):
    profile = str(profile or "").strip().lower()

    if profile in ("own_har_200x27", "own", "custom"):
        return {
            "model": "own_har_200x27_model.keras",
            "scaler": "own_har_200x27_scaler.pkl",
            "label_encoder": "own_har_200x27_label_encoder.pkl",
        }

    return {
        "model": "pamap2_basic_har_model.keras",
        "scaler": "pamap2_basic_scaler.pkl",
        "label_encoder": "pamap2_basic_label_encoder.pkl",
    }


def resolve_model_file(configured_path, default_filename):
    if configured_path:
        if os.path.isabs(configured_path):
            return os.path.abspath(configured_path)

        return os.path.abspath(os.path.join(get_backend_dir(), configured_path))

    return os.path.join(get_default_model_dir(), default_filename)


def get_model_config():
    profile = os.getenv("HAR_MODEL_PROFILE", MODEL_PROFILE or "pamap2_basic_keras")
    defaults = default_model_files_for_profile(profile)

    return {
        "profile": profile,
        "model_path": resolve_model_file(os.getenv("HAR_MODEL_PATH"), defaults["model"]),
        "scaler_path": resolve_model_file(os.getenv("HAR_SCALER_PATH"), defaults["scaler"]),
        "label_encoder_path": resolve_model_file(
            os.getenv("HAR_LABEL_ENCODER_PATH"),
            defaults["label_encoder"],
        ),
    }


def get_model_metadata():
    config = get_model_config()
    visible_profile = MODEL_PROFILE if MODEL is not None else config["profile"]

    return {
        "profile": visible_profile,
        "configured_profile": config["profile"],
        "loaded": MODEL is not None and SCALER is not None and LABEL_ENCODER is not None,
        "model_path": MODEL_PATH or config["model_path"],
        "scaler_path": SCALER_PATH or config["scaler_path"],
        "label_encoder_path": LABEL_ENCODER_PATH or config["label_encoder_path"],
        "model_file": os.path.basename(MODEL_PATH or config["model_path"]),
        "scaler_file": os.path.basename(SCALER_PATH or config["scaler_path"]),
        "label_encoder_file": os.path.basename(LABEL_ENCODER_PATH or config["label_encoder_path"]),
        "classes": [str(label) for label in LABEL_ENCODER.classes_] if LABEL_ENCODER is not None else [],
        "input_shape": list(MODEL.input_shape) if MODEL is not None else None,
    }


def make_prediction_id():
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    return f"{stamp}-{uuid.uuid4().hex[:8]}"


def parse_node_order(value):
    if value is None:
        value = os.getenv("PAMAP2_NODE_ORDER", "1,2,3")

    if isinstance(value, (list, tuple)):
        raw_items = value
    else:
        raw_items = str(value).split(",")

    try:
        order = tuple(int(item) for item in raw_items)
    except Exception:
        order = (1, 2, 3)

    if sorted(order) != NODE_IDS:
        raise ValueError(f"node_order must be a permutation of {NODE_IDS}, got {value}")

    return order


def parse_bool(value, default=False):
    if value is None:
        return default

    if isinstance(value, bool):
        return value

    return str(value).strip().lower() not in ("0", "false", "no", "off")


def parse_axis_transform(value):
    if value is None:
        value = os.getenv("PAMAP2_AXIS_TRANSFORM", IDENTITY_AXIS_TRANSFORM)

    text = str(value).strip().lower().replace(",", "").replace(" ", "")

    if text in ("", "identity", "none", "raw"):
        text = IDENTITY_AXIS_TRANSFORM

    matches = re.findall(r"([+-]?)([xyz])", text)

    if len(matches) != 3:
        raise ValueError(f"axis_transform must look like '+x+y+z' or '+z-y-x', got {value}")

    canonical_parts = []
    axes = []

    for sign_text, axis_name in matches:
        sign = "-" if sign_text == "-" else "+"
        canonical_parts.append(f"{sign}{axis_name}")
        axes.append(axis_name)

    if len(set(axes)) != 3:
        raise ValueError(f"axis_transform must use x, y, z once each, got {value}")

    return "".join(canonical_parts)


def parse_node_axis_transforms(value=None, axis_transform=None):
    fallback_axis = parse_axis_transform(axis_transform)

    if value is None:
        value = os.getenv("PAMAP2_NODE_AXIS_TRANSFORMS")

    if value in (None, ""):
        return {
            node_id: fallback_axis
            for node_id in NODE_IDS
        }

    if isinstance(value, dict):
        parsed = {
            int(node_id): parse_axis_transform(node_axis)
            for node_id, node_axis in value.items()
        }
    elif isinstance(value, (list, tuple)):
        if len(value) != len(NODE_IDS):
            raise ValueError(f"node_axis_transforms list must have {len(NODE_IDS)} items")

        parsed = {
            node_id: parse_axis_transform(value[index])
            for index, node_id in enumerate(NODE_IDS)
        }
    else:
        text = str(value).strip()

        try:
            loaded = json.loads(text)
            return parse_node_axis_transforms(loaded, axis_transform=fallback_axis)
        except Exception:
            pass

        if ":" not in text:
            return {
                node_id: parse_axis_transform(text)
                for node_id in NODE_IDS
            }

        parsed = {}
        for item in re.split(r"[;|]", text):
            item = item.strip()

            if not item:
                continue

            if ":" not in item:
                raise ValueError(
                    "node_axis_transforms must look like '1:+x+y+z;2:+z-y-x;3:-x+y+z'"
                )

            node_id_text, node_axis = item.split(":", 1)
            parsed[int(node_id_text.strip())] = parse_axis_transform(node_axis)

    missing_nodes = [node_id for node_id in NODE_IDS if node_id not in parsed]

    if missing_nodes:
        for node_id in missing_nodes:
            parsed[node_id] = fallback_axis

    return {
        node_id: parsed[node_id]
        for node_id in NODE_IDS
    }


def default_node_axis_transforms(axis_transform):
    fallback_axis = parse_axis_transform(axis_transform)

    return {
        node_id: fallback_axis
        for node_id in NODE_IDS
    }


def parse_node_axis_transforms_for_sweep(value=None, axis_transform=None):
    if value is None:
        return default_node_axis_transforms(axis_transform)

    return parse_node_axis_transforms(value, axis_transform=axis_transform)


def axis_transform_spec(axis_transform):
    axis_transform = parse_axis_transform(axis_transform)
    matches = re.findall(r"([+-])([xyz])", axis_transform)
    return tuple(
        (AXIS_INDEX[axis_name], -1.0 if sign_text == "-" else 1.0)
        for sign_text, axis_name in matches
    )


def parse_mag_mode(value):
    if value is None:
        value = os.getenv("PAMAP2_MAG_MODE", "raw")

    mode = str(value).strip().lower().replace("-", "_")

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

    if mode not in MAG_MODE_OPTIONS:
        raise ValueError(f"mag_mode must be one of {MAG_MODE_OPTIONS}, got {value}")

    return mode


DEFAULT_NODE_ORDER = parse_node_order(os.getenv("PAMAP2_NODE_ORDER", "1,2,3"))
DEFAULT_AXIS_TRANSFORM = parse_axis_transform(os.getenv("PAMAP2_AXIS_TRANSFORM", IDENTITY_AXIS_TRANSFORM))
DEFAULT_NODE_AXIS_TRANSFORMS = parse_node_axis_transforms(axis_transform=DEFAULT_AXIS_TRANSFORM)
DEFAULT_MAG_MODE = parse_mag_mode(os.getenv("PAMAP2_MAG_MODE", "raw"))


def feature_columns_for_order(node_order):
    return tuple(
        f"model_node{model_slot}_from_source_node{source_node_id}_{feature}"
        for model_slot, source_node_id in enumerate(node_order, start=1)
        for feature in FEATURES_PER_NODE
    )


def json_float(value):
    try:
        value = float(value)
    except Exception:
        return None

    if not np.isfinite(value):
        return None

    return round(value, 6)


def summarize_feature_values(values):
    array = np.asarray(values, dtype=np.float32)

    if array.size == 0:
        return {
            "min": None,
            "mean": None,
            "max": None,
            "std": None,
        }

    return {
        "min": json_float(np.nanmin(array)),
        "mean": json_float(np.nanmean(array)),
        "max": json_float(np.nanmax(array)),
        "std": json_float(np.nanstd(array)),
    }


def summarize_array(array, columns=None):
    array = np.asarray(array, dtype=np.float32)
    summary = {
        "shape": list(array.shape),
        "nan_count": int(np.isnan(array).sum()),
        "inf_count": int(np.isinf(array).sum()),
        "min": json_float(np.nanmin(array)) if array.size else None,
        "mean": json_float(np.nanmean(array)) if array.size else None,
        "max": json_float(np.nanmax(array)) if array.size else None,
        "std": json_float(np.nanstd(array)) if array.size else None,
    }

    if array.ndim >= 2 and array.shape[0] > 0:
        summary["first_row"] = [json_float(value) for value in array[0].tolist()]
        summary["last_row"] = [json_float(value) for value in array[-1].tolist()]

    if columns and array.ndim == 2 and array.shape[1] == len(columns):
        summary["columns"] = {
            columns[index]: summarize_feature_values(array[:, index])
            for index in range(array.shape[1])
        }

    return summary


def summarize_windows_by_node(windows_by_node):
    summary = {}

    for node_id in NODE_IDS:
        readings = windows_by_node.get(node_id, [])
        rows = []

        for reading in readings:
            rows.append([
                float(reading.get(feature, 0.0))
                for feature in FEATURES_PER_NODE
            ])

        node_summary = {
            "count": len(readings),
            "first": readings[0] if readings else None,
            "last": readings[-1] if readings else None,
        }

        if rows:
            array = np.asarray(rows, dtype=np.float32)
            node_summary["feature_stats"] = {
                feature: summarize_feature_values(array[:, index])
                for index, feature in enumerate(FEATURES_PER_NODE)
            }

        summary[str(node_id)] = node_summary

    return summary


def mag_mode_scale(mag_mode):
    if mag_mode in ("div100", "center_div100"):
        return 100.0

    if mag_mode in ("div1000", "center_div1000"):
        return 1000.0

    return 1.0


def should_center_mag(mag_mode):
    return mag_mode in ("center", "center_div100", "center_div1000")


def compute_mag_centers(windows_by_node, mag_mode):
    centers = {
        node_id: {feature: 0.0 for feature in MAG_FEATURES}
        for node_id in NODE_IDS
    }

    if not should_center_mag(mag_mode):
        return centers

    for node_id in NODE_IDS:
        readings = windows_by_node[node_id]

        for feature in MAG_FEATURES:
            centers[node_id][feature] = sum(
                float(reading[feature])
                for reading in readings
            ) / len(readings)

    return centers


def transform_feature_group(reading, group, axis_spec, node_id, mag_mode, mag_centers):
    transformed = []
    scale = mag_mode_scale(mag_mode) if group == MAG_FEATURES else 1.0

    for source_index, sign in axis_spec:
        source_feature = group[source_index]
        value = float(reading[source_feature])

        if group == MAG_FEATURES:
            if mag_mode == "zero":
                value = 0.0
            else:
                value -= mag_centers[node_id][source_feature]
                value /= scale

        transformed.append(value * sign)

    return transformed


def build_preprocess_debug(axis_transform, mag_mode, node_axis_transforms=None):
    node_axis_transforms = parse_node_axis_transforms(
        node_axis_transforms,
        axis_transform=axis_transform,
    )

    return {
        "axis_transform": axis_transform,
        "axis_spec": [
            {
                "output_axis": AXIS_NAMES[dest_index],
                "source_axis": AXIS_NAMES[source_index],
                "sign": int(sign),
            }
            for dest_index, (source_index, sign) in enumerate(axis_transform_spec(axis_transform))
        ],
        "node_axis_transforms": {
            str(node_id): node_axis
            for node_id, node_axis in node_axis_transforms.items()
        },
        "node_axis_specs": {
            str(node_id): [
                {
                    "output_axis": AXIS_NAMES[dest_index],
                    "source_axis": AXIS_NAMES[source_index],
                    "sign": int(sign),
                }
                for dest_index, (source_index, sign) in enumerate(axis_transform_spec(node_axis))
            ]
            for node_id, node_axis in node_axis_transforms.items()
        },
        "mag_mode": mag_mode,
        "mag_scale": mag_mode_scale(mag_mode),
        "mag_centered": should_center_mag(mag_mode),
    }


def write_prediction_debug_log(status, **metadata):
    try:
        log_path = get_prediction_log_path()
        os.makedirs(os.path.dirname(log_path), exist_ok=True)

        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "status": status,
            "remote_addr": request.remote_addr,
            "model": MODEL_PROFILE,
            "window_size": WINDOW_SIZE,
            "features_per_node": list(FEATURES_PER_NODE),
            **metadata,
        }

        with open(log_path, "a", encoding="utf-8") as log_file:
            log_file.write(json.dumps(entry, ensure_ascii=False, default=str))
            log_file.write("\n")
    except Exception as error:
        print(f"Failed to write PAMAP2 prediction debug log: {error}", flush=True)


def load_model():
    global MODEL, SCALER, LABEL_ENCODER
    global MODEL_PROFILE, MODEL_PATH, SCALER_PATH, LABEL_ENCODER_PATH

    config = get_model_config()
    MODEL_PROFILE = config["profile"]
    MODEL_PATH = config["model_path"]
    SCALER_PATH = config["scaler_path"]
    LABEL_ENCODER_PATH = config["label_encoder_path"]

    print("model_path exists:", os.path.exists(MODEL_PATH), MODEL_PATH)
    print("scaler_path exists:", os.path.exists(SCALER_PATH), SCALER_PATH)
    print("label_encoder_path exists:", os.path.exists(LABEL_ENCODER_PATH), LABEL_ENCODER_PATH)

    MODEL = tf.keras.models.load_model(MODEL_PATH)
    SCALER = joblib.load(SCALER_PATH)
    LABEL_ENCODER = joblib.load(LABEL_ENCODER_PATH)

    print(f"HAR model loaded: {MODEL_PROFILE}")
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


def build_model_input(
    windows_by_node,
    node_order=None,
    axis_transform=None,
    node_axis_transforms=None,
    mag_mode=None,
    include_column_stats=True,
    emit_prints=True,
):
    node_order = parse_node_order(node_order)
    axis_transform = parse_axis_transform(axis_transform)
    node_axis_transforms = parse_node_axis_transforms(
        node_axis_transforms,
        axis_transform=axis_transform,
    )
    mag_mode = parse_mag_mode(mag_mode)
    mag_centers = compute_mag_centers(windows_by_node, mag_mode)
    feature_columns = feature_columns_for_order(node_order)
    rows = []

    for timestep in range(WINDOW_SIZE):
        row = []

        for source_node_id in node_order:
            reading = windows_by_node[source_node_id][timestep]
            axis_spec = axis_transform_spec(node_axis_transforms[source_node_id])

            for group in VECTOR_FEATURE_GROUPS:
                row.extend(
                    transform_feature_group(
                        reading,
                        group,
                        axis_spec,
                        source_node_id,
                        mag_mode,
                        mag_centers,
                    )
                )

        rows.append(row)

    data_array = np.array(rows, dtype=np.float32)
    raw_input_summary = summarize_array(
        data_array,
        feature_columns if include_column_stats else None,
    )

    if emit_prints:
        print("INPUT SHAPE BEFORE SCALER:", data_array.shape, flush=True)
        print("NODE ORDER:", node_order, flush=True)
        print("AXIS TRANSFORM:", axis_transform, "MAG MODE:", mag_mode, flush=True)
        print("NODE AXIS TRANSFORMS:", node_axis_transforms, flush=True)
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
    scaled_input_summary = summarize_array(
        data_array,
        feature_columns if include_column_stats else None,
    )
    data_array = np.nan_to_num(
        data_array,
        nan=0.0,
        posinf=0.0,
        neginf=0.0,
    )
    data_array = np.clip(data_array, -10.0, 10.0)

    model_input = np.expand_dims(data_array, axis=0)
    model_input_summary = summarize_array(
        model_input[0],
        feature_columns if include_column_stats else None,
    )

    if emit_prints:
        print("MODEL INPUT SHAPE:", model_input.shape, "EXPECTED:", expected_shape, flush=True)

    return model_input, {
        "node_order": list(node_order),
        "axis_transform": axis_transform,
        "node_axis_transforms": {
            str(node_id): node_axis
            for node_id, node_axis in node_axis_transforms.items()
        },
        "mag_mode": mag_mode,
        "preprocess": build_preprocess_debug(axis_transform, mag_mode, node_axis_transforms),
        "mag_centers": {
            str(node_id): {
                feature: json_float(value)
                for feature, value in node_centers.items()
            }
            for node_id, node_centers in mag_centers.items()
        },
        "feature_columns": list(feature_columns),
        "expected_shape": list(expected_shape),
        "raw_input": raw_input_summary,
        "scaled_input_before_clip": scaled_input_summary,
        "model_input": model_input_summary,
    }


def predict_activity(
    windows_by_node,
    node_order=None,
    axis_transform=None,
    node_axis_transforms=None,
    mag_mode=None,
):
    if MODEL is None or SCALER is None or LABEL_ENCODER is None:
        raise RuntimeError("Model, scaler, or label encoder not loaded")

    node_order = parse_node_order(node_order)
    axis_transform = parse_axis_transform(axis_transform)
    node_axis_transforms = parse_node_axis_transforms(
        node_axis_transforms,
        axis_transform=axis_transform,
    )
    mag_mode = parse_mag_mode(mag_mode)
    model_input, model_debug = build_model_input(
        windows_by_node,
        node_order=node_order,
        axis_transform=axis_transform,
        node_axis_transforms=node_axis_transforms,
        mag_mode=mag_mode,
    )

    probs = MODEL.predict(model_input, verbose=0)[0]
    prob_map = {
        str(label): float(prob)
        for label, prob in zip(LABEL_ENCODER.classes_, probs)
    }
    top_predictions = [
        {
            "label": label,
            "probability": json_float(probability),
        }
        for label, probability in sorted(
            prob_map.items(),
            key=lambda item: item[1],
            reverse=True,
        )
    ]

    print("\n=== CLASS PROBABILITIES ===", flush=True)
    print(prob_map, flush=True)

    activity_idx = int(np.argmax(probs))
    confidence = float(probs[activity_idx])
    activity = LABEL_ENCODER.inverse_transform([activity_idx])[0]

    return str(activity), confidence, prob_map, top_predictions, model_debug


def run_order_sweep(windows_by_node, axis_transform=None, node_axis_transforms=None, mag_mode=None):
    results = []

    if MODEL is None or SCALER is None or LABEL_ENCODER is None:
        return results

    axis_transform = parse_axis_transform(axis_transform)
    node_axis_transforms = parse_node_axis_transforms(
        node_axis_transforms,
        axis_transform=axis_transform,
    )
    mag_mode = parse_mag_mode(mag_mode)

    for node_order in NODE_ORDER_OPTIONS:
        try:
            model_input, _ = build_model_input(
                windows_by_node,
                node_order=node_order,
                axis_transform=axis_transform,
                node_axis_transforms=node_axis_transforms,
                mag_mode=mag_mode,
                include_column_stats=False,
                emit_prints=False,
            )
            probs = MODEL.predict(model_input, verbose=0)[0]
            prob_map = {
                str(label): json_float(prob)
                for label, prob in zip(LABEL_ENCODER.classes_, probs)
            }
            activity_idx = int(np.argmax(probs))
            activity = str(LABEL_ENCODER.inverse_transform([activity_idx])[0])
            confidence = json_float(probs[activity_idx])
            results.append({
                "node_order": list(node_order),
                "axis_transform": axis_transform,
                "node_axis_transforms": {
                    str(node_id): node_axis
                    for node_id, node_axis in node_axis_transforms.items()
                },
                "mag_mode": mag_mode,
                "activity": activity,
                "confidence": confidence,
                "probabilities": prob_map,
            })
        except Exception as error:
            results.append({
                "node_order": list(node_order),
                "axis_transform": axis_transform,
                "node_axis_transforms": {
                    str(node_id): node_axis
                    for node_id, node_axis in node_axis_transforms.items()
                },
                "mag_mode": mag_mode,
                "error": str(error),
            })

    results.sort(key=lambda item: item.get("confidence") or -1, reverse=True)
    return results


def parse_node_order_options(value, default_to_all=False):
    if value is None:
        return NODE_ORDER_OPTIONS if default_to_all else (DEFAULT_NODE_ORDER,)

    if isinstance(value, str) and value.strip().lower() == "all":
        return NODE_ORDER_OPTIONS

    if isinstance(value, (list, tuple)):
        if len(value) == 3 and all(not isinstance(item, (list, tuple, dict)) for item in value):
            return (parse_node_order(value),)

        return tuple(parse_node_order(item) for item in value)

    return (parse_node_order(value),)


def parse_axis_transform_options(value, default_to_all=False):
    if value is None:
        return AXIS_TRANSFORM_OPTIONS if default_to_all else (DEFAULT_AXIS_TRANSFORM,)

    if isinstance(value, str) and value.strip().lower() == "all":
        return AXIS_TRANSFORM_OPTIONS

    if isinstance(value, (list, tuple)):
        return tuple(parse_axis_transform(item) for item in value)

    return (parse_axis_transform(value),)


def parse_mag_mode_options(value, default_to_all=False):
    if value is None:
        return MAG_MODE_OPTIONS if default_to_all else (DEFAULT_MAG_MODE,)

    if isinstance(value, str) and value.strip().lower() == "all":
        return MAG_MODE_OPTIONS

    if isinstance(value, (list, tuple)):
        return tuple(parse_mag_mode(item) for item in value)

    return (parse_mag_mode(value),)


def parse_target_activity(value):
    if value is None or str(value).strip() == "":
        return None

    target = str(value).strip()

    if LABEL_ENCODER is None:
        return target

    valid_labels = {str(label) for label in LABEL_ENCODER.classes_}

    if target not in valid_labels:
        raise ValueError(f"target_activity must be one of {sorted(valid_labels)}, got {value}")

    return target


def run_config_sweep(
    windows_by_node,
    node_orders,
    axis_transforms,
    mag_modes,
    node_axis_transforms=None,
    target_activity=None,
    top_n=20,
):
    if MODEL is None or SCALER is None or LABEL_ENCODER is None:
        raise RuntimeError("Model, scaler, or label encoder not loaded")

    top_n = max(1, min(int(top_n), 100))
    label_names = [str(label) for label in LABEL_ENCODER.classes_]
    label_index = {label: index for index, label in enumerate(label_names)}
    model_inputs = []
    metadata = []
    errors = []

    for axis_transform in axis_transforms:
        parsed_node_axis_transforms = parse_node_axis_transforms_for_sweep(
            node_axis_transforms,
            axis_transform=axis_transform,
        )

        for mag_mode in mag_modes:
            for node_order in node_orders:
                try:
                    model_input, _ = build_model_input(
                        windows_by_node,
                        node_order=node_order,
                        axis_transform=axis_transform,
                        node_axis_transforms=parsed_node_axis_transforms,
                        mag_mode=mag_mode,
                        include_column_stats=False,
                        emit_prints=False,
                    )
                    model_inputs.append(model_input[0])
                    metadata.append((node_order, axis_transform, parsed_node_axis_transforms, mag_mode))
                except Exception as error:
                    errors.append({
                        "node_order": list(node_order),
                        "axis_transform": axis_transform,
                        "node_axis_transforms": {
                            str(node_id): node_axis
                            for node_id, node_axis in parsed_node_axis_transforms.items()
                        },
                        "mag_mode": mag_mode,
                        "error": str(error),
                    })

    if not model_inputs:
        return {
            "tested_configs": 0,
            "errors": errors,
            "results": [],
        }

    batch_size = int(os.getenv("PAMAP2_CONFIG_SWEEP_BATCH_SIZE", "64"))
    probabilities_batch = MODEL.predict(
        np.stack(model_inputs, axis=0),
        verbose=0,
        batch_size=batch_size,
    )
    results = []

    for (node_order, axis_transform, parsed_node_axis_transforms, mag_mode), probabilities in zip(metadata, probabilities_batch):
        probability_map = {
            label: json_float(probabilities[index])
            for label, index in label_index.items()
        }
        activity_index = int(np.argmax(probabilities))
        activity = label_names[activity_index]
        confidence = json_float(probabilities[activity_index])
        target_probability = (
            json_float(probabilities[label_index[target_activity]])
            if target_activity is not None
            else None
        )
        score = target_probability if target_probability is not None else confidence

        results.append({
            "node_order": list(node_order),
            "axis_transform": axis_transform,
            "node_axis_transforms": {
                str(node_id): node_axis
                for node_id, node_axis in parsed_node_axis_transforms.items()
            },
            "mag_mode": mag_mode,
            "activity": activity,
            "confidence": confidence,
            "target_activity": target_activity,
            "target_probability": target_probability,
            "score": score,
            "probabilities": probability_map,
        })

    results.sort(key=lambda item: item.get("score") or -1, reverse=True)

    return {
        "tested_configs": len(results),
        "errors": errors,
        "results": results[:top_n],
    }


def run_pamap2_calibration_sweep(
    samples,
    node_orders,
    axis_transforms,
    mag_modes,
    node_axis_transforms=None,
    top_n=20,
):
    if MODEL is None or SCALER is None or LABEL_ENCODER is None:
        raise RuntimeError("Model, scaler, or label encoder not loaded")

    top_n = max(1, min(int(top_n), 100))
    label_names = [str(label) for label in LABEL_ENCODER.classes_]
    label_index = {label: index for index, label in enumerate(label_names)}
    valid_samples = []
    errors = []

    for sample_index, sample in enumerate(samples):
        try:
            label = parse_target_activity(sample.get("label") or sample.get("target_activity"))

            if label is None:
                raise ValueError("sample label is required")

            windows_by_node = sample.get("windows_by_node")

            if windows_by_node is None:
                raise ValueError("sample windows_by_node is required")

            valid_samples.append({
                "index": sample_index,
                "id": sample.get("id") or str(sample_index + 1),
                "label": label,
                "windows_by_node": validate_windows_by_node(windows_by_node),
                "created_at": sample.get("created_at"),
            })
        except Exception as error:
            errors.append({
                "sample_index": sample_index,
                "sample_id": sample.get("id") if isinstance(sample, dict) else None,
                "error": str(error),
            })

    if not valid_samples:
        raise ValueError("No valid PAMAP2 calibration samples found")

    aggregates = []
    pending_inputs = []
    pending_refs = []
    max_pending_inputs = max(1, int(os.getenv("PAMAP2_CALIBRATION_SWEEP_MAX_PENDING", "256")))
    predict_batch_size = max(1, int(os.getenv("PAMAP2_CONFIG_SWEEP_BATCH_SIZE", "64")))

    def flush_pending_inputs():
        if not pending_inputs:
            return

        probabilities_batch = MODEL.predict(
            np.stack(pending_inputs, axis=0),
            verbose=0,
            batch_size=predict_batch_size,
        )

        for ref, probabilities in zip(pending_refs, probabilities_batch):
            aggregate = aggregates[ref["config_id"]]
            target_label = ref["label"]
            target_probability = float(probabilities[label_index[target_label]])
            activity_index = int(np.argmax(probabilities))
            activity = label_names[activity_index]
            confidence = float(probabilities[activity_index])
            is_correct = activity == target_label

            aggregate["prediction_count"] += 1
            aggregate["correct_count"] += 1 if is_correct else 0
            aggregate["target_probability_sum"] += target_probability
            aggregate["confidence_sum"] += confidence
            aggregate["cross_entropy_sum"] += -float(np.log(max(target_probability, 1e-9)))

            label_stats = aggregate["per_label"].setdefault(target_label, {
                "count": 0,
                "correct": 0,
                "target_probability_sum": 0.0,
                "confidence_sum": 0.0,
            })
            label_stats["count"] += 1
            label_stats["correct"] += 1 if is_correct else 0
            label_stats["target_probability_sum"] += target_probability
            label_stats["confidence_sum"] += confidence

            if len(aggregate["examples"]) < 12:
                aggregate["examples"].append({
                    "sample_id": ref["sample_id"],
                    "target_activity": target_label,
                    "activity": activity,
                    "confidence": json_float(confidence),
                    "target_probability": json_float(target_probability),
                    "correct": is_correct,
                })

        pending_inputs.clear()
        pending_refs.clear()

    for axis_transform in axis_transforms:
        parsed_node_axis_transforms = parse_node_axis_transforms_for_sweep(
            node_axis_transforms,
            axis_transform=axis_transform,
        )

        for mag_mode in mag_modes:
            for node_order in node_orders:
                config_id = len(aggregates)
                aggregates.append({
                    "node_order": tuple(node_order),
                    "axis_transform": axis_transform,
                    "node_axis_transforms": parsed_node_axis_transforms,
                    "mag_mode": mag_mode,
                    "prediction_count": 0,
                    "correct_count": 0,
                    "target_probability_sum": 0.0,
                    "confidence_sum": 0.0,
                    "cross_entropy_sum": 0.0,
                    "per_label": {},
                    "examples": [],
                    "errors": [],
                })

                for sample in valid_samples:
                    try:
                        model_input, _ = build_model_input(
                            sample["windows_by_node"],
                            node_order=node_order,
                            axis_transform=axis_transform,
                            node_axis_transforms=parsed_node_axis_transforms,
                            mag_mode=mag_mode,
                            include_column_stats=False,
                            emit_prints=False,
                        )
                        pending_inputs.append(model_input[0])
                        pending_refs.append({
                            "config_id": config_id,
                            "sample_id": sample["id"],
                            "label": sample["label"],
                        })

                        if len(pending_inputs) >= max_pending_inputs:
                            flush_pending_inputs()
                    except Exception as error:
                        aggregates[config_id]["errors"].append({
                            "sample_id": sample["id"],
                            "target_activity": sample["label"],
                            "error": str(error),
                        })

    flush_pending_inputs()

    results = []

    for aggregate in aggregates:
        prediction_count = aggregate["prediction_count"]

        if prediction_count:
            accuracy = aggregate["correct_count"] / prediction_count
            mean_target_probability = aggregate["target_probability_sum"] / prediction_count
            mean_confidence = aggregate["confidence_sum"] / prediction_count
            mean_cross_entropy = aggregate["cross_entropy_sum"] / prediction_count
            score = accuracy + mean_target_probability
        else:
            accuracy = 0.0
            mean_target_probability = 0.0
            mean_confidence = 0.0
            mean_cross_entropy = None
            score = -1.0

        per_label = {}

        for label, stats in aggregate["per_label"].items():
            count = stats["count"]
            per_label[label] = {
                "count": count,
                "correct": stats["correct"],
                "accuracy": json_float(stats["correct"] / count) if count else None,
                "mean_target_probability": json_float(
                    stats["target_probability_sum"] / count
                ) if count else None,
                "mean_confidence": json_float(stats["confidence_sum"] / count) if count else None,
            }

        result = {
            "node_order": list(aggregate["node_order"]),
            "axis_transform": aggregate["axis_transform"],
            "node_axis_transforms": {
                str(node_id): node_axis
                for node_id, node_axis in aggregate["node_axis_transforms"].items()
            },
            "mag_mode": aggregate["mag_mode"],
            "score": json_float(score),
            "accuracy": json_float(accuracy),
            "correct_count": aggregate["correct_count"],
            "sample_count": prediction_count,
            "mean_target_probability": json_float(mean_target_probability),
            "mean_confidence": json_float(mean_confidence),
            "mean_cross_entropy": json_float(mean_cross_entropy),
            "per_label": per_label,
            "examples": aggregate["examples"],
            "errors": aggregate["errors"][:10],
        }
        results.append(result)

        if aggregate["errors"]:
            errors.extend({
                "node_order": result["node_order"],
                "axis_transform": result["axis_transform"],
                "node_axis_transforms": result["node_axis_transforms"],
                "mag_mode": result["mag_mode"],
                **config_error,
            } for config_error in aggregate["errors"][:3])

    results.sort(
        key=lambda item: (
            item.get("score") if item.get("score") is not None else -1.0,
            item.get("accuracy") if item.get("accuracy") is not None else -1.0,
            item.get("mean_target_probability") if item.get("mean_target_probability") is not None else -1.0,
        ),
        reverse=True,
    )

    best_config = results[0] if results else None

    return {
        "sample_count": len(valid_samples),
        "counts": calibration_counts(valid_samples),
        "tested_configs": len(results),
        "errors": errors,
        "best_config": best_config,
        "results": results[:top_n],
    }


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


def calibration_counts(samples):
    counts = {}

    for sample in samples:
        label = str(sample.get("label", "")).strip()

        if label:
            counts[label] = counts.get(label, 0) + 1

    return counts


def serialize_windows_by_node(windows_by_node):
    return {
        str(node_id): [
            {
                feature: float(reading[feature])
                for feature in FEATURES_PER_NODE
            }
            for reading in windows_by_node[node_id]
        ]
        for node_id in NODE_IDS
    }


def load_live_calibration_samples():
    path = get_live_calibration_path()

    if not os.path.exists(path):
        return []

    with open(path, "r", encoding="utf-8") as calibration_file:
        payload = json.load(calibration_file)

    if isinstance(payload, dict):
        samples = payload.get("samples", [])
    else:
        samples = payload

    return samples if isinstance(samples, list) else []


def save_live_calibration_samples(samples):
    path = get_live_calibration_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)

    with open(path, "w", encoding="utf-8") as calibration_file:
        json.dump(
            {
                "updated_at": datetime.now(timezone.utc).isoformat(),
                "samples": samples,
                "counts": calibration_counts(samples),
            },
            calibration_file,
            ensure_ascii=False,
            indent=2,
        )


def load_pamap2_calibration_samples():
    path = get_pamap2_calibration_path()

    if not os.path.exists(path):
        return []

    with open(path, "r", encoding="utf-8") as calibration_file:
        payload = json.load(calibration_file)

    if isinstance(payload, dict):
        samples = payload.get("samples", [])
    else:
        samples = payload

    return samples if isinstance(samples, list) else []


def save_pamap2_calibration_samples(samples):
    path = get_pamap2_calibration_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)

    with open(path, "w", encoding="utf-8") as calibration_file:
        json.dump(
            {
                "updated_at": datetime.now(timezone.utc).isoformat(),
                "sample_count": len(samples),
                "counts": calibration_counts(samples),
                "samples": samples,
            },
            calibration_file,
            ensure_ascii=False,
            indent=2,
        )


def load_pamap2_best_config():
    path = get_pamap2_best_config_path()

    if not os.path.exists(path):
        return None

    with open(path, "r", encoding="utf-8") as config_file:
        payload = json.load(config_file)

    return payload if isinstance(payload, dict) else None


def save_pamap2_best_config(config):
    path = get_pamap2_best_config_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)

    payload = {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        **config,
    }

    with open(path, "w", encoding="utf-8") as config_file:
        json.dump(payload, config_file, ensure_ascii=False, indent=2)

    return payload


def build_live_feature_vector(windows_by_node):
    features = []
    debug = {}

    for node_id in NODE_IDS:
        readings = windows_by_node[node_id]
        acc = np.asarray(
            [[float(reading[axis]) for axis in ("ax", "ay", "az")] for reading in readings],
            dtype=np.float32,
        )
        gyro = np.asarray(
            [[float(reading[axis]) for axis in ("gx", "gy", "gz")] for reading in readings],
            dtype=np.float32,
        )

        acc_mean = np.mean(acc, axis=0) / 9.81
        acc_std = np.std(acc, axis=0) / 3.0
        gyro_mean = np.mean(gyro, axis=0)
        gyro_std = np.std(gyro, axis=0)

        if len(acc) > 1:
            acc_delta = float(np.mean(np.linalg.norm(np.diff(acc, axis=0), axis=1)) / 2.0)
        else:
            acc_delta = 0.0

        gyro_energy = float(np.mean(np.linalg.norm(gyro, axis=1)))

        node_features = np.concatenate([
            acc_mean,
            acc_std,
            gyro_mean,
            gyro_std,
            np.asarray([acc_delta, gyro_energy], dtype=np.float32),
        ])
        node_features = np.nan_to_num(node_features, nan=0.0, posinf=0.0, neginf=0.0)
        features.extend(float(value) for value in node_features)

        debug[str(node_id)] = {
            "acc_mean": [json_float(value) for value in np.mean(acc, axis=0)],
            "acc_std": [json_float(value) for value in np.std(acc, axis=0)],
            "gyro_std": [json_float(value) for value in np.std(gyro, axis=0)],
            "acc_delta": json_float(acc_delta),
            "gyro_energy": json_float(gyro_energy),
        }

    return features, debug


def predict_live_calibrated(windows_by_node):
    if not LIVE_CALIBRATION_ENABLED:
        return None

    samples = load_live_calibration_samples()
    groups = {}

    for sample in samples:
        label = str(sample.get("label", "")).strip()
        vector = sample.get("features")

        if not label or not isinstance(vector, list):
            continue

        groups.setdefault(label, []).append(np.asarray(vector, dtype=np.float32))

    if len(groups) < LIVE_CALIBRATION_MIN_LABELS:
        return None

    vector, feature_debug = build_live_feature_vector(windows_by_node)
    current = np.asarray(vector, dtype=np.float32)
    distances = []

    for label, vectors in groups.items():
        centroid = np.mean(np.stack(vectors, axis=0), axis=0)
        distance = float(np.linalg.norm(current - centroid) / max(1.0, np.sqrt(current.size)))
        distances.append((label, distance))

    distances.sort(key=lambda item: item[1])

    if not distances:
        return None

    raw_scores = np.exp(-5.0 * np.asarray([distance for _, distance in distances], dtype=np.float32))
    score_sum = float(np.sum(raw_scores)) or 1.0
    probabilities = {
        label: json_float(score / score_sum)
        for (label, _), score in zip(distances, raw_scores)
    }
    best_label, best_distance = distances[0]

    return {
        "activity": best_label,
        "confidence": float(probabilities[best_label] or 0.0),
        "probabilities": probabilities,
        "top_predictions": [
            {
                "label": label,
                "probability": probabilities[label],
                "distance": json_float(distance),
            }
            for label, distance in distances
        ],
        "distances": {
            label: json_float(distance)
            for label, distance in distances
        },
        "best_distance": json_float(best_distance),
        "sample_counts": calibration_counts(samples),
        "feature_debug": feature_debug,
    }


@activity_bp.route("/predict", methods=["POST"])
def predict_endpoint():
    data = None
    windows_by_node = None
    prediction_id = make_prediction_id()
    started_at = time.perf_counter()

    try:
        data = request.get_json(silent=True)

        if data is None:
            write_sensor_debug_log(
                None,
                "invalid_json",
                prediction_id=prediction_id,
                error="Invalid JSON body",
            )
            write_prediction_debug_log(
                "invalid_json",
                prediction_id=prediction_id,
                error="Invalid JSON body",
            )
            return jsonify({"error": "Invalid JSON body"}), 400

        windows_by_node = data.get("windows_by_node")

        if windows_by_node is None:
            write_sensor_debug_log(
                data,
                "missing_windows_by_node",
                prediction_id=prediction_id,
                received_keys=list(data.keys()),
            )
            write_prediction_debug_log(
                "missing_windows_by_node",
                prediction_id=prediction_id,
                received_keys=list(data.keys()),
            )
            return jsonify({
                "error": "windows_by_node is required for the PAMAP2 model",
                "received_keys": list(data.keys()),
            }), 400

        node_order = parse_node_order(data.get("node_order"))
        axis_transform = parse_axis_transform(data.get("axis_transform"))
        node_axis_transforms = parse_node_axis_transforms(
            data.get("node_axis_transforms"),
            axis_transform=axis_transform,
        )
        mag_mode = parse_mag_mode(data.get("mag_mode"))
        resampled_window = data.get("resampled_window")
        validated_windows = validate_windows_by_node(windows_by_node)
        window_summary = summarize_windows_by_node(validated_windows)

        prediction_result = predict_activity(
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
                    "probability": json_float(confidence),
                }
            ]
            model_debug = {}
        else:
            activity, confidence, prob_map, top_predictions, model_debug = prediction_result

        pamap2_activity = activity
        pamap2_confidence = confidence
        pamap2_probabilities = {
            label: json_float(probability)
            for label, probability in prob_map.items()
        }
        use_live_calibration = parse_bool(
            data.get("use_live_calibration"),
            LIVE_CALIBRATION_ENABLED,
        )
        calibrated_result = (
            predict_live_calibrated(validated_windows)
            if use_live_calibration
            else None
        )
        classifier = "pamap2"

        if calibrated_result is not None:
            classifier = "live_calibrated"
            activity = calibrated_result["activity"]
            confidence = calibrated_result["confidence"]
            prob_map = calibrated_result["probabilities"]
            top_predictions = calibrated_result["top_predictions"]

        order_sweep_enabled = parse_bool(data.get("order_sweep"), ORDER_SWEEP_ENABLED)
        order_sweep = run_order_sweep(
            validated_windows,
            axis_transform=axis_transform,
            node_axis_transforms=node_axis_transforms,
            mag_mode=mag_mode,
        ) if order_sweep_enabled else []
        inference_ms = round((time.perf_counter() - started_at) * 1000.0, 2)

        upsert_current_label(activity)
        remember_latest_combined_window(NODE_IDS, validated_windows, activity)

        for node_id, node_readings in validated_windows.items():
            remember_latest_window(node_id, node_readings, activity)
            mark_esp_connected_if_known(node_id)

        write_sensor_debug_log(
            validated_windows,
            "success",
            prediction_id=prediction_id,
            used_node_ids=NODE_IDS,
            node_order=list(node_order),
            axis_transform=axis_transform,
            node_axis_transforms={
                str(node_id): node_axis
                for node_id, node_axis in node_axis_transforms.items()
            },
            mag_mode=mag_mode,
            resampled_window=resampled_window,
            use_live_calibration=use_live_calibration,
            order_sweep_enabled=order_sweep_enabled,
            classifier=classifier,
            pamap2_activity=pamap2_activity,
            pamap2_confidence=round(pamap2_confidence, 4),
            calibrated_result=calibrated_result,
            activity=activity,
            confidence=round(confidence, 4),
        )
        write_prediction_debug_log(
            "success",
            prediction_id=prediction_id,
            used_node_ids=NODE_IDS,
            node_order=list(node_order),
            axis_transform=axis_transform,
            node_axis_transforms={
                str(node_id): node_axis
                for node_id, node_axis in node_axis_transforms.items()
            },
            mag_mode=mag_mode,
            resampled_window=resampled_window,
            use_live_calibration=use_live_calibration,
            order_sweep_enabled=order_sweep_enabled,
            classifier=classifier,
            pamap2_activity=pamap2_activity,
            pamap2_confidence=round(pamap2_confidence, 6),
            pamap2_probabilities=pamap2_probabilities,
            calibrated_result=calibrated_result,
            activity=activity,
            confidence=round(confidence, 6),
            inference_ms=inference_ms,
            probabilities={
                label: json_float(probability)
                for label, probability in prob_map.items()
            },
            top_predictions=top_predictions,
            order_sweep=order_sweep,
            window_summary=window_summary,
            model_debug=model_debug,
        )

        return jsonify({
            "prediction_id": prediction_id,
            "used_node_ids": NODE_IDS,
            "node_order": list(node_order),
            "axis_transform": axis_transform,
            "node_axis_transforms": {
                str(node_id): node_axis
                for node_id, node_axis in node_axis_transforms.items()
            },
            "mag_mode": mag_mode,
            "resampled_window": resampled_window,
            "use_live_calibration": use_live_calibration,
            "classifier": classifier,
            "pamap2_activity": pamap2_activity,
            "pamap2_confidence": round(pamap2_confidence, 4),
            "calibrated_result": calibrated_result,
            "activity": activity,
            "confidence": round(confidence, 4),
            "probabilities": {
                label: round(float(probability), 6)
                for label, probability in prob_map.items()
            },
            "top_predictions": top_predictions[:3],
            "order_sweep": order_sweep[:6],
            "inference_ms": inference_ms,
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
            prediction_id=prediction_id,
            error=str(e),
        )
        write_prediction_debug_log(
            "validation_error",
            prediction_id=prediction_id,
            error=str(e),
            received_keys=list(data.keys()) if isinstance(data, dict) else None,
        )
        return jsonify({"error": str(e)}), 400

    except Exception as e:
        import traceback
        print("PREDICT ERROR:", repr(e), flush=True)
        traceback.print_exc()
        write_sensor_debug_log(
            windows_by_node if windows_by_node is not None else data,
            "prediction_error",
            prediction_id=prediction_id,
            error=str(e),
        )
        write_prediction_debug_log(
            "prediction_error",
            prediction_id=prediction_id,
            error=str(e),
            received_keys=list(data.keys()) if isinstance(data, dict) else None,
        )
        return jsonify({"error": str(e)}), 500


@activity_bp.route("/calibration", methods=["GET"])
def calibration_status_endpoint():
    try:
        samples = load_live_calibration_samples()
        return jsonify({
            "enabled": LIVE_CALIBRATION_ENABLED,
            "path": get_live_calibration_path(),
            "sample_count": len(samples),
            "counts": calibration_counts(samples),
            "min_labels": LIVE_CALIBRATION_MIN_LABELS,
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@activity_bp.route("/calibration/sample", methods=["POST"])
def calibration_sample_endpoint():
    data = None

    try:
        data = request.get_json(silent=True)

        if data is None:
            return jsonify({"error": "Invalid JSON body"}), 400

        label = parse_target_activity(data.get("label") or data.get("target_activity"))

        if label is None:
            return jsonify({"error": "label is required"}), 400

        windows_by_node = data.get("windows_by_node")

        if windows_by_node is None:
            return jsonify({"error": "windows_by_node is required"}), 400

        validated_windows = validate_windows_by_node(windows_by_node)
        features, feature_debug = build_live_feature_vector(validated_windows)
        samples = load_live_calibration_samples()
        samples.append({
            "label": label,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "features": features,
            "feature_debug": feature_debug,
            "resampled_window": data.get("resampled_window"),
        })
        save_live_calibration_samples(samples)

        write_prediction_debug_log(
            "live_calibration_sample",
            label=label,
            sample_count=len(samples),
            counts=calibration_counts(samples),
            resampled_window=data.get("resampled_window"),
            feature_debug=feature_debug,
        )

        return jsonify({
            "status": "ok",
            "label": label,
            "sample_count": len(samples),
            "counts": calibration_counts(samples),
            "path": get_live_calibration_path(),
        })

    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        write_prediction_debug_log(
            "live_calibration_sample_error",
            error=str(e),
            received_keys=list(data.keys()) if isinstance(data, dict) else None,
        )
        return jsonify({"error": str(e)}), 500


@activity_bp.route("/calibration/clear", methods=["POST"])
def calibration_clear_endpoint():
    try:
        save_live_calibration_samples([])
        write_prediction_debug_log("live_calibration_cleared")
        return jsonify({
            "status": "ok",
            "sample_count": 0,
            "counts": {},
            "path": get_live_calibration_path(),
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@activity_bp.route("/predict/config_sweep", methods=["POST"])
def config_sweep_endpoint():
    data = None
    prediction_id = make_prediction_id()
    started_at = time.perf_counter()

    try:
        data = request.get_json(silent=True)

        if data is None:
            write_prediction_debug_log(
                "config_sweep_invalid_json",
                prediction_id=prediction_id,
                error="Invalid JSON body",
            )
            return jsonify({"error": "Invalid JSON body"}), 400

        windows_by_node = data.get("windows_by_node")

        if windows_by_node is None:
            write_prediction_debug_log(
                "config_sweep_missing_windows_by_node",
                prediction_id=prediction_id,
                received_keys=list(data.keys()),
            )
            return jsonify({
                "error": "windows_by_node is required for config sweep",
                "received_keys": list(data.keys()),
            }), 400

        validated_windows = validate_windows_by_node(windows_by_node)
        node_orders = parse_node_order_options(data.get("node_orders", "all"), default_to_all=True)
        axis_transforms = parse_axis_transform_options(
            data.get("axis_transforms", "all"),
            default_to_all=True,
        )
        mag_modes = parse_mag_mode_options(
            data.get("mag_modes", ("raw", "zero", "center", "div100")),
            default_to_all=False,
        )
        node_axis_transforms = (
            parse_node_axis_transforms(data.get("node_axis_transforms"))
            if data.get("node_axis_transforms") is not None
            else None
        )
        target_activity = parse_target_activity(data.get("target_activity"))
        top_n = int(data.get("top_n", 20))

        result = run_config_sweep(
            validated_windows,
            node_orders=node_orders,
            axis_transforms=axis_transforms,
            mag_modes=mag_modes,
            node_axis_transforms=node_axis_transforms,
            target_activity=target_activity,
            top_n=top_n,
        )
        elapsed_ms = round((time.perf_counter() - started_at) * 1000.0, 2)

        write_prediction_debug_log(
            "config_sweep_success",
            prediction_id=prediction_id,
            node_orders=[list(order) for order in node_orders],
            axis_transform_count=len(axis_transforms),
            node_axis_transforms={
                str(node_id): node_axis
                for node_id, node_axis in node_axis_transforms.items()
            } if node_axis_transforms is not None else None,
            mag_modes=list(mag_modes),
            target_activity=target_activity,
            tested_configs=result["tested_configs"],
            error_count=len(result["errors"]),
            elapsed_ms=elapsed_ms,
            top_results=result["results"][:10],
        )

        return jsonify({
            "prediction_id": prediction_id,
            "target_activity": target_activity,
            "node_order_count": len(node_orders),
            "axis_transform_count": len(axis_transforms),
            "mag_modes": list(mag_modes),
            "tested_configs": result["tested_configs"],
            "errors": result["errors"][:20],
            "results": result["results"],
            "elapsed_ms": elapsed_ms,
        })

    except ValueError as e:
        write_prediction_debug_log(
            "config_sweep_validation_error",
            prediction_id=prediction_id,
            error=str(e),
            received_keys=list(data.keys()) if isinstance(data, dict) else None,
        )
        return jsonify({"error": str(e)}), 400

    except Exception as e:
        import traceback
        print("CONFIG SWEEP ERROR:", repr(e), flush=True)
        traceback.print_exc()
        write_prediction_debug_log(
            "config_sweep_error",
            prediction_id=prediction_id,
            error=str(e),
            received_keys=list(data.keys()) if isinstance(data, dict) else None,
        )
        return jsonify({"error": str(e)}), 500


@activity_bp.route("/predict/pamap2_calibration", methods=["GET"])
def pamap2_calibration_status_endpoint():
    try:
        samples = load_pamap2_calibration_samples()
        best_config = load_pamap2_best_config()

        return jsonify({
            "status": "ok",
            "path": get_pamap2_calibration_path(),
            "sample_count": len(samples),
            "counts": calibration_counts(samples),
            "best_config_path": get_pamap2_best_config_path(),
            "best_config": best_config,
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@activity_bp.route("/predict/pamap2_calibration/sample", methods=["POST"])
def pamap2_calibration_sample_endpoint():
    data = None

    try:
        data = request.get_json(silent=True)

        if data is None:
            return jsonify({"error": "Invalid JSON body"}), 400

        label = parse_target_activity(data.get("label") or data.get("target_activity"))

        if label is None:
            return jsonify({"error": "label or target_activity is required"}), 400

        windows_by_node = data.get("windows_by_node")

        if windows_by_node is None:
            return jsonify({"error": "windows_by_node is required"}), 400

        validated_windows = validate_windows_by_node(windows_by_node)
        axis_transform = parse_axis_transform(data.get("axis_transform"))
        node_axis_transforms = parse_node_axis_transforms(
            data.get("node_axis_transforms"),
            axis_transform=axis_transform,
        )
        samples = load_pamap2_calibration_samples()
        sample_id = make_prediction_id()
        samples.append({
            "id": sample_id,
            "label": label,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "windows_by_node": serialize_windows_by_node(validated_windows),
            "resampled_window": data.get("resampled_window"),
            "source_config": {
                "node_order": list(parse_node_order(data.get("node_order"))),
                "axis_transform": axis_transform,
                "node_axis_transforms": {
                    str(node_id): node_axis
                    for node_id, node_axis in node_axis_transforms.items()
                },
                "mag_mode": parse_mag_mode(data.get("mag_mode")),
            },
            "window_summary": summarize_windows_by_node(validated_windows),
        })
        save_pamap2_calibration_samples(samples)

        write_prediction_debug_log(
            "pamap2_calibration_sample",
            sample_id=sample_id,
            label=label,
            sample_count=len(samples),
            counts=calibration_counts(samples),
            resampled_window=data.get("resampled_window"),
        )

        return jsonify({
            "status": "ok",
            "sample_id": sample_id,
            "label": label,
            "sample_count": len(samples),
            "counts": calibration_counts(samples),
            "path": get_pamap2_calibration_path(),
        })

    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        write_prediction_debug_log(
            "pamap2_calibration_sample_error",
            error=str(e),
            received_keys=list(data.keys()) if isinstance(data, dict) else None,
        )
        return jsonify({"error": str(e)}), 500


@activity_bp.route("/predict/pamap2_calibration/clear", methods=["POST"])
def pamap2_calibration_clear_endpoint():
    try:
        save_pamap2_calibration_samples([])
        write_prediction_debug_log("pamap2_calibration_cleared")

        return jsonify({
            "status": "ok",
            "sample_count": 0,
            "counts": {},
            "path": get_pamap2_calibration_path(),
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@activity_bp.route("/predict/pamap2_calibration/sweep", methods=["POST"])
def pamap2_calibration_sweep_endpoint():
    data = None
    prediction_id = make_prediction_id()
    started_at = time.perf_counter()

    if not PAMAP2_CALIBRATION_SWEEP_LOCK.acquire(blocking=False):
        return jsonify({
            "error": "PAMAP2 calibration sweep is already running",
            "prediction_id": prediction_id,
        }), 409

    try:
        data = request.get_json(silent=True) or {}
        samples = load_pamap2_calibration_samples()

        if not samples:
            return jsonify({
                "error": "No PAMAP2 calibration samples saved yet",
                "path": get_pamap2_calibration_path(),
            }), 400

        node_orders = parse_node_order_options(data.get("node_orders", "all"), default_to_all=True)
        axis_transforms = parse_axis_transform_options(
            data.get("axis_transforms", "all"),
            default_to_all=True,
        )
        mag_modes = parse_mag_mode_options(
            data.get("mag_modes", PAMAP2_CALIBRATION_MAG_MODES),
            default_to_all=False,
        )
        node_axis_transforms = (
            parse_node_axis_transforms(data.get("node_axis_transforms"))
            if data.get("node_axis_transforms") is not None
            else None
        )
        top_n = int(data.get("top_n", 20))

        result = run_pamap2_calibration_sweep(
            samples,
            node_orders=node_orders,
            axis_transforms=axis_transforms,
            mag_modes=mag_modes,
            node_axis_transforms=node_axis_transforms,
            top_n=top_n,
        )
        elapsed_ms = round((time.perf_counter() - started_at) * 1000.0, 2)
        saved_best_config = None

        if result.get("best_config"):
            best = result["best_config"]
            saved_best_config = save_pamap2_best_config({
                "node_order": best["node_order"],
                "axis_transform": best["axis_transform"],
                "node_axis_transforms": best["node_axis_transforms"],
                "mag_mode": best["mag_mode"],
                "score": best["score"],
                "accuracy": best["accuracy"],
                "correct_count": best["correct_count"],
                "sample_count": best["sample_count"],
                "counts": result["counts"],
                "mean_target_probability": best["mean_target_probability"],
                "mean_confidence": best["mean_confidence"],
                "mean_cross_entropy": best["mean_cross_entropy"],
                "per_label": best["per_label"],
            })

        write_prediction_debug_log(
            "pamap2_calibration_sweep_success",
            prediction_id=prediction_id,
            sample_count=result["sample_count"],
            counts=result["counts"],
            node_order_count=len(node_orders),
            axis_transform_count=len(axis_transforms),
            mag_modes=list(mag_modes),
            fixed_node_axis_transforms={
                str(node_id): node_axis
                for node_id, node_axis in node_axis_transforms.items()
            } if node_axis_transforms is not None else None,
            tested_configs=result["tested_configs"],
            error_count=len(result["errors"]),
            elapsed_ms=elapsed_ms,
            best_config=saved_best_config,
            top_results=result["results"][:10],
        )

        return jsonify({
            "prediction_id": prediction_id,
            "sample_count": result["sample_count"],
            "counts": result["counts"],
            "node_order_count": len(node_orders),
            "axis_transform_count": len(axis_transforms),
            "mag_modes": list(mag_modes),
            "fixed_node_axis_transforms": {
                str(node_id): node_axis
                for node_id, node_axis in node_axis_transforms.items()
            } if node_axis_transforms is not None else None,
            "tested_configs": result["tested_configs"],
            "errors": result["errors"][:50],
            "best_config": saved_best_config,
            "best_config_path": get_pamap2_best_config_path(),
            "results": result["results"],
            "elapsed_ms": elapsed_ms,
        })

    except ValueError as e:
        write_prediction_debug_log(
            "pamap2_calibration_sweep_validation_error",
            prediction_id=prediction_id,
            error=str(e),
            received_keys=list(data.keys()) if isinstance(data, dict) else None,
        )
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        import traceback
        print("PAMAP2 CALIBRATION SWEEP ERROR:", repr(e), flush=True)
        traceback.print_exc()
        write_prediction_debug_log(
            "pamap2_calibration_sweep_error",
            prediction_id=prediction_id,
            error=str(e),
            received_keys=list(data.keys()) if isinstance(data, dict) else None,
        )
        return jsonify({"error": str(e)}), 500
    finally:
        PAMAP2_CALIBRATION_SWEEP_LOCK.release()

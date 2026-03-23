import os
from typing import Any

import torch
from flask import Blueprint, jsonify, request

from database import db_run

activity_bp = Blueprint("activity", __name__)

WINDOW_SIZE = int(os.getenv("HAR_WINDOW_SIZE", "32"))
FEATURE_KEYS = ("ax", "ay", "az", "gx", "gy", "gz")
CLASS_LABELS = [
    label.strip()
    for label in os.getenv("HAR_CLASS_LABELS", "standing,walking,sitting,lying").split(",")
    if label.strip()
]
MODEL_PATH = os.getenv(
    "HAR_MODEL_PATH",
    os.path.join(os.path.dirname(__file__), "..", "model", "best_model.pt"),
)
DEVICE = torch.device("cuda" if torch.cuda.is_available() else "cpu")

MODEL = None
MODEL_LOAD_ERROR = None
LATEST_FUSED_WINDOW = None
LAST_PREDICTED_LABEL = None
LAST_NODE_ORDER = None


def _safe_int_key(value: str) -> tuple[int, str]:
    try:
        return (0, int(value))
    except (TypeError, ValueError):
        return (1, str(value))


def _load_model() -> None:
    global MODEL, MODEL_LOAD_ERROR

    if MODEL is not None or MODEL_LOAD_ERROR is not None:
        return

    try:
        try:
            model = torch.jit.load(MODEL_PATH, map_location=DEVICE)
        except Exception:
            model = torch.load(MODEL_PATH, map_location=DEVICE, weights_only=False)

        if hasattr(model, "to"):
            model = model.to(DEVICE)
        if hasattr(model, "eval"):
            model.eval()

        MODEL = model
    except Exception as exc:
        MODEL_LOAD_ERROR = str(exc)


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _validate_fused_readings(readings):
    if not isinstance(readings, list):
        return False, "'readings' must be a list"

    if len(readings) != WINDOW_SIZE:
        return False, f"Expected {WINDOW_SIZE} fused timesteps, got {len(readings)}"

    if not readings:
        return False, "No readings provided"

    first = readings[0]
    if not isinstance(first, dict) or not isinstance(first.get("nodes"), dict):
        return False, "Each timestep must contain a 'nodes' dictionary"

    node_order = sorted(first["nodes"].keys(), key=_safe_int_key)
    if not node_order:
        return False, "At least one node is required in each timestep"

    for idx, timestep in enumerate(readings):
        if not isinstance(timestep, dict):
            return False, f"Timestep {idx} must be an object"

        nodes = timestep.get("nodes")
        if not isinstance(nodes, dict):
            return False, f"Timestep {idx} is missing 'nodes'"

        current_order = sorted(nodes.keys(), key=_safe_int_key)
        if current_order != node_order:
            return False, f"Timestep {idx} has inconsistent node ids"

        for node_id in node_order:
            sample = nodes.get(node_id)
            if not isinstance(sample, dict):
                return False, f"Timestep {idx}, node {node_id} must be an object"

            for feature in FEATURE_KEYS:
                if feature not in sample:
                    return False, f"Timestep {idx}, node {node_id} missing '{feature}'"
                if not _is_number(sample[feature]):
                    return False, f"Timestep {idx}, node {node_id}, '{feature}' must be numeric"

    return True, node_order


def _flatten_fused_window(readings, node_order):
    rows = []
    for timestep in readings:
        row = []
        for node_id in node_order:
            sample = timestep["nodes"][node_id]
            for feature in FEATURE_KEYS:
                row.append(float(sample[feature]))
        rows.append(row)
    return rows


def _run_model(window_rows):
    _load_model()

    if MODEL_LOAD_ERROR is not None:
        raise RuntimeError(f"Model could not be loaded: {MODEL_LOAD_ERROR}")
    if MODEL is None:
        raise RuntimeError("Model is not available")

    tensor = torch.tensor(window_rows, dtype=torch.float32, device=DEVICE).unsqueeze(0)

    last_error = None
    candidate_inputs = [tensor, tensor.transpose(1, 2)]

    for model_input in candidate_inputs:
        try:
            with torch.no_grad():
                output = MODEL(model_input)

            if isinstance(output, (tuple, list)):
                output = output[0]

            if not torch.is_tensor(output):
                raise RuntimeError("Model output is not a tensor")

            if output.ndim == 1:
                pred_idx = int(torch.argmax(output).item())
            elif output.ndim >= 2:
                pred_idx = int(torch.argmax(output, dim=1).item())
            else:
                raise RuntimeError("Unexpected model output shape")

            if 0 <= pred_idx < len(CLASS_LABELS):
                return CLASS_LABELS[pred_idx]
            return str(pred_idx)
        except Exception as exc:
            last_error = exc

    raise RuntimeError(f"Inference failed for both input layouts: {last_error}")


def _store_prediction(label, readings, node_order):
    global LATEST_FUSED_WINDOW, LAST_PREDICTED_LABEL, LAST_NODE_ORDER
    LATEST_FUSED_WINDOW = readings
    LAST_PREDICTED_LABEL = label
    LAST_NODE_ORDER = node_order
    db_run("UPDATE labels SET name = ? WHERE id = 1", [label])


@activity_bp.route("/predict", methods=["POST"])
def predict_activity():
    try:
        payload = request.get_json(silent=True) or {}
        readings = payload.get("readings")

        is_valid, validation_result = _validate_fused_readings(readings)
        if not is_valid:
            return jsonify({"message": validation_result}), 400

        node_order = validation_result
        window_rows = _flatten_fused_window(readings, node_order)
        predicted_label = _run_model(window_rows)
        _store_prediction(predicted_label, readings, node_order)

        return jsonify(
            {
                "predicted_label": predicted_label,
                "node_order": node_order,
                "window_size": len(readings),
                "feature_count": len(window_rows[0]) if window_rows else 0,
            }
        )
    except Exception as exc:
        return jsonify({"message": str(exc)}), 500


@activity_bp.route("/predict/latest", methods=["GET"])
def get_latest_prediction():
    return jsonify(
        {
            "predicted_label": LAST_PREDICTED_LABEL,
            "node_order": LAST_NODE_ORDER,
            "has_window": LATEST_FUSED_WINDOW is not None,
        }
    )

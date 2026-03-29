import os
import copy
import torch
import numpy as np
from flask import Blueprint, request, jsonify
from sklearn.preprocessing import StandardScaler

from database import db_run, db_get

activity_bp = Blueprint('activity', __name__)

MODEL = None
SCALER = None
DEVICE = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
WINDOW_SIZE = 32
COMBINED_KEY = '_combined'

LABELS = ['standing', 'walking', 'sitting', 'lying']
REQUIRED_FEATURES = ('ax', 'ay', 'az', 'gx', 'gy', 'gz')
LATEST_WINDOWS_BY_NODE = {}
LAST_NODE_ID = None


class HARNet(torch.nn.Module):
    def __init__(self, num_features, num_classes):
        super().__init__()

        self.conv_block = torch.nn.Sequential(
            torch.nn.Conv1d(num_features, 128, kernel_size=5, padding=2),
            torch.nn.BatchNorm1d(128),
            torch.nn.ReLU(),
            torch.nn.Dropout(0.2),

            torch.nn.Conv1d(128, 128, kernel_size=5, padding=2),
            torch.nn.BatchNorm1d(128),
            torch.nn.ReLU(),
            torch.nn.Dropout(0.2),
        )

        self.lstm = torch.nn.LSTM(
            input_size=128,
            hidden_size=128,
            num_layers=2,
            batch_first=True,
            bidirectional=True,
            dropout=0.2,
        )

        self.classifier = torch.nn.Sequential(
            torch.nn.Linear(256, 128),
            torch.nn.ReLU(),
            torch.nn.Dropout(0.3),
            torch.nn.Linear(128, num_classes),
        )

    def forward(self, x):
        x = x.transpose(1, 2)   # (B, F, T)
        x = self.conv_block(x)  # (B, 128, T)
        x = x.transpose(1, 2)   # (B, T, 128)
        x, _ = self.lstm(x)     # (B, T, 256)
        x = x[:, -1, :]         # last timestep
        x = self.classifier(x)
        return x


def load_model():
    global MODEL, SCALER

    base_dir = os.path.dirname(__file__)
    model_path = os.path.abspath(os.path.join(base_dir, '..', '..', 'model', 'activity_recognition_model.pt'))
    scaler_path = os.path.abspath(os.path.join(base_dir, '..', '..', 'model', 'scaler.npz'))

    print("base_dir:", base_dir)
    print("model_path exists:", os.path.exists(model_path), model_path)
    print("scaler_path exists:", os.path.exists(scaler_path), scaler_path)

    checkpoint = torch.load(model_path, map_location=DEVICE)
    print("checkpoint type:", type(checkpoint))
    if isinstance(checkpoint, dict):
        print("checkpoint keys:", checkpoint.keys())

    MODEL = HARNet(num_features=6, num_classes=4).to(DEVICE)
    MODEL.load_state_dict(checkpoint['model_state'])
    MODEL.eval()

    scaler_np = np.load(scaler_path)
    print("scaler keys:", scaler_np.files)

    SCALER = StandardScaler()
    SCALER.mean_ = scaler_np['mean']
    SCALER.scale_ = scaler_np['scale']
    SCALER.var_ = SCALER.scale_ ** 2
    SCALER.n_features_in_ = len(SCALER.mean_)

    print(f"✓ Model loaded on {DEVICE}")


def predict_activity(sensor_data):
    if MODEL is None or SCALER is None:
        raise RuntimeError("Model or scaler not loaded")

    if len(sensor_data) != WINDOW_SIZE:
        raise ValueError(f"Exactly {WINDOW_SIZE} readings are required")

    data_array = np.array([
        [d['ax'], d['ay'], d['az'], d['gx'], d['gy'], d['gz']]
        for d in sensor_data
    ], dtype=np.float32)

    print("INPUT SAMPLE (first row):", data_array[0], flush=True)
    print("INPUT SAMPLE (last row):", data_array[-1], flush=True)

    data_array = SCALER.transform(data_array)
    data_array = np.nan_to_num(data_array, nan=0.0, posinf=0.0, neginf=0.0)
    data_array = np.clip(data_array, -10.0, 10.0)

    tensor = torch.tensor(data_array, dtype=torch.float32).unsqueeze(0).to(DEVICE)

    with torch.no_grad():
        output = MODEL(tensor)
        probs = torch.softmax(output, dim=1).detach().cpu().numpy()[0]

        prob_map = {
            "standing": float(probs[0]),
            "walking": float(probs[1]),
            "sitting": float(probs[2]),
            "lying": float(probs[3]),
        }
        print("\n=== CLASS PROBABILITIES ===", flush=True)
        print(prob_map, flush=True)

        activity_idx = int(np.argmax(probs))
        confidence = float(probs[activity_idx])

    return LABELS[activity_idx], confidence


def validate_sensor_readings(sensor_data):
    if not isinstance(sensor_data, list):
        raise ValueError('Sensor readings must be a list')

    if len(sensor_data) != WINDOW_SIZE:
        raise ValueError(f'Exactly {WINDOW_SIZE} readings are required')

    for i, reading in enumerate(sensor_data):
        if not isinstance(reading, dict):
            raise ValueError(f'Reading at index {i} must be an object')

        for key in REQUIRED_FEATURES:
            if key not in reading:
                raise ValueError(f"Reading at index {i} is missing '{key}'")
            try:
                float(reading[key])
            except (TypeError, ValueError):
                raise ValueError(f"Reading at index {i} has non-numeric '{key}'")


def validate_windows_by_node(windows_by_node):
    if not isinstance(windows_by_node, dict) or not windows_by_node:
        raise ValueError('windows_by_node must be a non-empty object')

    normalized = {}
    for raw_node_id, readings in windows_by_node.items():
        try:
            node_id = int(raw_node_id)
        except (TypeError, ValueError):
            raise ValueError(f'Invalid node id in windows_by_node: {raw_node_id}')
        validate_sensor_readings(readings)
        normalized[node_id] = readings

    return normalized


def combine_windows_by_node(windows_by_node):
    node_ids = sorted(windows_by_node.keys())
    if not node_ids:
        raise ValueError('At least one node window is required')

    combined = []
    for idx in range(WINDOW_SIZE):
        merged = {}
        for feature in REQUIRED_FEATURES:
            values = [float(windows_by_node[node_id][idx][feature]) for node_id in node_ids]
            merged[feature] = sum(values) / len(values)
        combined.append(merged)

    return combined, node_ids


def upsert_current_label(label):
    row = db_get('SELECT id FROM labels WHERE id = 1')
    if row:
        db_run('UPDATE labels SET name = ? WHERE id = 1', [label])
    else:
        db_run('INSERT INTO labels (id, name) VALUES (1, ?)', [label])


def mark_esp_connected_if_known(node_id):
    if node_id is None:
        return

    row = db_get('SELECT id FROM esp_devices WHERE id = ?', [node_id])
    if row:
        db_run('UPDATE esp_devices SET is_connected = 1 WHERE id = ?', [node_id])
    else:
        db_run('INSERT INTO esp_devices (id, is_connected) VALUES (?, 1)', [node_id])


def remember_latest_window(node_id, readings, predicted_label):
    global LAST_NODE_ID
    key = node_id if node_id is not None else '_default'
    LATEST_WINDOWS_BY_NODE[key] = {
        'node_id': node_id,
        'predicted_label': predicted_label,
        'readings': copy.deepcopy(readings),
    }
    LAST_NODE_ID = key


def remember_latest_combined_window(node_ids, readings, predicted_label):
    global LAST_NODE_ID
    LATEST_WINDOWS_BY_NODE[COMBINED_KEY] = {
        'node_id': None,
        'node_ids': list(node_ids),
        'predicted_label': predicted_label,
        'readings': copy.deepcopy(readings),
    }
    LAST_NODE_ID = COMBINED_KEY


def get_latest_window(node_id=None):
    key = node_id if node_id is not None else LAST_NODE_ID
    if key is None:
        return None
    item = LATEST_WINDOWS_BY_NODE.get(key)
    if item is None and node_id is None:
        item = LATEST_WINDOWS_BY_NODE.get(COMBINED_KEY)
    if item is None and node_id is None:
        item = LATEST_WINDOWS_BY_NODE.get('_default')
    return copy.deepcopy(item) if item is not None else None


def get_all_latest_node_windows():
    windows = []
    for key, value in LATEST_WINDOWS_BY_NODE.items():
        if isinstance(key, int):
            windows.append(copy.deepcopy(value))
    windows.sort(key=lambda item: item.get('node_id', 0))
    return windows


@activity_bp.route('/predict', methods=['POST'])
def predict_endpoint():
    try:
        data = request.get_json() or {}
        node_id = data.get('node_id')
        readings = data.get('readings')
        windows_by_node = data.get('windows_by_node')
        validated_windows = None

        used_node_ids = []
        if windows_by_node is not None:
            validated_windows = validate_windows_by_node(windows_by_node)
            combined_readings, used_node_ids = combine_windows_by_node(validated_windows)
            readings = combined_readings
        else:
            if not readings:
                return jsonify({'error': 'No sensor readings provided'}), 400
            validate_sensor_readings(readings)
            if node_id is not None:
                used_node_ids = [node_id]

        activity, confidence = predict_activity(readings)

        upsert_current_label(activity)

        if validated_windows is not None:
            remember_latest_combined_window(used_node_ids, readings, activity)
            for used_node_id, node_readings in validated_windows.items():
                remember_latest_window(used_node_id, node_readings, activity)
                mark_esp_connected_if_known(used_node_id)
        else:
            remember_latest_window(node_id, readings, activity)
            mark_esp_connected_if_known(node_id)

        response = {
            'node_id': node_id,
            'used_node_ids': used_node_ids or ([node_id] if node_id is not None else []),
            'activity': activity,
            'confidence': round(confidence, 4)
        }
        if windows_by_node is not None:
            response['fusion'] = 'average_per_timestep'

        return jsonify(response)

    except ValueError as e:
        return jsonify({'error': str(e)}), 400

    except Exception as e:
      import traceback
      print("PREDICT ERROR:", repr(e))
      traceback.print_exc()
      return jsonify({'error': str(e)}), 500
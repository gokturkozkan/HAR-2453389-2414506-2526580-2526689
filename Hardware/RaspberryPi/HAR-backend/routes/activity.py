import os
import json
import torch
import numpy as np
from flask import Blueprint, request, jsonify
from sklearn.preprocessing import StandardScaler

from database import db_run

activity_bp = Blueprint('activity', __name__)

MODEL = None
SCALER = None
DEVICE = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
WINDOW_SIZE = 32

LABELS = ['standing', 'walking', 'sitting', 'lying']


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

    checkpoint = torch.load(model_path, map_location=DEVICE)

    MODEL = HARNet(num_features=6, num_classes=4).to(DEVICE)
    MODEL.load_state_dict(checkpoint['model_state'])
    MODEL.eval()

    scaler_np = np.load(scaler_path)
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

    data_array = SCALER.transform(data_array)
    data_array = np.nan_to_num(data_array, nan=0.0, posinf=0.0, neginf=0.0)
    data_array = np.clip(data_array, -10.0, 10.0)

    tensor = torch.tensor(data_array, dtype=torch.float32).unsqueeze(0).to(DEVICE)

    with torch.no_grad():
        output = MODEL(tensor)
        probs = torch.softmax(output, dim=1)
        activity_idx = torch.argmax(probs, dim=1).item()
        confidence = probs[0, activity_idx].item()

    return LABELS[activity_idx], confidence


@activity_bp.route('/predict', methods=['POST'])
def predict_endpoint():
    try:
        data = request.get_json()
        node_id = data.get('node_id')
        readings = data.get('readings')

        if not readings:
            return jsonify({'error': 'No sensor readings provided'}), 400

        activity, confidence = predict_activity(readings)

        db_run(
            'INSERT INTO activity_predictions (node_id, activity, confidence) VALUES (?, ?, ?)',
            [node_id, activity, float(confidence)]
        )

        return jsonify({
            'node_id': node_id,
            'activity': activity,
            'confidence': round(confidence, 4)
        })

    except Exception as e:
        return jsonify({'error': str(e)}), 500
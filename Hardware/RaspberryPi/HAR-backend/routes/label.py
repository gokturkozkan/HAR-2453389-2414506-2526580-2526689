from flask import Blueprint, request, jsonify
import base64
import json
from database import db_get, db_run
from routes.activity import get_all_latest_node_windows, get_latest_window

label_bp = Blueprint('label', __name__)


def clear_label():
    db_run('UPDATE labels SET name = ? WHERE id = 1', [''])


@label_bp.route('/label', methods=['GET'])
def get_label():
    try:
        label_row = db_get('SELECT name FROM labels WHERE id = 1')
        label = label_row['name'] if label_row and label_row.get('name') is not None else ''

        if not label:
            return jsonify({'message': 'No activity label available yet'}), 404

        image_row = db_get('SELECT data FROM unity_images WHERE name = ?', [f'{label}.png']) if label else None
        image_base64 = None

        latest_window = get_latest_window()
        latest_node_id = latest_window.get('node_id') if latest_window else None

        if image_row and image_row.get('data'):
            image_data = image_row['data']
            if isinstance(image_data, bytes):
                image_base64 = base64.b64encode(image_data).decode('utf-8')
            else:
                image_base64 = image_data

        return jsonify({
            'label': label,
            'image': image_base64,
            'hasImage': image_base64 is not None,
            'node_id': latest_node_id,
        })
    except Exception as error:
        print(f'Error fetching label and image: {error}')
        return jsonify({'message': 'Error fetching label and image'}), 500


@label_bp.route('/label', methods=['POST'])
def update_label():
    try:
        data = request.get_json(silent=True) or {}
        label = data.get('label', data.get('name'))

        if not label or not isinstance(label, str):
            return jsonify({'message': 'Label is required and must be a string'}), 400

        label = label.strip()
        if not label:
            return jsonify({'message': 'Label is required and must be a string'}), 400

        requested_node_id = data.get('node_id')
        try:
            requested_node_id = int(requested_node_id) if requested_node_id is not None else None
        except (TypeError, ValueError):
            requested_node_id = None

        previous_label_row = db_get('SELECT name FROM labels WHERE id = 1')
        previous_label = previous_label_row['name'] if previous_label_row else None

        latest_window = get_latest_window(requested_node_id)
        all_node_windows = get_all_latest_node_windows()
        resolved_node_id = requested_node_id
        sensor_data_json = None

        if latest_window:
            if resolved_node_id is None:
                latest_node_id = latest_window.get('node_id')
                resolved_node_id = latest_node_id if isinstance(latest_node_id, int) else None

            latest_readings = latest_window.get('readings')
            if isinstance(latest_readings, list):
                sensor_data_json = json.dumps(latest_readings)

        esp_data_json = json.dumps(all_node_windows) if all_node_windows else None

        db_run('UPDATE labels SET name = ? WHERE id = 1', [label])

        if resolved_node_id is not None and 1 <= resolved_node_id <= 7 and sensor_data_json is not None:
            db_run(
                f'UPDATE labels SET esp{resolved_node_id} = ? WHERE id = 1',
                [sensor_data_json],
            )

        db_run(
            'INSERT INTO relabels (node_id, original_label, new_label, sensor_data, esp_data) VALUES (?, ?, ?, ?, ?)',
            [resolved_node_id, previous_label, label, sensor_data_json, esp_data_json],
        )

        image_row = db_get('SELECT data FROM unity_images WHERE name = ?', [f'{label}.png'])
        image_base64 = None

        if image_row and image_row.get('data'):
            image_data = image_row['data']
            if isinstance(image_data, bytes):
                image_base64 = base64.b64encode(image_data).decode('utf-8')
            else:
                image_base64 = image_data

        return jsonify({
            'message': 'Label updated successfully',
            'label': label,
            'image': image_base64,
            'hasImage': image_base64 is not None,
            'node_id': resolved_node_id,
            'esp_data': esp_data_json,
        })
    except Exception as error:
        print(f'Error updating label: {error}')
        return jsonify({'message': 'Error updating label'}), 500

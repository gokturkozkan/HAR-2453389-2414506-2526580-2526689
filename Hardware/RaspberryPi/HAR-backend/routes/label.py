from flask import Blueprint, request, jsonify
import base64
import json
from database import db_all, db_get, db_run
from routes.activity import get_latest_window

label_bp = Blueprint('label', __name__)

def clear_label():
    """Clear the label in the database."""
    db_run('UPDATE labels SET name = ? WHERE id = 1', [''])  # Set label to empty string


def _get_image_base64(label):
    image_row = db_get('SELECT data FROM unity_images WHERE name = ?', [f'{label}.png'])
    if not image_row or not image_row.get('data'):
        return None

    image_data = image_row['data']
    if isinstance(image_data, bytes):
        return base64.b64encode(image_data).decode('utf-8')
    return image_data


def _resolve_current_label():
    current = db_get('SELECT name FROM labels WHERE id = 1')
    if current and current.get('name'):
        return current['name']
    return None

@label_bp.route('/label', methods=['GET'])
def get_label():
    try:
        label = _resolve_current_label()
        if not label:
            return jsonify({'message': 'No activity label available yet'}), 404

        image_base64 = _get_image_base64(label)
        if not image_base64:
            return jsonify({'message': f'Image not found for label: {label}'}), 404

        return jsonify({
            'label': label,
            'image': image_base64
        })
    except Exception as error:
        print(f'Error fetching label and image: {error}')
        return jsonify({'message': 'Error fetching label and image'}), 500

@label_bp.route('/label', methods=['POST'])
def update_label():
    try:
        data = request.get_json() or {}
        label = data.get('label')
        node_id = data.get('node_id')
        
        if not label or not isinstance(label, str):
            return jsonify({'message': 'Label is required and must be a string'}), 400

        latest = get_latest_window(node_id)
        if not latest:
            return jsonify({'message': 'No recent sensor window available to relabel'}), 400

        previous_label = latest.get('predicted_label')
        sensor_data_json = json.dumps(latest.get('readings', []), separators=(',', ':'))

        db_run(
            'INSERT INTO relabels (node_id, original_label, new_label, sensor_data) VALUES (?, ?, ?, ?)',
            [latest.get('node_id'), previous_label, label, sensor_data_json],
        )

        print(
            f"[RELABEL] node={latest.get('node_id')} from={previous_label} to={label}"
        )
        
        # Manual relabeling is allowed and immediately reflected in /label.
        db_run('UPDATE labels SET name = ? WHERE id = 1', [label])

        image_base64 = _get_image_base64(label)
        if not image_base64:
            return jsonify({'message': f'Image not found for label: {label}'}), 404

        return jsonify({
            'message': 'Label updated successfully',
            'label': label,
            'image': image_base64
        })
    except Exception as error:
        print(f'Error updating label: {error}')
        return jsonify({'message': 'Error updating label'}), 500
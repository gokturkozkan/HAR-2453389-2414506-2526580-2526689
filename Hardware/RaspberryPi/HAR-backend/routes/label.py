from flask import Blueprint, request, jsonify
import base64
from database import db_get, db_run

label_bp = Blueprint('label', __name__)


def clear_label():
    db_run('UPDATE labels SET name = ? WHERE id = 1', [''])


@label_bp.route('/label', methods=['GET'])
def get_label():
    try:
        label_row = db_get('SELECT name FROM labels WHERE id = 1')
        label = label_row['name'] if label_row and label_row.get('name') is not None else ''

        image_row = db_get('SELECT data FROM unity_images WHERE name = ?', [f'{label}.png']) if label else None
        image_base64 = None

        if image_row and image_row.get('data'):
            image_data = image_row['data']
            if isinstance(image_data, bytes):
                image_base64 = base64.b64encode(image_data).decode('utf-8')
            else:
                image_base64 = image_data

        return jsonify({
            'label': label,
            'image': image_base64,
            'hasImage': image_base64 is not None
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

        db_run('UPDATE labels SET name = ? WHERE id = 1', [label])

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
            'hasImage': image_base64 is not None
        })
    except Exception as error:
        print(f'Error updating label: {error}')
        return jsonify({'message': 'Error updating label'}), 500

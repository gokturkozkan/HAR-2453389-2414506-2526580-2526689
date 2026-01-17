from flask import Blueprint, request, jsonify
import base64
from database import db_all, db_get, db_run

label_bp = Blueprint('label', __name__)

def clear_label():
    """Clear the label in the database."""
    db_run('UPDATE labels SET name = ? WHERE id = 1', [''])  # Set label to empty string

@label_bp.route('/label', methods=['GET'])
def get_label():
    try:
        # Get the current label from database
        label_row = db_get('SELECT name FROM labels WHERE id = 1')
        label = label_row.get('name') if label_row else 'idle'
        
        # Default to 'idle' if empty
        if not label:
            label = 'idle'
        
        # Normalize to lowercase for matching
        label_lower = label.lower().strip()
        
        # Find the corresponding image (case-insensitive match)
        image_row = db_get('SELECT data, name FROM unity_images WHERE LOWER(name) = ?', [f'{label_lower}.png'])
        
        if not image_row or not image_row.get('data'):
            return jsonify({'message': f'Image not found for label: {label}'}), 404
        
        # Convert image data to base64
        image_data = image_row['data']
        if isinstance(image_data, bytes):
            image_base64 = base64.b64encode(image_data).decode('utf-8')
        else:
            image_base64 = image_data
        
        return jsonify({
            'label': label_lower,
            'image': image_base64
        })
    except Exception as error:
        print(f'Error fetching label and image: {error}')
        return jsonify({'message': 'Error fetching label and image'}), 500

@label_bp.route('/label', methods=['POST'])
def update_label():
    try:
        data = request.get_json()
        label = data.get('label')
        
        if not label or not isinstance(label, str):
            return jsonify({'message': 'Label is required and must be a string'}), 400
        
        # Normalize to lowercase
        label_lower = label.lower().strip()
        
        # Check if matching image exists (case-insensitive)
        image_row = db_get('SELECT data, name FROM unity_images WHERE LOWER(name) = ?', [f'{label_lower}.png'])
        
        if not image_row or not image_row.get('data'):
            return jsonify({'message': f'Image not found for label: {label_lower}'}), 404
        
        # Update the label in the database (store lowercase)
        db_run('UPDATE labels SET name = ? WHERE id = 1', [label_lower])
        print(f'[label] Updated label to: {label_lower}')
        
        # Convert image data to base64
        image_data = image_row['data']
        if isinstance(image_data, bytes):
            image_base64 = base64.b64encode(image_data).decode('utf-8')
        else:
            image_base64 = image_data
        
        return jsonify({
            'message': 'Label updated successfully',
            'label': label_lower,
            'image': image_base64
        })
    except Exception as error:
        print(f'Error updating label: {error}')
        return jsonify({'message': 'Error updating label'}), 500
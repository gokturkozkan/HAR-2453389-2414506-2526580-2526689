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
        #TODO: MODEL WILL GIVE LABEL HERE:
        #FOR NOW ITS JUST SITTING
        label = "sitting"
        
        # Find the corresponding image in unity_images with matching name (e.g., "sitting.png")
        image_row = db_get('SELECT data FROM unity_images WHERE name = ?', [f'{label}.png'])
        
        if not image_row or not image_row.get('data'):
            return jsonify({'message': f'Image not found for label: {label}'}), 404
        
        # Convert image data to base64
        image_data = image_row['data']
        if isinstance(image_data, bytes):
            image_base64 = base64.b64encode(image_data).decode('utf-8')
        else:
            image_base64 = image_data
        
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
        data = request.get_json()
        label = data.get('label')
        
        if not label or not isinstance(label, str):
            return jsonify({'message': 'Label is required and must be a string'}), 400
        
        # Update the label in the database
        db_run('UPDATE labels SET name = ? WHERE id = 1', [label])
        
        # Get the corresponding image
        image_row = db_get('SELECT data FROM unity_images WHERE name = ?', [f'{label}.png'])
        
        if not image_row or not image_row.get('data'):
            return jsonify({'message': f'Image not found for label: {label}'}), 404
        
        # Convert image data to base64
        image_data = image_row['data']
        if isinstance(image_data, bytes):
            image_base64 = base64.b64encode(image_data).decode('utf-8')
        else:
            image_base64 = image_data
        
        return jsonify({
            'message': 'Label updated successfully',
            'label': label,
            'image': image_base64
        })
    except Exception as error:
        print(f'Error updating label: {error}')
        return jsonify({'message': 'Error updating label'}), 500
from flask import Blueprint, request, jsonify
from database import db_all, db_run, db_get

esp_bp = Blueprint('esp', __name__)

@esp_bp.route('/esp-status', methods=['GET'])
def get_esp_status():
    try:
        id_param = request.args.get('id')
        
        if id_param:
            try:
                device_id = int(id_param)
            except ValueError:
                return jsonify({'message': 'Invalid device ID'}), 400
            
            row = db_get(
                'SELECT id, is_connected as isConnected FROM esp_devices WHERE id = ?',
                [device_id]
            )
            
            if not row:
                return jsonify({'message': 'Device not found'}), 404
            
            device = {
                'id': row['id'],
                'isConnected': bool(row['isConnected'])
            }
            return jsonify(device)
        
        rows = db_all(
            'SELECT id, is_connected as isConnected FROM esp_devices ORDER BY id ASC'
        )
        devices = [
            {'id': r['id'], 'isConnected': bool(r['isConnected'])}
            for r in rows
        ]
        return jsonify(devices)
    except Exception as error:
        print(f'Error fetching ESP status: {error}')
        return jsonify({'message': 'Error fetching ESP status'}), 500

@esp_bp.route('/esp', methods=['GET'])
def get_esp_list():
    try:
        rows = db_all('SELECT id FROM esp_devices ORDER BY id ASC')
        ids = [{'id': r['id']} for r in rows]
        return jsonify(ids)
    except Exception as error:
        print(f'Error fetching ESP ids: {error}')
        return jsonify({'message': 'Error fetching ESPs'}), 500

@esp_bp.route('/esp-status/<int:device_id>', methods=['POST'])
def update_esp_status(device_id):
    try:
        data = request.get_json() or {}
        is_connected = data.get('isConnected')
        
        # Check if device exists
        device = db_get('SELECT id FROM esp_devices WHERE id = ?', [device_id])
        
        if not device:
            # Create new device
            db_run(
                'INSERT INTO esp_devices (id, is_connected) VALUES (?, ?)',
                [device_id, 1 if is_connected else 0]
            )
        else:
            # Update existing device
            db_run(
                'UPDATE esp_devices SET is_connected = ? WHERE id = ?',
                [1 if is_connected else 0, device_id]
            )

        state = 'connected' if is_connected else 'disconnected'
        print(f'[ESP] Node {device_id} marked as {state} in database')
        
        return jsonify({'message': 'Device status updated', 'id': device_id})
    except Exception as error:
        print(f'Error updating ESP status: {error}')
        return jsonify({'message': 'Error updating ESP status'}), 500

@esp_bp.route('/esp-devices/init', methods=['POST'])
def init_esp_devices():
    try:
        data = request.get_json()
        count = data.get('count', 2)
        
        for i in range(1, count + 1):
            exists = db_get('SELECT id FROM esp_devices WHERE id = ?', [i])
            if not exists:
                db_run(
                    'INSERT INTO esp_devices (id, is_connected) VALUES (?, ?)',
                    [i, 0]
                )
        
        return jsonify({'message': f'Initialized {count} ESP devices'})
    except Exception as error:
        print(f'Error initializing ESP devices: {error}')
        return jsonify({'message': 'Error initializing ESP devices'}), 500

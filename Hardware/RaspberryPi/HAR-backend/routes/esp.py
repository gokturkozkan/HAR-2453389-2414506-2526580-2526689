from flask import Blueprint, request, jsonify
from database import db_all, db_run, db_get
from tdma_control import TdmaControlError, TdmaBackendController

esp_bp = Blueprint('esp', __name__)
tdma_controller = TdmaBackendController()


def enrich_with_runtime_status(device):
    try:
        runtime = tdma_controller.get_status(device['id'])
    except TdmaControlError:
        return device

    if not runtime.get('updatedAt'):
        return device

    enriched = {
        **device,
        'status': runtime.get('status'),
        'detail': runtime.get('detail'),
        'name': runtime.get('name'),
        'port': runtime.get('port'),
        'updatedAt': runtime.get('updatedAt'),
    }

    if runtime.get('latestLine'):
        enriched['latestLine'] = runtime.get('latestLine')

    return enriched


def command_response(handler, device_id):
    try:
        result = handler(device_id)
        return jsonify(result)
    except TdmaControlError as error:
        return jsonify(error.to_response()), error.status_code

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
            return jsonify(enrich_with_runtime_status(device))
        
        rows = db_all(
            'SELECT id, is_connected as isConnected FROM esp_devices ORDER BY id ASC'
        )
        devices = [
            enrich_with_runtime_status({'id': r['id'], 'isConnected': bool(r['isConnected'])})
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


@esp_bp.route('/esp/<int:device_id>/connect', methods=['POST'])
def connect_esp_device(device_id):
    return command_response(tdma_controller.connect_node, device_id)


@esp_bp.route('/esp/<int:device_id>/disconnect', methods=['POST'])
def disconnect_esp_device(device_id):
    return command_response(tdma_controller.disconnect_node, device_id)


@esp_bp.route('/esp/<int:device_id>/reconnect', methods=['POST'])
def reconnect_esp_device(device_id):
    return command_response(tdma_controller.reconnect_node, device_id)


@esp_bp.route('/esp/<int:device_id>/probe', methods=['POST'])
def probe_esp_device(device_id):
    return command_response(tdma_controller.probe_node, device_id)

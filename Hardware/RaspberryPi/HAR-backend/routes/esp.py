from flask import Blueprint, request, jsonify
from database import db_all, db_run, db_get

esp_bp = Blueprint('esp', __name__)
ESP_STATES = {'joining', 'synced', 'streaming', 'stale', 'disconnected'}


def serialize_device(row):
    return {
        'id': row['id'],
        'isConnected': bool(row['isConnected']),
        'state': row.get('state') or ('streaming' if row['isConnected'] else 'disconnected'),
        'lastSeenMs': row.get('lastSeenMs'),
        'lastSeq': int(row.get('lastSeq') or 0),
        'missedPackets': int(row.get('missedPackets') or 0),
    }


def normalize_state(raw_state, is_connected):
    if isinstance(raw_state, str) and raw_state in ESP_STATES:
        return raw_state
    return 'streaming' if bool(is_connected) else 'disconnected'


def normalize_optional_int(raw_value, field_name):
    if raw_value is None:
        return None
    try:
        return int(raw_value)
    except (TypeError, ValueError):
        raise ValueError(f'Invalid {field_name}')

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
                '''
                SELECT
                    id,
                    is_connected as isConnected,
                    state,
                    last_seen_ms as lastSeenMs,
                    last_seq as lastSeq,
                    missed_packets as missedPackets
                FROM esp_devices
                WHERE id = ?
                ''',
                [device_id]
            )
            
            if not row:
                return jsonify({'message': 'Device not found'}), 404
            
            return jsonify(serialize_device(row))
        
        rows = db_all(
            '''
            SELECT
                id,
                is_connected as isConnected,
                state,
                last_seen_ms as lastSeenMs,
                last_seq as lastSeq,
                missed_packets as missedPackets
            FROM esp_devices
            ORDER BY id ASC
            '''
        )
        devices = [serialize_device(r) for r in rows]
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
        raw_is_connected = data.get('isConnected')
        existing = db_get(
            '''
            SELECT
                id,
                is_connected as isConnected,
                state,
                last_seen_ms as lastSeenMs,
                last_seq as lastSeq,
                missed_packets as missedPackets
            FROM esp_devices
            WHERE id = ?
            ''',
            [device_id]
        )
        if data.get('state') is None and raw_is_connected is None and existing is not None:
            state = existing.get('state') or ('streaming' if existing.get('isConnected') else 'disconnected')
        else:
            state = normalize_state(data.get('state'), raw_is_connected if raw_is_connected is not None else False)
        is_connected = bool(raw_is_connected) if raw_is_connected is not None else (state == 'streaming')
        last_seen_ms = normalize_optional_int(data.get('lastSeenMs'), 'lastSeenMs')
        last_seq = normalize_optional_int(data.get('lastSeq'), 'lastSeq')
        missed_packets = normalize_optional_int(data.get('missedPackets'), 'missedPackets')
        
        if existing is None:
            db_run(
                '''
                INSERT INTO esp_devices (
                    id,
                    is_connected,
                    state,
                    last_seen_ms,
                    last_seq,
                    missed_packets
                ) VALUES (?, ?, ?, ?, ?, ?)
                ''',
                [
                    device_id,
                    1 if is_connected else 0,
                    state,
                    last_seen_ms,
                    last_seq if last_seq is not None else 0,
                    missed_packets if missed_packets is not None else 0,
                ]
            )
        else:
            if last_seen_ms is None and 'lastSeenMs' not in data:
                last_seen_ms = existing.get('lastSeenMs')
            if last_seq is None and 'lastSeq' not in data:
                last_seq = existing.get('lastSeq')
            if missed_packets is None and 'missedPackets' not in data:
                missed_packets = existing.get('missedPackets')
            if raw_is_connected is None and 'isConnected' not in data:
                is_connected = bool(existing.get('isConnected')) if state == existing.get('state') else (state == 'streaming')

            db_run(
                '''
                UPDATE esp_devices
                SET
                    is_connected = ?,
                    state = ?,
                    last_seen_ms = ?,
                    last_seq = ?,
                    missed_packets = ?
                WHERE id = ?
                ''',
                [
                    1 if is_connected else 0,
                    state,
                    last_seen_ms,
                    last_seq if last_seq is not None else 0,
                    missed_packets if missed_packets is not None else 0,
                    device_id,
                ]
            )

        print(
            f'[ESP] Node {device_id} marked as {state} '
            f'(connected={is_connected}, seq={last_seq}, missed={missed_packets})'
        )
        
        updated = db_get(
            '''
            SELECT
                id,
                is_connected as isConnected,
                state,
                last_seen_ms as lastSeenMs,
                last_seq as lastSeq,
                missed_packets as missedPackets
            FROM esp_devices
            WHERE id = ?
            ''',
            [device_id]
        )
        return jsonify({'message': 'Device status updated', 'device': serialize_device(updated)})
    except ValueError as error:
        return jsonify({'message': str(error)}), 400
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
                    '''
                    INSERT INTO esp_devices (
                        id,
                        is_connected,
                        state,
                        last_seen_ms,
                        last_seq,
                        missed_packets
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    ''',
                    [i, 0, 'disconnected', None, 0, 0]
                )
        
        return jsonify({'message': f'Initialized {count} ESP devices'})
    except Exception as error:
        print(f'Error initializing ESP devices: {error}')
        return jsonify({'message': 'Error initializing ESP devices'}), 500

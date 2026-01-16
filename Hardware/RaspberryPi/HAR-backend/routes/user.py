from flask import Blueprint, request, jsonify
import bcrypt
from database import db_get, db_run

user_bp = Blueprint('user', __name__)

@user_bp.route('/user/update', methods=['POST'])
def update_user():
    try:
        data = request.get_json()
        credentials = data.get('credentials', {})
        user_id = data.get('userId')
        next_username = credentials.get('username', '').strip()
        
        if not next_username:
            return jsonify({'message': 'Username is required'}), 400
        
        if not user_id:
            return jsonify({'message': 'User ID is required'}), 400
        
        # Check if the user exists
        user = db_get('SELECT id, username FROM users WHERE id = ?', [user_id])
        if not user:
            return jsonify({'message': 'User not found'}), 404
        
        # Check if username is already taken by another user
        existing = db_get(
            'SELECT id FROM users WHERE username = ? AND id != ?',
            [next_username, user_id]
        )
        if existing:
            return jsonify({'message': 'Username already taken'}), 409
        
        # Update the username
        db_run('UPDATE users SET username = ? WHERE id = ?', [next_username, user_id])
        
        return jsonify({
            'user': {
                'id': user_id,
                'username': next_username
            }
        })
    except Exception as error:
        print(f'Error updating user: {error}')
        return jsonify({'message': 'Error updating credentials'}), 500

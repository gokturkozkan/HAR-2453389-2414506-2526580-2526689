from flask import Blueprint, request, jsonify
from database import db_get, db_run
import bcrypt
import uuid

auth_bp = Blueprint('auth', __name__)

@auth_bp.route('/register', methods=['POST'])
def register():
    try:
        data = request.get_json()
        credentials = data.get('credentials', {})
        username = credentials.get('username')
        password = credentials.get('password')
        
        if not username or not password:
            return jsonify({'message': 'Username and password required'}), 400
        
        # Check if user already exists
        existing_user = db_get('SELECT id FROM users WHERE username = ?', [username])
        if existing_user:
            return jsonify({'message': 'User already exists'}), 409
        
        # Hash password
        hashed_password = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt())
        user_id = str(uuid.uuid4())
        
        # Create user
        db_run(
            'INSERT INTO users (id, username, password) VALUES (?, ?, ?)',
            [user_id, username, hashed_password.decode('utf-8')]
        )
        
        return jsonify({
            'user': {
                'id': user_id,
                'username': username
            }
        }), 201
    except Exception as error:
        print(f'Registration error: {error}')
        return jsonify({'message': 'Error creating account'}), 500

@auth_bp.route('/login', methods=['POST'])
def login():
    try:
        print("api request received: login")
        data = request.get_json()
        credentials = data.get('credentials', {})
        username = credentials.get('username')
        password = credentials.get('password')
        
        if not username or not password:
            return jsonify({'message': 'Username and password required'}), 400
        
        # Find user
        user = db_get(
            'SELECT id, username, password FROM users WHERE username = ?',
            [username]
        )
        
        if not user:
            return jsonify({'message': 'Invalid username or password'}), 401
        
        # Verify password
        stored_password = user['password'].encode('utf-8') if isinstance(user['password'], str) else user['password']
        password_valid = bcrypt.checkpw(password.encode('utf-8'), stored_password)
        
        if not password_valid:
            return jsonify({'message': 'Invalid username or password'}), 401
        
        return jsonify({
            'user': {
                'id': user['id'],
                'username': user['username']
            }
        })
    except Exception as error:
        print(f'Login error: {error}')
        return jsonify({'message': 'Error during login'}), 500

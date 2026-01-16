from flask import Flask, jsonify
from flask_cors import CORS
from dotenv import load_dotenv
import os
import signal
import sys
from database import init_database, close_database
from routes.auth import auth_bp
from routes.esp import esp_bp
from routes.admin import admin_bp
from routes.user import user_bp
from routes.label import label_bp, clear_label

load_dotenv()

app = Flask(__name__)
CORS(app, resources={
    r"/*": {
        "origins": "*",
        "methods": ["GET", "POST", "PUT", "DELETE"],
        "allow_headers": ["Content-Type", "Authorization"]
    }
})

# Configure app
app.config['JSON_SORT_KEYS'] = False

# Register blueprints
app.register_blueprint(auth_bp)
app.register_blueprint(esp_bp)
app.register_blueprint(admin_bp)
app.register_blueprint(user_bp)
app.register_blueprint(label_bp)

# Health check endpoint
@app.route('/health', methods=['GET'])
def health():
    from datetime import datetime
    return jsonify({
        'status': 'ok',
        'timestamp': datetime.utcnow().isoformat()
    })

# 404 handler
@app.errorhandler(404)
def not_found(error):
    return jsonify({'message': 'Route not found'}), 404


def graceful_shutdown(signum, frame):
    print('\nShutting down gracefully...')
    close_database()
    sys.exit(0)

if __name__ == '__main__':
    # Register signal handlers
    signal.signal(signal.SIGINT, graceful_shutdown)
    signal.signal(signal.SIGTERM, graceful_shutdown)
    
    try:
        init_database()
        print('Database initialized')
        clear_label()
        
        PORT = int(os.getenv('PORT', 3000))
        ENV = os.getenv('NODE_ENV', 'development')
        
        print(f'HAR Backend running on http://localhost:{PORT}')
        print(f'Accessible on LAN at http://<your-ip>:{PORT}')
        print(f'Environment: {ENV}')
        
        app.run(host='0.0.0.0', port=PORT, debug=(ENV == 'development'))
    except Exception as error:
        print(f'Failed to start server: {error}')
        sys.exit(1)

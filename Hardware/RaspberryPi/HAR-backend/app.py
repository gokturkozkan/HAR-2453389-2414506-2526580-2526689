from flask import Flask, jsonify
from flask_cors import CORS
from dotenv import load_dotenv
import os
import signal
import sys

from database import init_database, close_database, db_run
from routes.auth import auth_bp
from routes.esp import esp_bp
from routes.admin import admin_bp
from routes.user import user_bp
from routes.label import label_bp, clear_label
from routes.activity import (
    activity_bp,
    load_model,
    DEFAULT_AXIS_TRANSFORM,
    DEFAULT_MAG_MODE,
    DEFAULT_NODE_AXIS_TRANSFORMS,
    DEFAULT_NODE_ORDER,
    get_pamap2_best_config_path,
    get_pamap2_calibration_path,
    load_pamap2_best_config,
)

load_dotenv()

app = Flask(__name__)

CORS(app, resources={
    r"/*": {
        "origins": "*",
        "methods": ["GET", "POST", "PUT", "DELETE"],
        "allow_headers": ["Content-Type", "Authorization"]
    }
})

app.config["JSON_SORT_KEYS"] = False

# ============================================================
# Blueprint Registration
# ============================================================

app.register_blueprint(auth_bp)
app.register_blueprint(esp_bp)
app.register_blueprint(admin_bp)
app.register_blueprint(user_bp)
app.register_blueprint(label_bp)
app.register_blueprint(activity_bp)


# ============================================================
# Health Check
# ============================================================

@app.route("/health", methods=["GET"])
def health():
    from datetime import datetime

    return jsonify({
        "status": "ok",
        "service": "HAR Backend",
        "model": "pamap2_basic_har_model.keras",
        "model_profile": "pamap2_basic_keras",
        "window_size": 200,
        "pamap2_node_order": list(DEFAULT_NODE_ORDER),
        "pamap2_axis_transform": DEFAULT_AXIS_TRANSFORM,
        "pamap2_node_axis_transforms": {
            str(node_id): node_axis
            for node_id, node_axis in DEFAULT_NODE_AXIS_TRANSFORMS.items()
        },
        "pamap2_mag_mode": DEFAULT_MAG_MODE,
        "pamap2_calibration_path": get_pamap2_calibration_path(),
        "pamap2_best_config_path": get_pamap2_best_config_path(),
        "pamap2_best_config": load_pamap2_best_config(),
        "nodes": {
            "1": "wrist",
            "2": "chest",
            "3": "ankle"
        },
        "timestamp": datetime.utcnow().isoformat()
    })


# ============================================================
# Error Handlers
# ============================================================

@app.errorhandler(404)
def not_found(error):
    return jsonify({"message": "Route not found"}), 404


# ============================================================
# Shutdown Handling
# ============================================================

def graceful_shutdown(signum, frame):
    print("\nShutting down gracefully...")
    try:
        db_run("UPDATE esp_devices SET is_connected = 0")
    except Exception as error:
        print(f"Failed to disconnect ESP devices: {error}")
    close_database()
    sys.exit(0)


# ============================================================
# Startup
# ============================================================

def start_server():
    init_database()
    print("Database initialized")

    clear_label()
    print("Current label cleared")

    print("Loading PAMAP2 HAR model...")
    load_model()
    print("Model loaded successfully")

    port = int(os.getenv("PORT", 3000))
    env = os.getenv("NODE_ENV", "development")

    print(f"HAR Backend running on http://localhost:{port}")
    print(f"Accessible on LAN at http://<your-ip>:{port}")
    print(f"Environment: {env}")
    print("Prediction endpoint: POST /predict")
    print("Expected payload: windows_by_node with nodes 1, 2, 3")

    app.run(
        host="0.0.0.0",
        port=port,
        debug=(env == "development"),
        use_reloader=False
    )


if __name__ == "__main__":
    signal.signal(signal.SIGINT, graceful_shutdown)
    signal.signal(signal.SIGTERM, graceful_shutdown)

    try:
        start_server()

    except Exception as error:
        print(f"Failed to start server: {error}")
        close_database()
        sys.exit(1)

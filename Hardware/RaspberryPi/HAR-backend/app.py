from flask import Flask, jsonify, request
from flask_cors import CORS
from dotenv import load_dotenv
import os
import signal
import sys
import threading

from database import init_database, close_database
from routes.auth import auth_bp
from routes.esp import esp_bp
from routes.admin import admin_bp
from routes.user import user_bp
from routes.label import label_bp, clear_label
from routes.activity import activity_bp, load_model

from remote_controller import UnityRemoteClient

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

app.register_blueprint(auth_bp)
app.register_blueprint(esp_bp)
app.register_blueprint(admin_bp)
app.register_blueprint(user_bp)
app.register_blueprint(label_bp)
app.register_blueprint(activity_bp)

remote_client = None
remote_lock = threading.Lock()


def init_remote_client():
    global remote_client
    with remote_lock:
        if remote_client is None:
            remote_client = UnityRemoteClient()
    return remote_client


def get_remote_client():
    global remote_client
    return remote_client


@app.route("/health", methods=["GET"])
def health():
    from datetime import datetime
    return jsonify({
        "status": "ok",
        "timestamp": datetime.utcnow().isoformat()
    })


@app.route("/remote/status", methods=["GET"])
def remote_status():
    global remote_client

    if remote_client is None:
        return jsonify({
            "initialized": False,
            "connected": False,
            "host": None,
            "port": None
        }), 200

    return jsonify({
        "initialized": True,
        "connected": remote_client.is_connected(),
        "host": remote_client.host,
        "port": remote_client.port
    }), 200


@app.route("/remote/connect", methods=["POST"])
def remote_connect():
    global remote_client

    with remote_lock:
        if remote_client is None:
            remote_client = UnityRemoteClient()

        if remote_client.is_connected():
            return jsonify({
                "message": "Already connected",
                "host": remote_client.host,
                "port": remote_client.port
            }), 200

        try:
            remote_client.connect()
            return jsonify({
                "message": "Connected to bridge server",
                "host": remote_client.host,
                "port": remote_client.port
            }), 200
        except Exception as e:
            return jsonify({
                "message": "Failed to connect",
                "error": str(e)
            }), 500


@app.route("/remote/disconnect", methods=["POST"])
def remote_disconnect():
    global remote_client

    with remote_lock:
        if remote_client is None or not remote_client.is_connected():
            return jsonify({"message": "Not connected"}), 200

        try:
            remote_client.close()
            return jsonify({"message": "Disconnected"}), 200
        except Exception as e:
            return jsonify({
                "message": "Failed to disconnect",
                "error": str(e)
            }), 500


@app.route("/remote/send-label", methods=["POST"])
def remote_send_label():
    global remote_client

    data = request.get_json(silent=True) or {}
    label = data.get("label")

    if not label or not isinstance(label, str):
        return jsonify({"message": "label is required"}), 400

    with remote_lock:
        if remote_client is None or not remote_client.is_connected():
            return jsonify({"message": "Remote controller is not connected"}), 400

        try:
            remote_client.send_label(label.strip(), source="backend-api")
            return jsonify({
                "message": "Label sent successfully",
                "label": label.strip()
            }), 200
        except Exception as e:
            return jsonify({
                "message": "Failed to send label",
                "error": str(e)
            }), 500


@app.errorhandler(404)
def not_found(error):
    return jsonify({"message": "Route not found"}), 404


def graceful_shutdown(signum, frame):
    global remote_client

    print("\nShutting down gracefully...")

    try:
        if remote_client is not None and remote_client.is_connected():
            remote_client.close()
    except Exception as e:
        print(f"Remote client shutdown error: {e}")

    close_database()
    sys.exit(0)


if __name__ == "__main__":
    signal.signal(signal.SIGINT, graceful_shutdown)
    signal.signal(signal.SIGTERM, graceful_shutdown)

    try:
        init_database()
        print("Database initialized")
        clear_label()
        load_model()
        init_remote_client()

        PORT = int(os.getenv("PORT", 3000))
        ENV = os.getenv("NODE_ENV", "development")

        print(f"HAR Backend running on http://localhost:{PORT}")
        print(f"Accessible on LAN at http://<your-ip>:{PORT}")
        print(f"Environment: {ENV}")

        app.run(host="0.0.0.0", port=PORT, debug=(ENV == "development"))

    except Exception as error:
        print(f"Failed to start server: {error}")
        sys.exit(1)

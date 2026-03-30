from datetime import datetime, timedelta, timezone

from flask import Blueprint, jsonify, request

from database import db_all, db_get, db_run

esp_bp = Blueprint("esp", __name__)

ESP_STATUS_SELECT = (
    "SELECT id, is_connected, transport, state, last_seen_ms, last_seen_at, "
    "last_seq, missed_packets, boot_id, firmware_version, last_error "
    "FROM esp_devices"
)
VALID_STATES = {"joining", "synced", "streaming", "stale", "disconnected"}


def default_esp_status(device_id):
    return {
        "id": device_id,
        "isConnected": False,
        "transport": None,
        "state": "disconnected",
        "lastSeenMs": None,
        "lastSeenAt": None,
        "lastSeq": 0,
        "missedPackets": 0,
        "bootId": None,
        "firmwareVersion": None,
        "lastError": None,
    }


def row_to_status(row):
    status = default_esp_status(row["id"])
    status.update(
        {
            "isConnected": bool(row.get("is_connected")),
            "transport": row.get("transport"),
            "state": row.get("state") or ("streaming" if row.get("is_connected") else "disconnected"),
            "lastSeenMs": row.get("last_seen_ms"),
            "lastSeenAt": row.get("last_seen_at"),
            "lastSeq": row.get("last_seq") or 0,
            "missedPackets": row.get("missed_packets") or 0,
            "bootId": row.get("boot_id"),
            "firmwareVersion": row.get("firmware_version"),
            "lastError": row.get("last_error"),
        }
    )
    status["isConnected"] = status["state"] == "streaming"
    return status


def optional_int(value, field_name, minimum=None):
    if value is None or value == "":
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field_name} must be an integer") from exc
    if minimum is not None and parsed < minimum:
        raise ValueError(f"{field_name} must be >= {minimum}")
    return parsed


def optional_text(value):
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def optional_state(value):
    if value is None:
        return None
    state = str(value).strip().lower()
    if state not in VALID_STATES:
        raise ValueError(f"state must be one of: {', '.join(sorted(VALID_STATES))}")
    return state


def derive_last_seen_at(last_seen_ms, last_seen_at):
    if last_seen_at:
        return last_seen_at
    if last_seen_ms is None:
        return None
    ts = datetime.now(timezone.utc) - timedelta(milliseconds=int(last_seen_ms))
    return ts.isoformat()


def load_status(device_id):
    row = db_get(f"{ESP_STATUS_SELECT} WHERE id = ?", [device_id])
    if not row:
        return None
    return row_to_status(row)


@esp_bp.route("/esp-status", methods=["GET"])
def get_esp_status():
    try:
        id_param = request.args.get("id")

        if id_param:
            try:
                device_id = int(id_param)
            except ValueError:
                return jsonify({"message": "Invalid device ID"}), 400

            device = load_status(device_id)
            if not device:
                return jsonify({"message": "Device not found"}), 404
            return jsonify(device)

        rows = db_all(f"{ESP_STATUS_SELECT} ORDER BY id ASC")
        return jsonify([row_to_status(row) for row in rows])
    except Exception as error:
        print(f"Error fetching ESP status: {error}")
        return jsonify({"message": "Error fetching ESP status"}), 500


@esp_bp.route("/esp", methods=["GET"])
def get_esp_list():
    try:
        rows = db_all("SELECT id FROM esp_devices ORDER BY id ASC")
        ids = [{"id": row["id"]} for row in rows]
        return jsonify(ids)
    except Exception as error:
        print(f"Error fetching ESP ids: {error}")
        return jsonify({"message": "Error fetching ESPs"}), 500


@esp_bp.route("/esp-status/<int:device_id>", methods=["POST"])
def update_esp_status(device_id):
    try:
        data = request.get_json() or {}
        status = load_status(device_id) or default_esp_status(device_id)

        if "transport" in data:
            status["transport"] = optional_text(data.get("transport"))

        if "state" in data:
            status["state"] = optional_state(data.get("state"))

        if "isConnected" in data:
            is_connected = data.get("isConnected")
            status["isConnected"] = bool(is_connected) if is_connected is not None else False
            if "state" not in data:
                status["state"] = "streaming" if status["isConnected"] else "disconnected"

        if status["state"] is None:
            status["state"] = "streaming" if status["isConnected"] else "disconnected"
        status["isConnected"] = status["state"] == "streaming"

        if "lastSeenMs" in data:
            status["lastSeenMs"] = optional_int(data.get("lastSeenMs"), "lastSeenMs", minimum=0)

        if "lastSeenAt" in data or "last_seen_at" in data:
            raw_last_seen_at = data.get("lastSeenAt", data.get("last_seen_at"))
            status["lastSeenAt"] = optional_text(raw_last_seen_at)

        if "lastSeenMs" in data or "lastSeenAt" in data or "last_seen_at" in data:
            status["lastSeenAt"] = derive_last_seen_at(status["lastSeenMs"], status["lastSeenAt"])

        if "lastSeq" in data:
            status["lastSeq"] = optional_int(data.get("lastSeq"), "lastSeq", minimum=0) or 0

        if "missedPackets" in data:
            status["missedPackets"] = (
                optional_int(data.get("missedPackets"), "missedPackets", minimum=0) or 0
            )

        if "bootId" in data:
            status["bootId"] = optional_int(data.get("bootId"), "bootId", minimum=0)

        if "firmwareVersion" in data:
            status["firmwareVersion"] = optional_int(
                data.get("firmwareVersion"), "firmwareVersion", minimum=0
            )

        if "lastError" in data:
            status["lastError"] = optional_text(data.get("lastError"))

        existing = db_get("SELECT id FROM esp_devices WHERE id = ?", [device_id])
        params = [
            device_id,
            1 if status["isConnected"] else 0,
            status["transport"],
            status["state"],
            status["lastSeenMs"],
            status["lastSeenAt"],
            status["lastSeq"],
            status["missedPackets"],
            status["bootId"],
            status["firmwareVersion"],
            status["lastError"],
        ]

        if existing:
            db_run(
                "UPDATE esp_devices "
                "SET is_connected = ?, transport = ?, state = ?, last_seen_ms = ?, "
                "last_seen_at = ?, last_seq = ?, missed_packets = ?, boot_id = ?, "
                "firmware_version = ?, last_error = ? "
                "WHERE id = ?",
                params[1:] + [device_id],
            )
        else:
            db_run(
                "INSERT INTO esp_devices "
                "(id, is_connected, transport, state, last_seen_ms, last_seen_at, "
                "last_seq, missed_packets, boot_id, firmware_version, last_error) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                params,
            )

        print(
            f"[ESP] Node {device_id} marked as {status['state']} via "
            f"{status['transport'] or 'unknown transport'}"
        )

        return jsonify({"message": "Device status updated", **status})
    except ValueError as error:
        return jsonify({"message": str(error)}), 400
    except Exception as error:
        print(f"Error updating ESP status: {error}")
        return jsonify({"message": "Error updating ESP status"}), 500


@esp_bp.route("/esp-devices/init", methods=["POST"])
def init_esp_devices():
    try:
        data = request.get_json() or {}
        count = data.get("count", 2)

        for device_id in range(1, count + 1):
            exists = db_get("SELECT id FROM esp_devices WHERE id = ?", [device_id])
            if not exists:
                db_run(
                    "INSERT INTO esp_devices (id, is_connected, state) VALUES (?, ?, ?)",
                    [device_id, 0, "disconnected"],
                )

        return jsonify({"message": f"Initialized {count} ESP devices"})
    except Exception as error:
        print(f"Error initializing ESP devices: {error}")
        return jsonify({"message": "Error initializing ESP devices"}), 500

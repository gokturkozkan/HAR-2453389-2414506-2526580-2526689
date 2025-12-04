import socket
import threading
import json
import random
import string
import time
import hmac
import hashlib
import sys
from datetime import datetime
from pathlib import Path

# -------------------------------
# CONFIG
# -------------------------------
HOST = "0.0.0.0"
TCP_PORT = 5005
DISCOVERY_PORT = 5006
LOG_FILE = Path("unity_commands.log")

PAIRING_WINDOW_SECONDS = 120  # seconds to accept first pairing

# Must match SALT in remote_controller.py
SALT = b"unity-bridge-salt-01"

# -------------------------------
# GLOBAL STATE
# -------------------------------
SECRET_HASH = None      # HMAC-SHA256(code, SALT) hex
PAIRING_START_TIME = time.time()
ALLOWED_IP = None       # Once paired, only this IP is allowed

# -------------------------------
# HASHING / SETUP
# -------------------------------
def compute_secret_hash(code: str) -> str:
    return hmac.new(SALT, code.encode("utf-8"), hashlib.sha256).hexdigest()

def init_secret_from_argv():
    global SECRET_HASH, PAIRING_START_TIME

    if len(sys.argv) < 2:
        print("ERROR: Pairing code must be passed as first argument.")
        print("Usage: python bridge_server.py <PAIRING_CODE>")
        input("Press ENTER to close...")
        sys.exit(1)

    pairing_code = sys.argv[1].strip()
    if not pairing_code:
        print("ERROR: Empty pairing code.")
        input("Press ENTER to close...")
        sys.exit(1)

    SECRET_HASH = compute_secret_hash(pairing_code)
    PAIRING_START_TIME = time.time()

    print("\n======================")
    print(" UNITY BRIDGE STARTED ")
    print("======================")
    print("PAIRING MODE:")
    print(f"  Pairing code provided by Unity: '{pairing_code}'")
    print(f"  Pairing window: {PAIRING_WINDOW_SECONDS} seconds")
    print("======================\n")

# -------------------------------
# LOGGING
# -------------------------------
def log_message(message_dict):
    """
    Instead of appending lines, always overwrite unity_commands.log
    with ONLY the latest JSON object. So the file always contains
    a single JSON object.
    """
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)

    if "timestamp" not in message_dict:
        message_dict["timestamp"] = datetime.utcnow().isoformat() + "Z"

    # Overwrite the file each time (mode="w")
    with LOG_FILE.open("w", encoding="utf-8") as f:
        json.dump(message_dict, f, ensure_ascii=False)


# -------------------------------
# TCP HANDLER
# -------------------------------
def handle_client(conn, addr):
    global ALLOWED_IP
    client_ip, client_port = addr

    # Enforce IP restriction once paired
    if ALLOWED_IP is not None and client_ip != ALLOWED_IP:
        print(f"[SECURITY] TCP from disallowed IP {client_ip} (allowed: {ALLOWED_IP}). Closing.")
        conn.close()
        return

    print(f"[INFO] New TCP connection from {addr}")

    with conn:
        buffer = ""
        while True:
            data = conn.recv(1024)
            if not data:
                print(f"[INFO] TCP connection closed by {addr}")
                break

            buffer += data.decode("utf-8")
            while "\n" in buffer:
                line, buffer = buffer.split("\n", 1)
                line = line.strip()
                if not line:
                    continue

                try:
                    msg = json.loads(line)
                except Exception:
                    print(f"[ERROR] Invalid JSON from {addr}: {line}")
                    continue

                # Check hashed secret
                if msg.get("secret") != SECRET_HASH:
                    print(f"[SECURITY] Invalid secret from {addr}, ignoring.")
                    continue

                # If ALLOWED_IP still None, lock to this client
                if ALLOWED_IP is None:
                    ALLOWED_IP = client_ip
                    print(f"[PAIRING] Locking client IP to {ALLOWED_IP}")

                print(f"[OK] {addr}: {msg}")
                log_message(msg)

# -------------------------------
# TCP SERVER
# -------------------------------
def tcp_server():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind((HOST, TCP_PORT))
        s.listen()
        print(f"[INFO] TCP server listening on {HOST}:{TCP_PORT}")
        print(f"[INFO] Logging to: {LOG_FILE.resolve()}")

        while True:
            conn, addr = s.accept()
            threading.Thread(target=handle_client, args=(conn, addr), daemon=True).start()

# -------------------------------
# UDP DISCOVERY
# -------------------------------
def udp_discovery():
    global ALLOWED_IP

    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.bind((HOST, DISCOVERY_PORT))
        print(f"[INFO] UDP discovery on {HOST}:{DISCOVERY_PORT}")

        while True:
            data, addr = s.recvfrom(1024)
            client_ip, client_port = addr
            txt = data.decode("utf-8", errors="ignore").strip()

            # Expect: DISCOVER <secret_hash>
            if not txt.startswith("DISCOVER "):
                continue

            their_hash = txt.split(" ", 1)[1]

            # If not yet paired, enforce time window
            if ALLOWED_IP is None:
                elapsed = time.time() - PAIRING_START_TIME
                if elapsed > PAIRING_WINDOW_SECONDS:
                    print(f"[SECURITY] Pairing window expired. Ignoring discovery from {addr}.")
                    continue

            if their_hash != SECRET_HASH:
                print(f"[SECURITY] Bad discovery secret hash from {addr}")
                continue

            # First valid client locks the IP
            if ALLOWED_IP is None:
                ALLOWED_IP = client_ip
                print(f"[PAIRING] First valid client, locked IP to {ALLOWED_IP}")
            elif client_ip != ALLOWED_IP:
                print(f"[SECURITY] Valid hash but wrong IP {client_ip} (allowed: {ALLOWED_IP})")
                continue

            reply = f"BRIDGE_OK {TCP_PORT}"
            s.sendto(reply.encode("utf-8"), addr)

# -------------------------------
# MAIN
# -------------------------------
if __name__ == "__main__":
    try:
        init_secret_from_argv()
        threading.Thread(target=udp_discovery, daemon=True).start()
        tcp_server()
    except Exception as e:
        print(f"\n[FATAL] Unhandled exception in bridge_server.py: {e}")
        input("Press ENTER to close...")
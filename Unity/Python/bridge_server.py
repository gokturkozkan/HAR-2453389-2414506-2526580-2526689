import socket
import threading
import json
import random
import string
import time
import hmac
import hashlib
import sys
import os
import requests
from datetime import datetime
from pathlib import Path


#config part
HOST = "0.0.0.0"
TCP_PORT = 5005
DISCOVERY_PORT = 5006
LOG_FILE = Path("unity_commands.log")

PAIRING_WINDOW_SECONDS = 120  #pairin window

SALT = b"unity-bridge-salt-01"
SECRET_HASH = None
PAIRING_START_TIME = time.time()
ALLOWED_IP = None

# HAR Backend URL - hardcoded for demo
HAR_BACKEND_URL = "http://192.168.0.100:5000"

#hashing and init
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

    print("\n" + "="*50)
    print(" UNITY BRIDGE STARTED ")
    print("="*50)
    print(f"\nPairing code: {pairing_code}")
    print(f"Pairing window: {PAIRING_WINDOW_SECONDS} seconds")
    print(f"HAR Backend: {HAR_BACKEND_URL}")
    print("="*50 + "\n")

#data log part
def log_message(message_dict):
    """
    Instead of appending lines, always overwrite unity_commands.log
    with ONLY the latest JSON object. So the file always contains
    a single JSON object.
    """
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)

    if "timestamp" not in message_dict:
        message_dict["timestamp"] = datetime.utcnow().isoformat() + "Z"

    # Atomic write to avoid Unity reading a partially-written file and to
    # minimize time spent holding the file handle (helps with OneDrive locks).
    tmp_path = LOG_FILE.with_suffix(LOG_FILE.suffix + ".tmp")
    with tmp_path.open("w", encoding="utf-8") as f:
        json.dump(message_dict, f, ensure_ascii=False)
        f.flush()
        os.fsync(f.fileno())

    os.replace(tmp_path, LOG_FILE)

#tcp handling
def handle_client(conn, addr):
    global ALLOWED_IP
    client_ip, client_port = addr

    # ip restriction
    if ALLOWED_IP is not None and client_ip != ALLOWED_IP:
        print(f"TCP from disallowed IP {client_ip} exit.")
        conn.close()
        return

    print(f"New connection from {addr}")

    with conn:
        buffer = ""
        while True:
            data = conn.recv(1024)
            if not data:
                print(f"Connection closed by {addr}")
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
                    print(f"Invalid JSON {addr}: {line}")
                    continue

                if msg.get("secret") != SECRET_HASH:
                    print(f"Invalid tkn.")
                    continue

                if ALLOWED_IP is None:
                    ALLOWED_IP = client_ip
                    print(f"Client IP locked to {ALLOWED_IP}")

                print(f"running fine {addr}: {msg}")
                log_message(msg)
                
                # Also update HAR backend if URL is configured
                label = msg.get("label")
                if HAR_BACKEND_URL and label:
                    try:
                        requests.post(
                            f"{HAR_BACKEND_URL}/label",
                            json={"label": label},
                            timeout=2.0
                        )
                        print(f"[bridge_server] Label '{label}' sent to HAR backend")
                    except Exception as be:
                        print(f"[bridge_server] Failed to update HAR backend: {be}")

def tcp_server():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind((HOST, TCP_PORT))
        s.listen()
        print(f"Server listening on {HOST}:{TCP_PORT}")
        print(f" Logging: {LOG_FILE.resolve()}")

        while True:
            conn, addr = s.accept()
            threading.Thread(target=handle_client, args=(conn, addr), daemon=True).start()

def udp_discovery():
    global ALLOWED_IP

    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.bind((HOST, DISCOVERY_PORT))
        print(f"UDP discovery opened (I hope this is not going to create critical vulnerability for project) {HOST}:{DISCOVERY_PORT}")

        while True:
            data, addr = s.recvfrom(1024)
            client_ip, client_port = addr
            txt = data.decode("utf-8", errors="ignore").strip()

            if not txt.startswith("DISCOVER "):
                continue

            their_hash = txt.split(" ", 1)[1]

            if ALLOWED_IP is None:
                elapsed = time.time() - PAIRING_START_TIME
                if elapsed > PAIRING_WINDOW_SECONDS:
                    print(f"Pairing window expired.")
                    continue

            if their_hash != SECRET_HASH:
                print(f"Wrong discovery tkn hash")
                continue

            if ALLOWED_IP is None:
                ALLOWED_IP = client_ip
                print(f"Valid client, locked IP to {ALLOWED_IP}")
            elif client_ip != ALLOWED_IP:
                print(f"Valid hash but wrong IP {client_ip}")
                continue

            reply = f"BRIDGE_OK {TCP_PORT}"
            s.sendto(reply.encode("utf-8"), addr)

if __name__ == "__main__":
    try:
        init_secret_from_argv()
        threading.Thread(target=udp_discovery, daemon=True).start()
        tcp_server()
    except Exception as e:
        print(f"\nUnhandled exception in bridge_server.py: {e}")
        input("Press ENTER to close...")
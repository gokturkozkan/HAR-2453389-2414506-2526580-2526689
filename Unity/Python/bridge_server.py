import hashlib
import hmac
import json
import socket
import sys
import threading
import time
from datetime import datetime
from pathlib import Path


HOST = "0.0.0.0"
TCP_PORT = 5005
DISCOVERY_PORT = 5006
LOG_FILE = Path("unity_commands.log")
PAIRING_WINDOW_SECONDS = 120

SALT = b"unity-bridge-salt-01"
SECRET_HASH = None
PAIRING_START_TIME = time.time()
ALLOWED_IP = None


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

    print("HARVR UNITY BRIDGE STARTED")
    print("PAIRING MODE")
    print(f"Pairing code: {pairing_code}")
    print(f"Pairing window: {PAIRING_WINDOW_SECONDS} seconds")


def log_message(message_dict):
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)

    if "timestamp" not in message_dict:
        message_dict["timestamp"] = datetime.utcnow().isoformat() + "Z"

    with LOG_FILE.open("w", encoding="utf-8") as log_file:
        json.dump(message_dict, log_file, ensure_ascii=False)


def handle_client(conn, addr):
    global ALLOWED_IP

    client_ip, _ = addr

    if ALLOWED_IP is not None and client_ip != ALLOWED_IP:
        print(f"TCP from disallowed IP {client_ip}; closing.")
        conn.close()
        return

    print(f"New TCP connection from {addr}")

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
                    message = json.loads(line)
                except Exception:
                    print(f"Invalid JSON from {addr}: {line}")
                    continue

                if message.get("secret") != SECRET_HASH:
                    print("Invalid bridge secret.")
                    continue

                if ALLOWED_IP is None:
                    ALLOWED_IP = client_ip
                    print(f"Client IP locked to {ALLOWED_IP}")

                print(f"Activity received: {message}")
                log_message(message)


def tcp_server():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server_socket:
        server_socket.bind((HOST, TCP_PORT))
        server_socket.listen()
        print(f"TCP server listening on {HOST}:{TCP_PORT}")
        print(f"Logging latest activity to: {LOG_FILE.resolve()}")

        while True:
            conn, addr = server_socket.accept()
            thread = threading.Thread(target=handle_client, args=(conn, addr), daemon=True)
            thread.start()


def udp_discovery():
    global ALLOWED_IP

    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as discovery_socket:
        discovery_socket.bind((HOST, DISCOVERY_PORT))
        print(f"UDP discovery listening on {HOST}:{DISCOVERY_PORT}")

        while True:
            data, addr = discovery_socket.recvfrom(1024)
            client_ip, _ = addr
            text = data.decode("utf-8", errors="ignore").strip()

            if not text.startswith("DISCOVER "):
                continue

            their_hash = text.split(" ", 1)[1]

            if ALLOWED_IP is None:
                elapsed = time.time() - PAIRING_START_TIME
                if elapsed > PAIRING_WINDOW_SECONDS:
                    print("Pairing window expired.")
                    continue

            if their_hash != SECRET_HASH:
                print("Wrong discovery hash.")
                continue

            if ALLOWED_IP is None:
                ALLOWED_IP = client_ip
                print(f"Valid client; locked IP to {ALLOWED_IP}")
            elif client_ip != ALLOWED_IP:
                print(f"Valid hash from wrong IP {client_ip}; ignoring.")
                continue

            reply = f"BRIDGE_OK {TCP_PORT}"
            discovery_socket.sendto(reply.encode("utf-8"), addr)


if __name__ == "__main__":
    try:
        init_secret_from_argv()
        threading.Thread(target=udp_discovery, daemon=True).start()
        tcp_server()
    except Exception as error:
        print(f"Unhandled bridge exception: {error}")
        input("Press ENTER to close...")

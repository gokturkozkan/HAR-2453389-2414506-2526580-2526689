import socket
import threading
import json
from datetime import datetime
from pathlib import Path

HOST = "0.0.0.0"
TCP_PORT = 5005
DISCOVERY_PORT = 5006
LOG_FILE = Path("unity_commands.log")

ALLOWED_IP = None
LOCK_FIRST_CLIENT_IP = True


def log_message(message_dict):
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)

    if "timestamp" not in message_dict:
        message_dict["timestamp"] = datetime.utcnow().isoformat() + "Z"

    with LOG_FILE.open("w", encoding="utf-8") as f:
        json.dump(message_dict, f, ensure_ascii=False)


def handle_client(conn, addr):
    global ALLOWED_IP

    client_ip, client_port = addr

    if LOCK_FIRST_CLIENT_IP and ALLOWED_IP is not None and client_ip != ALLOWED_IP:
        print(f"TCP connection rejected from disallowed IP: {client_ip}")
        conn.close()
        return

    print(f"New TCP connection from {addr}")

    with conn:
        buffer = ""

        while True:
            try:
                data = conn.recv(1024)
            except Exception as e:
                print(f"Receive error from {addr}: {e}")
                break

            if not data:
                print(f"Connection closed by {addr}")
                break

            buffer += data.decode("utf-8", errors="ignore")

            while "\n" in buffer:
                line, buffer = buffer.split("\n", 1)
                line = line.strip()

                if not line:
                    continue

                try:
                    msg = json.loads(line)
                except Exception:
                    print(f"Invalid JSON from {addr}: {line}")
                    continue

                if "label" not in msg:
                    print(f"JSON missing 'label' from {addr}: {msg}")
                    continue

                if LOCK_FIRST_CLIENT_IP and ALLOWED_IP is None:
                    ALLOWED_IP = client_ip
                    print(f"Client IP locked to {ALLOWED_IP}")

                print(f"Received command from {addr}: {msg}")
                log_message(msg)


def tcp_server():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind((HOST, TCP_PORT))
        s.listen()

        print(f"TCP server listening on {HOST}:{TCP_PORT}")
        print(f"Logging latest command to: {LOG_FILE.resolve()}")

        while True:
            conn, addr = s.accept()
            threading.Thread(target=handle_client, args=(conn, addr), daemon=True).start()


def udp_discovery():
    global ALLOWED_IP

    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.bind((HOST, DISCOVERY_PORT))
        print(f"UDP discovery listening on {HOST}:{DISCOVERY_PORT}")

        while True:
            data, addr = s.recvfrom(1024)
            client_ip, client_port = addr
            txt = data.decode("utf-8", errors="ignore").strip()

            if txt != "UNITY_BRIDGE_DISCOVERY":
                continue

            if LOCK_FIRST_CLIENT_IP and ALLOWED_IP is not None and client_ip != ALLOWED_IP:
                print(f"Discovery ignored from disallowed IP: {client_ip}")
                continue

            if LOCK_FIRST_CLIENT_IP and ALLOWED_IP is None:
                ALLOWED_IP = client_ip
                print(f"Discovery accepted, locked client IP to {ALLOWED_IP}")

            reply = f"BRIDGE_OK {TCP_PORT}"
            s.sendto(reply.encode("utf-8"), addr)
            print(f"Discovery reply sent to {addr}")


if __name__ == "__main__":
    try:
        print("UNITY BRIDGE STARTED")
        print("Pairing is disabled.")
        print(f"TCP Port: {TCP_PORT}")
        print(f"UDP Discovery Port: {DISCOVERY_PORT}")

        threading.Thread(target=udp_discovery, daemon=True).start()
        tcp_server()

    except Exception as e:
        print(f"\nUnhandled exception in bridge_server.py: {e}")
        input("Press ENTER to close...")

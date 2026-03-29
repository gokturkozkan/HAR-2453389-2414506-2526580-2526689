import socket
import json
from datetime import datetime
import hmac
import hashlib
import random
import string

from network_config import (
    UNITY_BRIDGE_DISCOVERY_ADDR,
    UNITY_BRIDGE_DISCOVERY_PORT,
    UNITY_BRIDGE_FALLBACK_HOST,
    UNITY_BRIDGE_TCP_PORT,
)

DISCOVERY_PORT = UNITY_BRIDGE_DISCOVERY_PORT
DISCOVERY_TIMEOUT = 3.0  # seconds

# Must match SALT in bridge_server.py
SALT = b"unity-bridge-salt-01"

def generate_pairing_code(length=6) -> str:
    return ''.join(random.choices(string.ascii_uppercase + string.digits, k=length))

def compute_secret_hash(code: str) -> str:
    return hmac.new(SALT, code.encode("utf-8"), hashlib.sha256).hexdigest()

def discover_bridge(secret_hash: str):
    message = f"DISCOVER {secret_hash}".encode("utf-8")

    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        s.settimeout(DISCOVERY_TIMEOUT)

        print("Searching for Unity bridge...")
        s.sendto(message, (UNITY_BRIDGE_DISCOVERY_ADDR, DISCOVERY_PORT))

        while True:
            try:
                data, addr = s.recvfrom(1024)
            except socket.timeout:
                raise TimeoutError("No Unity bridge found.")

            reply = data.decode("utf-8", errors="ignore").strip()
            print(f"Reply from {addr}: {reply}")

            if reply.startswith("BRIDGE_OK "):
                port_str = reply.split(" ", 1)[1]
                port = int(port_str)
                ip = addr[0]
                print(f"Bridge located at {ip}:{port}")
                return ip, port


def fallback_bridge():
    if not UNITY_BRIDGE_FALLBACK_HOST.strip():
        raise TimeoutError(
            "No Unity bridge found by broadcast and no UNITY_BRIDGE_FALLBACK_HOST is configured."
        )
    try:
        ip = socket.gethostbyname(UNITY_BRIDGE_FALLBACK_HOST)
        print(f"Falling back to {UNITY_BRIDGE_FALLBACK_HOST}:{UNITY_BRIDGE_TCP_PORT} -> {ip}:{UNITY_BRIDGE_TCP_PORT}")
        return ip, UNITY_BRIDGE_TCP_PORT
    except OSError as exc:
        raise TimeoutError(
            f"No Unity bridge found by broadcast and hostname fallback failed for {UNITY_BRIDGE_FALLBACK_HOST}: {exc}"
        ) from exc

class UnityRemoteClient:
    def __init__(self):
        # Generate pairing code on remote side
        self.pairing_code = generate_pairing_code()
        self.secret_hash = compute_secret_hash(self.pairing_code)
        self.sock = None
        self.host = None
        self.port = None

    def show_pairing_code(self):
        print("\n")
        print("  REMOTE CONTROLLER STARTED ")
        print("")
        print("PAIRING CODE:")
        print(f"    {self.pairing_code}")
        print("")
        print("1) Start/Play the Unity application.")
        print("2) Enter this code in Unity's 'pairingCode' field.")
        print("3) Press ENTER here to connect.\n")
        input("Press ENTER once Unity is ready with this code...")

    def connect(self):
        try:
            self.host, self.port = discover_bridge(self.secret_hash)
        except TimeoutError:
            self.host, self.port = fallback_bridge()
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        print(f"Connecting to {self.host}:{self.port}...")
        self.sock.connect((self.host, self.port))
        print("Connected.")

    def close(self):
        if self.sock:
            try:
                self.sock.close()
            except:
                pass
            print("Disconnected.")

    def send_label(self, label: str):
        msg = {
            "label": label,
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "source": "remote-python",
            "secret": self.secret_hash
        }
        line = json.dumps(msg, ensure_ascii=False) + "\n"
        self.sock.sendall(line.encode("utf-8"))
        print(f"sent message: {msg}")

def interactive_cli():
    client = UnityRemoteClient()
    client.show_pairing_code()

    try:
        client.connect()

        print("\nType label")
        print("Type 'quit' to exit.\n")

        while True:
            cmd = input("label> ").strip()
            if not cmd:
                continue
            if cmd.lower() in ("quit", "exit"):
                break
            client.send_label(cmd)

    except Exception as e:
        print(f" {e}")
    finally:
        client.close()

if __name__ == "__main__":
    interactive_cli()

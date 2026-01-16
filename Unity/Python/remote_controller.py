import socket
import json
from datetime import datetime
import hmac
import hashlib
import random
import string
import time

DISCOVERY_PORT = 5006
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
        s.sendto(message, ("255.255.255.255", DISCOVERY_PORT))

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
        print("2) Enter this code in Unity's 'pairingCode' field and press Connect.")
        print("3) Waiting for bridge to start...\n")

    def connect(self, retry_interval=2.0, max_retries=60):
        """Auto-connect with retries until bridge is available"""
        retries = 0
        while retries < max_retries:
            try:
                self.host, self.port = discover_bridge(self.secret_hash)
                self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                print(f"Connecting to {self.host}:{self.port}...")
                self.sock.connect((self.host, self.port))
                print("Connected.")
                return True
            except (TimeoutError, ConnectionRefusedError, OSError) as e:
                retries += 1
                if retries < max_retries:
                    print(f"Bridge not ready, retrying... ({retries}/{max_retries})")
                    time.sleep(retry_interval)
                else:
                    raise Exception(f"Failed to connect after {max_retries} attempts")
        return False

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

import socket
import json
from datetime import datetime
import hmac
import hashlib
import random
import string

DISCOVERY_PORT = 5006
DISCOVERY_TIMEOUT = 3.0  # seconds

# Must match SALT in bridge_server.py
SALT = b"unity-bridge-salt-01"

def generate_pairing_code(length=6) -> str:
    return ''.join(random.choices(string.ascii_uppercase + string.digits, k=length))

def compute_secret_hash(code: str) -> str:
    return hmac.new(SALT, code.encode("utf-8"), hashlib.sha256).hexdigest()

def discover_bridge(secret_hash: str):
    """
    Broadcasts: DISCOVER <secret_hash>
    Expects: BRIDGE_OK <port>
    Returns: (ip, port)
    """
    message = f"DISCOVER {secret_hash}".encode("utf-8")

    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        s.settimeout(DISCOVERY_TIMEOUT)

        print("[DISCOVERY] Searching for Unity bridge...")
        s.sendto(message, ("255.255.255.255", DISCOVERY_PORT))

        while True:
            try:
                data, addr = s.recvfrom(1024)
            except socket.timeout:
                raise TimeoutError("No Unity bridge found (timeout or pairing window expired).")

            reply = data.decode("utf-8", errors="ignore").strip()
            print(f"[DISCOVERY] Reply from {addr}: {reply}")

            if reply.startswith("BRIDGE_OK "):
                port_str = reply.split(" ", 1)[1]
                port = int(port_str)
                ip = addr[0]
                print(f"[DISCOVERY] Bridge located at {ip}:{port}")
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
        print("\n============================")
        print("  REMOTE CONTROLLER STARTED ")
        print("============================")
        print("PAIRING CODE (tell Unity side):")
        print(f"    {self.pairing_code}")
        print("============================")
        print("1) Enter this code in Unity's 'pairingCode' field.")
        print("2) Start/Play the Unity application.")
        print("3) Press ENTER here to connect.\n")
        input("Press ENTER once Unity is ready with this code...")

    def connect(self):
        self.host, self.port = discover_bridge(self.secret_hash)
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        print(f"[INFO] Connecting to {self.host}:{self.port}...")
        self.sock.connect((self.host, self.port))
        print("[INFO] Connected.")

    def close(self):
        if self.sock:
            try:
                self.sock.close()
            except:
                pass
            print("[INFO] Disconnected.")

    def send_label(self, label: str):
        msg = {
            "label": label,
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "source": "remote-python",
            "secret": self.secret_hash
        }
        line = json.dumps(msg, ensure_ascii=False) + "\n"
        self.sock.sendall(line.encode("utf-8"))
        print(f"[SENT] {msg}")

def interactive_cli():
    client = UnityRemoteClient()
    client.show_pairing_code()

    try:
        client.connect()

        print("\nType label commands (e.g. 'startRecording')")
        print("Type 'quit' to exit.\n")

        while True:
            cmd = input("cmd> ").strip()
            if not cmd:
                continue
            if cmd.lower() in ("quit", "exit"):
                break
            client.send_label(cmd)

    except Exception as e:
        print(f"[ERROR] {e}")
    finally:
        client.close()

if __name__ == "__main__":
    interactive_cli()

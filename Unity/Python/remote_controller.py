import hashlib
import hmac
import json
import random
import socket
import string
from datetime import datetime


DISCOVERY_PORT = 5006
DISCOVERY_TIMEOUT = 3.0
SALT = b"unity-bridge-salt-01"


def generate_pairing_code(length=6) -> str:
    return "".join(random.choices(string.ascii_uppercase + string.digits, k=length))


def compute_secret_hash(code: str) -> str:
    return hmac.new(SALT, code.encode("utf-8"), hashlib.sha256).hexdigest()


def discover_bridge(secret_hash: str):
    message = f"DISCOVER {secret_hash}".encode("utf-8")

    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        sock.settimeout(DISCOVERY_TIMEOUT)

        print("Searching for Unity bridge...")
        sock.sendto(message, ("255.255.255.255", DISCOVERY_PORT))

        while True:
            data, addr = sock.recvfrom(1024)
            reply = data.decode("utf-8", errors="ignore").strip()
            print(f"Reply from {addr}: {reply}")

            if reply.startswith("BRIDGE_OK "):
                port = int(reply.split(" ", 1)[1])
                return addr[0], port


class UnityRemoteClient:
    def __init__(self, pairing_code=None):
        self.pairing_code = (pairing_code or generate_pairing_code()).strip()
        self.secret_hash = compute_secret_hash(self.pairing_code)
        self.sock = None
        self.host = None
        self.port = None

    def show_pairing_code(self):
        print("")
        print("HARVR REMOTE CONTROLLER")
        print("")
        print("PAIRING CODE:")
        print(f"    {self.pairing_code}")
        print("")
        print("1) Start Play Mode in Unity.")
        print("2) Start the bridge with the same pairing code.")
        print("3) Press ENTER here to connect.")
        input("Press ENTER once Unity is ready...")

    def connect(self):
        self.host, self.port = discover_bridge(self.secret_hash)
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        print(f"Connecting to {self.host}:{self.port}...")
        self.sock.connect((self.host, self.port))
        print("Connected.")

    def close(self):
        if self.sock:
            self.sock.close()
            self.sock = None
            print("Disconnected.")

    def send_label(self, label: str):
        message = {
            "label": label,
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "source": "remote-python",
            "secret": self.secret_hash,
        }
        line = json.dumps(message, ensure_ascii=False) + "\n"
        self.sock.sendall(line.encode("utf-8"))
        print(f"sent: {message}")


def interactive_cli():
    pairing_code = input("Pairing code (blank to generate): ").strip() or None
    client = UnityRemoteClient(pairing_code)
    client.show_pairing_code()

    try:
        client.connect()

        print("")
        print("Type labels: walking, crouching, punching, idle")
        print("Type quit to exit.")
        print("")

        while True:
            command = input("label> ").strip()
            if not command:
                continue
            if command.lower() in ("quit", "exit"):
                break
            client.send_label(command)
    except Exception as error:
        print(error)
    finally:
        client.close()


if __name__ == "__main__":
    interactive_cli()

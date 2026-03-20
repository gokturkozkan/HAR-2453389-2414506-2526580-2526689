import socket
import json
from datetime import datetime

DISCOVERY_PORT = 5006
TCP_PORT = 5005
DISCOVERY_TIMEOUT = 3.0


def discover_bridge(timeout=DISCOVERY_TIMEOUT):
    message = b"UNITY_BRIDGE_DISCOVERY"

    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        s.settimeout(timeout)

        print("Searching for bridge server...")
        s.sendto(message, ("255.255.255.255", DISCOVERY_PORT))

        while True:
            try:
                data, addr = s.recvfrom(1024)
            except socket.timeout:
                raise TimeoutError("No bridge server found on the local network.")

            reply = data.decode("utf-8", errors="ignore").strip()
            print(f"Reply from {addr}: {reply}")

            if reply.startswith("BRIDGE_OK"):
                parts = reply.split()
                port = int(parts[1]) if len(parts) > 1 else TCP_PORT
                ip = addr[0]
                print(f"Bridge server located at {ip}:{port}")
                return ip, port


class UnityRemoteClient:
    def __init__(self, timeout=DISCOVERY_TIMEOUT):
        self.timeout = timeout
        self.sock = None
        self.host = None
        self.port = None

    def connect(self):
        self.host, self.port = discover_bridge(timeout=self.timeout)

        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.settimeout(self.timeout)

        print(f"Connecting to bridge server at {self.host}:{self.port}...")
        self.sock.connect((self.host, self.port))
        print("Connected.")

    def is_connected(self):
        return self.sock is not None

    def close(self):
        if self.sock is not None:
            try:
                self.sock.close()
            except Exception:
                pass

        self.sock = None
        self.host = None
        self.port = None
        print("Disconnected.")

    def send_label(self, label: str, source: str = "remote-python"):
        if self.sock is None:
            raise RuntimeError("Not connected to bridge server.")

        msg = {
            "label": label,
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "source": source
        }

        line = json.dumps(msg, ensure_ascii=False) + "\n"
        self.sock.sendall(line.encode("utf-8"))
        print(f"Sent message: {msg}")


def interactive_cli():
    client = UnityRemoteClient()

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
        print(f"Error: {e}")
    finally:
        client.close()


if __name__ == "__main__":
    interactive_cli()

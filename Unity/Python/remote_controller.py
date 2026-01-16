import argparse
import json
import socket
import threading
import time
import hmac
import hashlib
import random
import string
from datetime import datetime
from typing import Any, Dict, Optional, Tuple


DISCOVERY_PORT = 5006
DISCOVERY_TIMEOUT = 3.0  # seconds

# GUI (on another PC) connects to this control port on the remote controller machine.
CONTROL_HOST = "0.0.0.0"
CONTROL_PORT = 5010

# Must match SALT in bridge_server.py
SALT = b"unity-bridge-salt-01"


def generate_pairing_code(length: int = 6) -> str:
    return "".join(random.choices(string.ascii_uppercase + string.digits, k=length))


def compute_secret_hash(code: str) -> str:
    return hmac.new(SALT, code.encode("utf-8"), hashlib.sha256).hexdigest()


def discover_bridge(secret_hash: str) -> Tuple[str, int]:
    message = f"DISCOVER {secret_hash}".encode("utf-8")

    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as udp:
        udp.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        udp.settimeout(DISCOVERY_TIMEOUT)

        udp.sendto(message, ("255.255.255.255", DISCOVERY_PORT))

        while True:
            try:
                data, addr = udp.recvfrom(1024)
            except socket.timeout:
                raise TimeoutError("No Unity bridge found.")

            reply = data.decode("utf-8", errors="ignore").strip()
            if reply.startswith("BRIDGE_OK "):
                port_str = reply.split(" ", 1)[1]
                return addr[0], int(port_str)


class RemoteController:
    def __init__(
        self,
        pairing_code: str,
        retry_interval: float = 2.0,
        max_retries: int = 0,
    ):
        self.pairing_code = pairing_code
        self.secret_hash = compute_secret_hash(pairing_code)

        self._retry_interval = retry_interval
        self._max_retries = max_retries

        self._lock = threading.Lock()
        self._bridge_sock: Optional[socket.socket] = None
        self._bridge_host: Optional[str] = None
        self._bridge_port: Optional[int] = None
        self._bridge_connected = False
        self._last_error: Optional[str] = None
        self._started_at = time.time()

        self._stop_event = threading.Event()

    def start(self) -> None:
        threading.Thread(target=self._bridge_connect_loop, daemon=True).start()

    def stop(self) -> None:
        self._stop_event.set()
        with self._lock:
            if self._bridge_sock is not None:
                try:
                    self._bridge_sock.close()
                except OSError:
                    pass
                self._bridge_sock = None
                self._bridge_connected = False

    def _set_bridge_disconnected(self, err: Optional[str] = None) -> None:
        if err:
            self._last_error = err
        if self._bridge_sock is not None:
            try:
                self._bridge_sock.close()
            except OSError:
                pass
        self._bridge_sock = None
        self._bridge_connected = False
        self._bridge_host = None
        self._bridge_port = None

    def _bridge_connect_loop(self) -> None:
        retries = 0
        while not self._stop_event.is_set():
            if self._max_retries and retries >= self._max_retries:
                return

            with self._lock:
                already_connected = self._bridge_connected and self._bridge_sock is not None

            if already_connected:
                time.sleep(0.5)
                continue

            try:
                host, port = discover_bridge(self.secret_hash)
                tcp = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                tcp.settimeout(10)
                tcp.connect((host, port))
                tcp.settimeout(None)

                with self._lock:
                    self._bridge_sock = tcp
                    self._bridge_host = host
                    self._bridge_port = port
                    self._bridge_connected = True
                    self._last_error = None

                print(f"[remote_controller] Connected to Unity bridge at {host}:{port}")
                continue

            except Exception as e:
                retries += 1
                with self._lock:
                    self._set_bridge_disconnected(str(e))
                time.sleep(self._retry_interval)

    def send_label(self, label: str, source: str = "gui") -> Tuple[bool, str]:
        payload = {
            "label": label,
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "source": source,
            "secret": self.secret_hash,
        }
        line = json.dumps(payload, ensure_ascii=False) + "\n"

        with self._lock:
            if not self._bridge_connected or self._bridge_sock is None:
                return False, "Not connected to Unity bridge"
            sock = self._bridge_sock

        try:
            sock.sendall(line.encode("utf-8"))
            return True, "ok"
        except Exception as e:
            with self._lock:
                self._set_bridge_disconnected(f"send failed: {e}")
            return False, f"send failed: {e}"

    def get_state(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "pairing_code": self.pairing_code,
                "bridge_connected": self._bridge_connected,
                "bridge_host": self._bridge_host,
                "bridge_port": self._bridge_port,
                "last_error": self._last_error,
                "uptime_seconds": round(time.time() - self._started_at, 1),
            }


def _send_json_line(writer, obj: Dict[str, Any]) -> None:
    writer.write(json.dumps(obj, ensure_ascii=False) + "\n")
    writer.flush()


def _handle_control_client(conn: socket.socket, addr, controller: RemoteController) -> None:
    peer = f"{addr[0]}:{addr[1]}"
    try:
        with conn:
            conn.settimeout(30)
            reader = conn.makefile("r", encoding="utf-8", newline="\n")
            writer = conn.makefile("w", encoding="utf-8", newline="\n")

            for raw in reader:
                line = raw.strip()
                if not line:
                    continue

                try:
                    req = json.loads(line)
                except Exception:
                    _send_json_line(writer, {"ok": False, "error": "invalid_json"})
                    continue

                cmd = req.get("cmd")
                request_id = req.get("id")

                if cmd == "get_state":
                    resp = {"ok": True, "id": request_id, "state": controller.get_state()}
                    _send_json_line(writer, resp)
                elif cmd == "send_label":
                    label = (req.get("label") or "").strip()
                    if not label:
                        _send_json_line(writer, {"ok": False, "id": request_id, "error": "missing_label"})
                        continue
                    ok, msg = controller.send_label(label)
                    _send_json_line(writer, {"ok": ok, "id": request_id, "message": msg})
                elif cmd == "ping":
                    _send_json_line(writer, {"ok": True, "id": request_id, "message": "pong"})
                else:
                    _send_json_line(writer, {"ok": False, "id": request_id, "error": "unknown_cmd"})

    except Exception as e:
        print(f"[remote_controller] control client {peer} disconnected: {e}")


def run_control_server(controller: RemoteController, host: str, port: int) -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server:
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server.bind((host, port))
        server.listen(10)
        print(f"[remote_controller] Control server listening on {host}:{port}")

        while True:
            conn, addr = server.accept()
            threading.Thread(
                target=_handle_control_client,
                args=(conn, addr, controller),
                daemon=True,
            ).start()


def main() -> None:
    parser = argparse.ArgumentParser(description="HAR remote controller (GUI talks to this over TCP).")
    parser.add_argument("--pairing-code", default=None, help="Pairing code shared with Unity/bridge_server.")
    parser.add_argument("--control-host", default=CONTROL_HOST)
    parser.add_argument("--control-port", type=int, default=CONTROL_PORT)
    parser.add_argument("--retry-interval", type=float, default=2.0)
    args = parser.parse_args()

    pairing_code = (args.pairing_code or generate_pairing_code()).strip()
    controller = RemoteController(pairing_code=pairing_code, retry_interval=args.retry_interval)
    controller.start()

    print("\n  REMOTE CONTROLLER STARTED ")
    print("PAIRING CODE:")
    print(f"    {pairing_code}")
    print("\nStart the Unity bridge with the SAME code (bridge_server.py <PAIRING_CODE>).")
    print("Then connect your GUI to this machine and press label buttons.\n")

    run_control_server(controller, args.control_host, args.control_port)


if __name__ == "__main__":
    main()

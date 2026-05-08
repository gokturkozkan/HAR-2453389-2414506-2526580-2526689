"""Collect live Unity bridge evidence for the HAR Test Results report.

Start Unity/Python/bridge_server.py first, then run this script with the same
pairing code.

Example:
  python Unity/Python/bridge_server.py 123456
  python tools/har_bridge_evidence_runner.py --code 123456 --label walking
"""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import socket
import time
from datetime import datetime, timezone
from pathlib import Path


REPO = Path(__file__).resolve().parents[1]
DEFAULT_OUT = REPO / "Reports" / "evidence" / "har_bridge_evidence.json"
DEFAULT_LOG = REPO / "Unity" / "Python" / "unity_commands.log"
SALT = b"unity-bridge-salt-01"


def compute_secret_hash(code: str) -> str:
    return hmac.new(SALT, code.encode("utf-8"), hashlib.sha256).hexdigest()


def udp_discover(host: str, port: int, secret_hash: str, timeout: float) -> dict:
    started = time.perf_counter()
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.settimeout(timeout)
        sock.sendto(f"DISCOVER {secret_hash}".encode("utf-8"), (host, port))
        try:
            data, addr = sock.recvfrom(1024)
        except socket.timeout:
            return {"ok": False, "elapsed_ms": round((time.perf_counter() - started) * 1000, 3), "error": "timeout"}
    return {
        "ok": data.decode("utf-8", errors="replace").startswith("BRIDGE_OK"),
        "elapsed_ms": round((time.perf_counter() - started) * 1000, 3),
        "reply": data.decode("utf-8", errors="replace"),
        "addr": addr[0],
    }


def tcp_send(host: str, port: int, payload: dict, timeout: float) -> dict:
    started = time.perf_counter()
    try:
        with socket.create_connection((host, port), timeout=timeout) as sock:
            sock.sendall((json.dumps(payload) + "\n").encode("utf-8"))
    except Exception as exc:
        return {"ok": False, "elapsed_ms": round((time.perf_counter() - started) * 1000, 3), "error": repr(exc)}
    return {"ok": True, "elapsed_ms": round((time.perf_counter() - started) * 1000, 3)}


def read_latest_log(log_path: Path) -> dict:
    if not log_path.exists():
        return {"ok": False, "error": f"{log_path} does not exist"}
    try:
        return {"ok": True, "data": json.loads(log_path.read_text(encoding="utf-8"))}
    except Exception as exc:
        return {"ok": False, "error": repr(exc)}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--code", required=True)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--discovery-port", type=int, default=5006)
    parser.add_argument("--tcp-port", type=int, default=5005)
    parser.add_argument("--label", default="walking")
    parser.add_argument("--node-id", type=int, default=1)
    parser.add_argument("--timeout", type=float, default=5.0)
    parser.add_argument("--log", default=str(DEFAULT_LOG))
    parser.add_argument("--out", default=str(DEFAULT_OUT))
    args = parser.parse_args()

    secret_hash = compute_secret_hash(args.code)
    discovery = udp_discover(args.host, args.discovery_port, secret_hash, args.timeout)
    command = {
        "secret": secret_hash,
        "label": args.label,
        "node_id": args.node_id,
        "source": "har_bridge_evidence_runner",
    }
    sent = tcp_send(args.host, args.tcp_port, command, args.timeout)
    time.sleep(0.25)
    latest_log = read_latest_log(Path(args.log))
    log_matches = bool(
        latest_log.get("ok")
        and latest_log.get("data", {}).get("label") == args.label
        and latest_log.get("data", {}).get("node_id") == args.node_id
    )

    evidence = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "host": args.host,
        "discovery": discovery,
        "tcp_send": sent,
        "latest_log": latest_log,
        "overall_passed": bool(discovery.get("ok") and sent.get("ok") and log_matches),
    }

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(evidence, indent=2), encoding="utf-8")
    print(f"Wrote {out}")
    print(f"Overall passed: {evidence['overall_passed']}")


if __name__ == "__main__":
    main()

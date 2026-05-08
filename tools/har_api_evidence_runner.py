"""Collect live API evidence for the HAR Test Results report.

Run this while the Flask backend is already running.

Examples:
  python tools/har_api_evidence_runner.py --base-url http://localhost:3000
  python tools/har_api_evidence_runner.py --base-url http://192.168.1.20:3000 --real-predict --latency-runs 50

The script writes JSON evidence under Reports/evidence by default. It uses only
the Python standard library so it can run even before optional test packages are installed.
"""

from __future__ import annotations

import argparse
import json
import statistics
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4


REPO = Path(__file__).resolve().parents[1]
DEFAULT_OUT = REPO / "Reports" / "evidence" / "har_api_evidence.json"


def build_window(size: int = 32, offset: float = 0.0) -> list[dict[str, float]]:
    return [
        {
            "ax": 0.1 + offset + i * 0.01,
            "ay": 0.2 + offset + i * 0.01,
            "az": 9.7,
            "gx": 0.01 + offset,
            "gy": 0.02 + offset,
            "gz": 0.03 + offset,
        }
        for i in range(size)
    ]


def request_json(base_url: str, method: str, path: str, payload: object | None = None) -> dict:
    url = base_url.rstrip("/") + path
    data = None
    headers = {"Accept": "application/json"}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"

    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    started = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            elapsed_ms = (time.perf_counter() - started) * 1000
            try:
                body = json.loads(raw) if raw else None
            except json.JSONDecodeError:
                body = raw
            return {"status": resp.status, "elapsed_ms": elapsed_ms, "body": body}
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        elapsed_ms = (time.perf_counter() - started) * 1000
        try:
            body = json.loads(raw) if raw else None
        except json.JSONDecodeError:
            body = raw
        return {"status": exc.code, "elapsed_ms": elapsed_ms, "body": body}
    except Exception as exc:
        elapsed_ms = (time.perf_counter() - started) * 1000
        return {"status": None, "elapsed_ms": elapsed_ms, "error": repr(exc)}


def pass_if(result: dict, expected_status: int, body_check=None) -> bool:
    if result.get("status") != expected_status:
        return False
    if body_check is not None:
        try:
            return bool(body_check(result.get("body")))
        except Exception:
            return False
    return True


def summarize_latency(samples: list[float]) -> dict:
    if not samples:
        return {}
    ordered = sorted(samples)
    p95_index = max(0, min(len(ordered) - 1, int(round(len(ordered) * 0.95)) - 1))
    return {
        "count": len(samples),
        "min_ms": round(min(samples), 3),
        "median_ms": round(statistics.median(samples), 3),
        "p95_ms": round(ordered[p95_index], 3),
        "max_ms": round(max(samples), 3),
    }


def add_case(cases: list[dict], test_id: str, description: str, result: dict, passed: bool):
    cases.append(
        {
            "id": test_id,
            "description": description,
            "status": result.get("status"),
            "elapsed_ms": round(result.get("elapsed_ms", 0), 3),
            "passed": passed,
            "body": result.get("body"),
            "error": result.get("error"),
        }
    )


def run(args: argparse.Namespace) -> dict:
    cases: list[dict] = []
    base = args.base_url

    health = request_json(base, "GET", "/health")
    add_case(cases, "API-HEALTH", "Backend health endpoint responds", health, pass_if(health, 200))

    username = f"har-evidence-{uuid4().hex[:8]}@example.com"
    password = "StrongPass123"
    register = request_json(base, "POST", "/register", {"credentials": {"username": username, "password": password}})
    add_case(cases, "ST-01A", "Register new user", register, pass_if(register, 201, lambda b: "user" in b))
    user_id = (register.get("body") or {}).get("user", {}).get("id")

    login = request_json(base, "POST", "/login", {"credentials": {"username": username, "password": password}})
    add_case(cases, "ST-01B", "Login registered user", login, pass_if(login, 200, lambda b: b.get("user", {}).get("username") == username))

    if user_id:
        next_username = f"har-evidence-updated-{uuid4().hex[:8]}@example.com"
        update = request_json(
            base,
            "POST",
            "/user/update",
            {"userId": user_id, "credentials": {"username": next_username}},
        )
        add_case(cases, "ST-06", "Profile username update", update, pass_if(update, 200, lambda b: b.get("user", {}).get("username") == next_username))

    init_esp = request_json(base, "POST", "/esp-devices/init", {"count": 3})
    add_case(cases, "IT-04A", "Initialize ESP status records", init_esp, pass_if(init_esp, 200))
    set_esp = request_json(base, "POST", "/esp-status/2", {"isConnected": True})
    add_case(cases, "IT-04B", "Update ESP connection status", set_esp, pass_if(set_esp, 200))
    get_esp = request_json(base, "GET", "/esp-status?id=2")
    add_case(cases, "IT-04C", "Read ESP connection status", get_esp, pass_if(get_esp, 200, lambda b: b == {"id": 2, "isConnected": True}))

    bad_missing = build_window()
    bad_missing[0].pop("gz")
    missing = request_json(base, "POST", "/predict", {"node_id": 1, "readings": bad_missing})
    add_case(cases, "UT-02", "Reject missing sensor feature", missing, pass_if(missing, 400, lambda b: "missing 'gz'" in b.get("error", "")))

    wrong_length = request_json(base, "POST", "/predict", {"node_id": 1, "readings": build_window(31)})
    add_case(cases, "UT-03", "Reject wrong window length", wrong_length, pass_if(wrong_length, 400, lambda b: "Exactly 32" in b.get("error", "")))

    non_numeric = build_window()
    non_numeric[4]["ax"] = "not-a-number"
    invalid_type = request_json(base, "POST", "/predict", {"node_id": 1, "readings": non_numeric})
    add_case(cases, "MD-02", "Reject non-numeric sensor value", invalid_type, pass_if(invalid_type, 400, lambda b: "non-numeric" in b.get("error", "")))

    real_latency_samples: list[float] = []
    if args.real_predict:
        for i in range(args.latency_runs):
            result = request_json(base, "POST", "/predict", {"node_id": 1, "readings": build_window(offset=i * 0.001)})
            real_latency_samples.append(result["elapsed_ms"])
            if i == 0:
                add_case(cases, "IT-01A", "Real prediction request", result, pass_if(result, 200, lambda b: "activity" in b))

        label = request_json(base, "GET", "/label")
        add_case(cases, "IT-01B", "Read label after real prediction", label, pass_if(label, 200, lambda b: "label" in b))

        relabel = request_json(base, "POST", "/label", {"label": args.relabel, "node_id": 1})
        add_case(cases, "IT-03", "Submit corrected label", relabel, pass_if(relabel, 200, lambda b: b.get("label") == args.relabel))

        fused = request_json(
            base,
            "POST",
            "/predict",
            {
                "windows_by_node": {
                    "1": build_window(offset=0.0),
                    "2": build_window(offset=1.0),
                }
            },
        )
        add_case(cases, "IT-05", "Submit multi-node fused prediction", fused, pass_if(fused, 200, lambda b: b.get("fusion") == "average_per_timestep"))

    evidence = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "base_url": base,
        "real_predict_enabled": args.real_predict,
        "cases": cases,
        "latency_summary": summarize_latency(real_latency_samples),
        "overall_passed": all(case["passed"] for case in cases),
    }
    return evidence


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://localhost:3000")
    parser.add_argument("--out", default=str(DEFAULT_OUT))
    parser.add_argument("--real-predict", action="store_true", help="Also run tests that require the real model to be loaded.")
    parser.add_argument("--latency-runs", type=int, default=50)
    parser.add_argument("--relabel", default="walking")
    args = parser.parse_args()

    evidence = run(args)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(evidence, indent=2), encoding="utf-8")
    print(f"Wrote {out}")
    print(f"Overall passed: {evidence['overall_passed']}")
    for case in evidence["cases"]:
        result = "PASS" if case["passed"] else "FAIL"
        print(f"{result} {case['id']} {case['description']} ({case['status']}, {case['elapsed_ms']} ms)")


if __name__ == "__main__":
    main()

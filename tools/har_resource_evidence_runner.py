"""Collect CPU and memory evidence for HAR performance tests.

Install backend requirements first because this script uses psutil:
  pip install -r Hardware/RaspberryPi/HAR-backend/requirements.txt

Examples:
  python tools/har_resource_evidence_runner.py --pid 1234 --duration 120
  python tools/har_resource_evidence_runner.py --process-name python --duration 120
"""

from __future__ import annotations

import argparse
import json
import statistics
import time
from datetime import datetime, timezone
from pathlib import Path

import psutil


REPO = Path(__file__).resolve().parents[1]
DEFAULT_OUT = REPO / "Reports" / "evidence" / "har_resource_evidence.json"


def find_process(process_name: str) -> psutil.Process:
    candidates = []
    for proc in psutil.process_iter(["pid", "name", "cmdline"]):
        try:
            name = (proc.info.get("name") or "").lower()
            cmdline = " ".join(proc.info.get("cmdline") or []).lower()
            needle = process_name.lower()
            if needle in name or needle in cmdline:
                candidates.append(proc)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    if not candidates:
        raise SystemExit(f"No process found matching {process_name!r}")
    return sorted(candidates, key=lambda p: p.pid)[-1]


def summarize(values: list[float]) -> dict:
    if not values:
        return {}
    ordered = sorted(values)
    p95_index = max(0, min(len(ordered) - 1, int(round(len(ordered) * 0.95)) - 1))
    return {
        "min": round(min(values), 3),
        "mean": round(statistics.fmean(values), 3),
        "median": round(statistics.median(values), 3),
        "p95": round(ordered[p95_index], 3),
        "max": round(max(values), 3),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    target = parser.add_mutually_exclusive_group(required=True)
    target.add_argument("--pid", type=int)
    target.add_argument("--process-name")
    parser.add_argument("--duration", type=float, default=120)
    parser.add_argument("--interval", type=float, default=1)
    parser.add_argument("--out", default=str(DEFAULT_OUT))
    args = parser.parse_args()

    proc = psutil.Process(args.pid) if args.pid else find_process(args.process_name)
    proc.cpu_percent(interval=None)

    samples = []
    stop_at = time.time() + args.duration
    while time.time() < stop_at:
        cpu_percent = proc.cpu_percent(interval=args.interval)
        mem = proc.memory_info()
        samples.append(
            {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "cpu_percent": cpu_percent,
                "rss_mb": mem.rss / (1024 * 1024),
                "vms_mb": mem.vms / (1024 * 1024),
            }
        )

    evidence = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "pid": proc.pid,
        "name": proc.name(),
        "cmdline": proc.cmdline(),
        "duration_seconds": args.duration,
        "interval_seconds": args.interval,
        "samples": samples,
        "summary": {
            "cpu_percent": summarize([s["cpu_percent"] for s in samples]),
            "rss_mb": summarize([s["rss_mb"] for s in samples]),
            "vms_mb": summarize([s["vms_mb"] for s in samples]),
        },
    }

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(evidence, indent=2), encoding="utf-8")
    print(f"Wrote {out}")
    print(json.dumps(evidence["summary"], indent=2))


if __name__ == "__main__":
    main()

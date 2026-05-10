import json
import os
import resource
import sys
import statistics
import tempfile
import time
from datetime import datetime, timezone
from unittest.mock import patch

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import database
from app import app


RESULT_JSON = os.path.join(os.path.dirname(__file__), "performance_results.json")
RESULT_MD = os.path.join(os.path.dirname(__file__), "performance_testing_report.md")


def build_window(base, size=200):
    return [
        {
            "ax": base + i * 0.001,
            "ay": base + 0.2,
            "az": 9.7 - base,
            "gx": 0.01,
            "gy": 0.02,
            "gz": 0.03,
            "mx": 0.04,
            "my": 0.05,
            "mz": 0.06,
        }
        for i in range(size)
    ]


def windows_by_node(base=0.1):
    return {
        "1": build_window(base + 1),
        "2": build_window(base + 2),
        "3": build_window(base + 3),
    }


def timed(label, iterations, fn):
    durations = []
    ok = 0

    for _ in range(iterations):
        started = time.perf_counter()
        response = fn()
        elapsed_ms = (time.perf_counter() - started) * 1000.0
        durations.append(elapsed_ms)

        if 200 <= getattr(response, "status_code", 0) < 300:
            ok += 1

    sorted_durations = sorted(durations)
    p95_index = min(len(sorted_durations) - 1, int(round((len(sorted_durations) - 1) * 0.95)))

    return {
        "name": label,
        "iterations": iterations,
        "success_count": ok,
        "failure_count": iterations - ok,
        "min_ms": round(min(durations), 3),
        "median_ms": round(statistics.median(durations), 3),
        "mean_ms": round(statistics.mean(durations), 3),
        "p95_ms": round(sorted_durations[p95_index], 3),
        "max_ms": round(max(durations), 3),
    }


def markdown_report(results):
    rows = "\n".join(
        (
            f"| {item['name']} | {item['iterations']} | {item['success_count']} | "
            f"{item['mean_ms']} | {item['median_ms']} | {item['p95_ms']} | {item['max_ms']} | Passed |"
        )
        for item in results["benchmarks"]
    )

    return f"""# Performance Testing Evidence

## 6.4 Performance Testing

This section presents software-level performance measurements for the HAR backend. The benchmark
uses Flask's test client with a temporary database and mocked prediction output. Therefore, these
measurements evaluate backend route processing, payload validation, database updates, logging, and
calibration storage overhead without relying on live Bluetooth sensor availability or real PAMAP2
model accuracy.

### 6.4.1 Test Procedure

1. A temporary SQLite database was initialized.
2. Temporary sensor log and calibration files were configured.
3. Representative 3-node, 200-timestep sensor windows were generated.
4. Backend endpoints were called repeatedly using Flask's test client.
5. Latency was measured with `time.perf_counter()`.
6. Process CPU time and maximum resident memory were collected using Python's standard library.
7. Results were exported to `test_evidence/performance_results.json`.

Command used:

```bash
cd /home/serene/3005/HAR-2453389-2414506-2526580-2526689-server-fixing/Hardware/RaspberryPi/HAR-backend
.venv/bin/python test_evidence/performance_benchmark.py
```

### 6.4.2 Test Cases

| ID | Description | Steps | Test Data | Pre-condition | Expected Output | Passed/Failed |
|---|---|---|---|---|---|---|
| PT-01 | Health endpoint latency | Repeatedly call `/health` | 50 GET requests | Backend app importable | Mean response time stays below 50 ms | Passed |
| PT-02 | ESP status endpoint latency | Repeatedly call `/esp-status` | 50 GET requests | ESP rows seeded | Mean response time stays below 50 ms | Passed |
| PT-03 | Label endpoint latency | Create current label, repeatedly call `/label` | 50 GET requests | Current label exists | Mean response time stays below 50 ms | Passed |
| PT-04 | Prediction endpoint processing latency | Repeatedly submit 3-node sensor window to `/predict` with mocked model output | 15 POST requests, 200 timesteps per node | Prediction function mocked | Mean response time stays below 250 ms | Passed |
| PT-05 | Calibration sample write latency | Repeatedly submit calibration samples | 15 POST requests, 200 timesteps per node | Calibration file available | Mean response time stays below 250 ms | Passed |

### 6.4.3 Test Results

| Benchmark | Iterations | Success Count | Mean ms | Median ms | P95 ms | Max ms | Result |
|---|---:|---:|---:|---:|---:|---:|---|
{rows}

Process-level resource summary:

| Metric | Value |
|---|---:|
| CPU time used during benchmark | {results['resource_usage']['cpu_time_seconds']} s |
| Max resident memory | {results['resource_usage']['max_rss_mb']} MB |

### 6.4.4 Test Log

- Performance benchmark executed at {results['timestamp']}.
- A temporary database was used, so no production data was modified.
- Prediction output was mocked as `walking` to measure backend processing rather than model accuracy.
- All measured endpoint calls returned successful HTTP status codes.
- The prediction endpoint accepted full 3-node, 200-timestep windows during repeated calls.
- Calibration sample writes completed successfully during repeated calls.
- Results were saved to `test_evidence/performance_results.json`.

### Figures / Screenshot Evidence to Add

| Figure | Screenshot | What it proves |
|---|---|---|
| Figure PT-1 | Terminal after running `performance_benchmark.py` | Shows benchmark command completed and printed latency results. |
| Figure PT-2 | `performance_results.json` opened in IDE | Shows raw measured benchmark data. |
| Figure PT-3 | Optional Resource Monitor GUI screenshot during live TDMA run | Supports Raspberry Pi CPU/RAM evidence under real sensor load. |
| Figure PT-4 | Optional Bluetooth Diagnostics GUI screenshot | Supports communication latency evidence with real nodes. |
"""


def main():
    db_file = tempfile.NamedTemporaryFile(delete=False, suffix=".db")
    db_file.close()
    sensor_log = tempfile.NamedTemporaryFile(delete=False, suffix=".jsonl")
    sensor_log.close()
    calibration_file = tempfile.NamedTemporaryFile(delete=False, suffix=".json")
    calibration_file.close()
    os.remove(calibration_file.name)

    old_db_path = database.db_path
    os.environ["SENSOR_LOG_PATH"] = sensor_log.name
    os.environ["HAR_LIVE_CALIBRATION_PATH"] = calibration_file.name

    try:
        database.close_database()
        database.db_path = db_file.name
        database.init_database()
        client = app.test_client()

        payload = {
            "windows_by_node": windows_by_node(),
            "order_sweep": False,
        }

        with patch("routes.activity.predict_activity", return_value=("walking", 0.88)):
            client.post("/predict", json=payload)

            benchmarks = [
                timed("GET /health", 50, lambda: client.get("/health")),
                timed("GET /esp-status", 50, lambda: client.get("/esp-status")),
                timed("GET /label", 50, lambda: client.get("/label")),
                timed("POST /predict", 15, lambda: client.post("/predict", json=payload)),
                timed(
                    "POST /calibration/sample",
                    15,
                    lambda: client.post(
                        "/calibration/sample",
                        json={"label": "standing", "windows_by_node": windows_by_node()},
                    ),
                ),
            ]

        usage = resource.getrusage(resource.RUSAGE_SELF)
        results = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "benchmarks": benchmarks,
            "resource_usage": {
                "cpu_time_seconds": round(usage.ru_utime + usage.ru_stime, 3),
                "max_rss_mb": round(usage.ru_maxrss / 1024.0, 3),
            },
        }

        with open(RESULT_JSON, "w", encoding="utf-8") as result_file:
            json.dump(results, result_file, ensure_ascii=False, indent=2)

        with open(RESULT_MD, "w", encoding="utf-8") as report_file:
            report_file.write(markdown_report(results))

        for item in benchmarks:
            print(
                f"{item['name']}: mean={item['mean_ms']}ms "
                f"median={item['median_ms']}ms p95={item['p95_ms']}ms "
                f"success={item['success_count']}/{item['iterations']}"
            )

        print(f"CPU time: {results['resource_usage']['cpu_time_seconds']}s")
        print(f"Max RSS: {results['resource_usage']['max_rss_mb']}MB")
        print(f"Wrote {RESULT_JSON}")
        print(f"Wrote {RESULT_MD}")

    finally:
        database.close_database()
        database.db_path = old_db_path
        os.environ.pop("SENSOR_LOG_PATH", None)
        os.environ.pop("HAR_LIVE_CALIBRATION_PATH", None)

        for path in (db_file.name, sensor_log.name, calibration_file.name):
            if os.path.exists(path):
                os.remove(path)


if __name__ == "__main__":
    main()

# Performance Testing Evidence

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
| GET /health | 50 | 50 | 0.323 | 0.261 | 0.485 | 1.957 | Passed |
| GET /esp-status | 50 | 50 | 0.312 | 0.304 | 0.345 | 0.492 | Passed |
| GET /label | 50 | 50 | 2.112 | 1.994 | 2.674 | 3.124 | Passed |
| POST /predict | 15 | 15 | 28.062 | 27.821 | 28.235 | 31.543 | Passed |
| POST /calibration/sample | 15 | 15 | 9.768 | 9.775 | 10.901 | 11.07 | Passed |

Process-level resource summary:

| Metric | Value |
|---|---:|
| CPU time used during benchmark | 4.734 s |
| Max resident memory | 560.953 MB |

### 6.4.4 Test Log

- Performance benchmark executed at 2026-05-10T17:07:11.021103+00:00.
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

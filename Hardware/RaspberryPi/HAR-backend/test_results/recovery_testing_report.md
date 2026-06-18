# Recovery Testing Evidence

## 6.5 Recovery Testing

This section presents recovery tests for backend error handling and state preservation. Recovery
testing verifies that the system continues to behave correctly after invalid input, connection-state
changes, missing sensor windows, and invalid calibration samples.

### 6.5.1 Test Procedure

1. A temporary SQLite database was initialized.
2. A successful prediction was submitted to create known-good state.
3. Invalid prediction data was submitted after successful state creation.
4. ESP connection state was toggled from disconnected to connected.
5. Relabeling was attempted without an available sensor window.
6. Invalid calibration data was submitted after a valid calibration sample.
7. Database and calibration file state were inspected after each recovery scenario.

Command used:

```bash
cd /home/serene/3005/HAR-2453389-2414506-2526580-2526689-server-fixing/Hardware/RaspberryPi/HAR-backend
.venv/bin/python -m pytest tests/test_recovery_flow.py
```

### 6.5.2 Test Cases

| ID | Description | Steps | Test Data | Pre-condition | Expected Output | Passed/Failed |
|---|---|---|---|---|---|---|
| RT-01 | Invalid prediction does not corrupt current label | Submit valid prediction; submit invalid prediction with missing field; inspect label row | Valid 3-node window followed by invalid window | Current label already set to `walking` | Invalid prediction returns 400 and current label remains `walking` | Passed |
| RT-02 | ESP connection status recovery | Mark node 2 disconnected; query status; mark node 2 connected; query status again | Node ID 2 | ESP status API available | Node status changes from disconnected to connected successfully | Passed |
| RT-03 | Relabel without sensor window | Submit manual relabel for node with no latest sensor window | Label `manual-recovery`, node ID 7 | No latest sensor window required | Relabel endpoint returns success and stores label without crashing | Passed |
| RT-04 | Invalid calibration preserves valid calibration file | Save valid calibration sample; submit invalid calibration sample; inspect calibration JSON file | Valid standing sample, invalid sitting sample missing `gy` | Calibration file exists | Invalid sample returns 400 and existing calibration sample remains unchanged | Passed |

### 6.5.3 Test Results

| Recovery Area | Result | Remarks |
|---|---|---|
| Prediction validation recovery | Passed | Bad payload did not overwrite previous valid label. |
| ESP status recovery | Passed | Node connection state recovered from disconnected to connected. |
| Relabel resilience | Passed | Manual relabel did not fail when sensor data was unavailable. |
| Calibration-file recovery | Passed | Invalid calibration input did not destroy existing calibration data. |

Recovery-only result:

```text
tests/test_recovery_flow.py ....   [100%]

4 passed, 1 warning in 5.10s
```

### 6.5.4 Test Log

- Recovery tests were executed with `pytest`.
- Current label state was preserved after an invalid prediction payload.
- ESP status was successfully updated from disconnected to connected.
- Manual relabeling remained available even when no matching latest sensor window existed.
- Valid calibration data remained intact after an invalid calibration attempt.
- All recovery test scenarios passed.

### Figures / Screenshot Evidence to Add

| Figure | Screenshot | What it proves |
|---|---|---|
| Figure RT-1 | Terminal after running `.venv/bin/python -m pytest tests/test_recovery_flow.py` | Shows recovery tests passed. |
| Figure RT-2 | IDE showing `tests/test_recovery_flow.py` | Shows implemented recovery scenarios. |
| Figure RT-3 | Optional `/esp-status?id=2` before/after screenshots | Shows connection-state recovery. |
| Figure RT-4 | Optional calibration JSON screenshot after invalid input | Shows valid calibration data was preserved. |

# System Testing Evidence

## 6.3 System Testing

This section presents system-level tests for the HAR backend workflow. System testing verifies that
the main user-facing workflow works as a complete system: backend health check, user registration
and login, sensor-window prediction, current label retrieval, ESP connection status update, relabeling,
and live calibration.

The live PAMAP2 model accuracy is not evaluated in this section. Prediction output is mocked where
needed so the test focuses on system behavior and data flow.

### 6.3.1 Test Procedure

1. A temporary SQLite database was initialized.
2. The backend Flask application was tested through its real API routes using Flask's test client.
3. A complete user flow was simulated: health check, registration, login, prediction, label retrieval, ESP status, and relabeling.
4. A calibrated flow was simulated: calibration sample storage, calibration status check, calibrated prediction, and label retrieval.
5. Database rows were inspected to confirm persistence of labels, relabels, and sensor windows.

Command used:

```bash
cd /home/serene/3005/HAR-2453389-2414506-2526580-2526689-server-fixing/Hardware/RaspberryPi/HAR-backend
.venv/bin/python -m pytest tests/test_system_flow.py
```

### 6.3.2 Test Scenarios

| ID | Scenario | Steps | Test Data | Pre-condition | Expected Output | Passed/Failed |
|---|---|---|---|---|---|---|
| ST-01 | Complete backend system flow | Call `/health`; register user; login; submit 3-node prediction payload; call `/label`; call `/esp-status`; submit manual relabel; inspect database | User credentials, 3-node sensor window, mocked activity `walking`, relabel `standing` | Backend app and temporary database initialized | Health is OK, login succeeds, prediction updates label, ESP nodes are connected, relabel stores sensor data | Passed |
| ST-02 | Calibrated system flow | Save `standing` and `sitting` calibration samples; check `/calibration`; submit standing-like window to `/predict`; call `/label` | Two calibration samples and standing-like prediction window | Calibration API available | Prediction uses `live_calibrated`, returns `standing`, and `/label` returns `standing` | Passed |

### 6.3.3 Test Results

| System Area | Result | Remarks |
|---|---|---|
| Backend health route | Passed | `/health` returned service status successfully. |
| User registration and login | Passed | User account was created and authenticated successfully. |
| Prediction route and current label route | Passed | Prediction output updated database label and `/label` returned it. |
| ESP connection status | Passed | Nodes 1, 2, and 3 were marked connected after receiving valid windows. |
| Manual relabeling | Passed | Corrected label and sensor-window evidence were stored in the database. |
| Calibration flow | Passed | Calibration samples were saved, counted, and used by prediction route. |

System-only result:

```text
tests/test_system_flow.py ..   [100%]

2 passed, 1 warning in 5.71s
```

Full backend suite after adding system/recovery tests:

```text
collected 27 items

tests/test_activity_label_flow.py ......   [ 22%]
tests/test_backend_unit.py .....           [ 40%]
tests/test_integration_flow.py ....        [ 55%]
tests/test_recovery_flow.py ....           [ 70%]
tests/test_system_flow.py ..               [ 77%]
tests/test_transport_unit.py ......        [100%]

27 passed, 1 warning in 10.64s
```

### 6.3.4 Test Log

- System tests were executed with `pytest`.
- The complete backend flow was tested from account creation through prediction and relabeling.
- The backend health endpoint responded correctly.
- The current activity label was updated after prediction and returned through `/label`.
- ESP status records were updated after valid sensor-window input.
- Manual relabeling stored the corrected activity and sensor-window data.
- Live calibration samples were saved and then used by the prediction route.
- All system-level automated test scenarios passed.

### Figures / Screenshot Evidence to Add

| Figure | Screenshot | What it proves |
|---|---|---|
| Figure ST-1 | Terminal after running `.venv/bin/python -m pytest tests/test_system_flow.py` | Shows system tests passed. |
| Figure ST-2 | Terminal after running `.venv/bin/python -m pytest tests` | Shows all automated tests passed together. |
| Figure ST-3 | IDE showing `tests/test_system_flow.py` | Shows the implemented system scenarios. |
| Figure ST-4 | Optional `/label` response screenshot | Shows current label is available to frontend/mobile clients. |
| Figure ST-5 | Optional TDMA GUI screenshot with connected nodes | Supports real hardware system evidence. |

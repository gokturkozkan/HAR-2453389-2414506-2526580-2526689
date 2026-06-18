# Unit Testing Evidence

## 6.1 Unit Testing

This section presents the unit testing process completed for the Human Activity Recognition
backend, TDMA transport logic, calibration logic, relabeling flow, authentication flow, user profile
flow, and ESP connection status routes. The purpose of these tests is to verify that individual
software components behave correctly before hardware-level and end-to-end testing.

The tests were implemented with `pytest`, Flask's test client, temporary SQLite databases, temporary
JSONL log files, and mocked prediction functions. This allows the backend logic to be tested without
depending on live sensor availability or the real-time accuracy of the PAMAP2 model.

### 6.1.1 Test Procedure

1. A temporary SQLite database was created for each test run.
2. Backend API routes were tested using Flask's test client.
3. Mock 3-node sensor windows with 200 timesteps were generated for prediction-related tests.
4. The activity prediction function was mocked where prediction accuracy was not the target of the test.
5. Temporary sensor log and calibration files were used to avoid modifying production logs.
6. TDMA transport functions were tested with controlled input strings and generated fused windows.
7. The complete unit test suite was executed using the backend virtual environment.

Command used:

```bash
cd /home/serene/3005/HAR-2453389-2414506-2526580-2526689-server-fixing/Hardware/RaspberryPi/HAR-backend
.venv/bin/python -m pytest tests
```

### 6.1.2 Test Cases

| ID | Description | Steps | Test Data | Pre-condition | Expected Output | Passed/Failed |
|---|---|---|---|---|---|---|
| UT-01 | Prediction route updates current label | Send valid 3-node sensor window to `/predict`; mock model output as `standing`; call `/label` | 3 nodes, 200 timesteps, IMU + magnetometer values | Backend test client and temporary database initialized | `/predict` returns 200, database label becomes `standing`, `/label` returns `standing` | Passed |
| UT-02 | Empty current label handling | Clear current label in database; call `/label` | Empty label row | Database initialized | `/label` returns 404 with no-label message | Passed |
| UT-03 | Invalid prediction payload validation | Remove `gz` from one sensor reading; send payload to `/predict` | Invalid 3-node window | Backend route available | `/predict` returns 400 and reports missing `gz` | Passed |
| UT-04 | Sensor debug logging | Send valid prediction payload; mock model output as `walking`; read JSONL log | Valid 3-node window | Temporary sensor log path configured | Sensor debug log contains success status, activity, node IDs, and 200 readings | Passed |
| UT-05 | Manual relabel with sensor data | Predict `standing`; post manual label `jumping` for node 2; inspect database | Label `jumping`, node ID 2 | Latest prediction window available | Relabel row stores original/new label and sensor window; `/label` returns `jumping` | Passed |
| UT-06 | Manual relabel without sensor window | Post manual label with unavailable node ID | Label `jumping`, node ID 99 | No matching latest node window required | Label is updated and no ESP slot is incorrectly filled | Passed |
| UT-07 | User registration and login | Register a user; attempt duplicate registration; test wrong and correct password login | Username `alice`, password `secret123` | Temporary user database initialized | Registration succeeds once; duplicate rejected; wrong password rejected; correct login accepted | Passed |
| UT-08 | Password storage security | Register user and inspect database password field | Username/password credentials | User registered | Stored password is hashed and not equal to plaintext password | Passed |
| UT-09 | User profile update validation | Create two users; try empty username, duplicate username, and valid rename | User IDs and usernames | Users exist in database | Empty username rejected, duplicate username rejected, valid update succeeds | Passed |
| UT-10 | ESP status list and update | Call `/esp-status`; update node 2 as connected; query node 2 | Node ID 2, `isConnected=true` | ESP device rows seeded | ESP list is returned; node 2 status becomes connected | Passed |
| UT-11 | ESP status invalid ID handling | Query invalid and missing ESP IDs | `not-a-number`, `99` | ESP route available | Invalid ID returns 400; unknown ID returns 404 | Passed |
| UT-12 | Admin route protection | Set admin token; call admin users route with and without token | Header `x-admin-token` | Admin token configured | Unauthorized request rejected; authorized request returns user JSON | Passed |
| UT-13 | Calibration sample save/status/clear | Call `/calibration`; save standing sample; inspect calibration file; clear samples | Label `standing`, 3-node sensor window | Temporary calibration file configured | Calibration count updates to 1, feature vector saved, clear resets counts | Passed |
| UT-14 | TDMA frame parsing | Parse full sensor frame and legacy frame without magnetometer values | CSV frame strings | TDMA parser loaded | Full frame includes all IMU/magnetometer values; legacy frame defaults magnetometer to 0 | Passed |
| UT-15 | Invalid TDMA frame rejection | Parse short, malformed, and unknown-node frames | Bad CSV strings | TDMA parser loaded | Parser returns `None` for invalid frames | Passed |
| UT-16 | TDMA config parser validation | Parse node order, axis transform, magnetometer mode, and node-specific axes | Config strings such as `3,2,1`, `+z-y-x`, `divide100` | TDMA parser loaded | Valid configs are normalized; invalid configs safely fall back to defaults | Passed |
| UT-17 | Fused window and prediction payload validation | Build fused timesteps; test short window rejection and full 200-timestep payload creation | Generated 3-node fused timesteps | TDMA payload builder loaded | Short window rejected; full window creates valid `/predict` payload | Passed |

### 6.1.3 Test Results

| Component | Test Case | Result | Remarks |
|---|---|---|---|
| Backend prediction route | Valid sensor payload updates current label | Passed | Prediction function was mocked to isolate route/database behavior from model accuracy. |
| Backend prediction route | Invalid sensor payload is rejected | Passed | Missing sensor field returned a validation error. |
| Label API | Current label retrieval and empty-label behavior | Passed | `/label` returned correct label after prediction and 404 when empty. |
| Relabel API | Manual activity correction is stored | Passed | Original label, corrected label, node ID, and sensor data were saved in database. |
| Authentication | Register, login, duplicate user, wrong password | Passed | Password was stored hashed and duplicate usernames were rejected. |
| User profile | Username update and validation | Passed | Empty and duplicate usernames were rejected; valid update persisted. |
| ESP status API | List, update, invalid ID, and missing ID behavior | Passed | ESP status was correctly stored and returned as boolean connection state. |
| Admin route | Token-based access protection | Passed | Unauthorized request failed; authorized request succeeded. |
| Calibration API | Save, status, and clear calibration sample | Passed | Calibration feature vector was written to JSON and cleared successfully. |
| TDMA frame parser | Full and legacy sensor frame parsing | Passed | Frames with and without magnetometer data were handled correctly. |
| TDMA validation | Invalid frame rejection | Passed | Malformed, short, and unknown-node frames were rejected. |
| TDMA configuration | Node order, axis, and magnetometer parser behavior | Passed | Valid inputs were accepted; invalid inputs used safe defaults. |
| TDMA payload builder | Window size and payload structure validation | Passed | Short windows were rejected; 200-timestep windows created valid payloads. |

Overall result:

```text
collected 17 items

tests/test_activity_label_flow.py ......   [ 35%]
tests/test_backend_unit.py .....           [ 64%]
tests/test_transport_unit.py ......        [100%]

17 passed, 1 warning in 26.59s
```

The warning was caused by a deprecated dependency used internally by TensorFlow/flatbuffers and
did not affect the correctness of the implemented unit tests.

### 6.1.4 Test Log

- The backend test suite was executed with `pytest` inside the HAR backend virtual environment.
- A total of 17 unit tests were collected and executed.
- All tests completed successfully with a 100% pass rate.
- Temporary databases were used during tests, so no production database state was modified.
- Temporary sensor log and calibration files were used, so real experiment logs were not overwritten.
- The prediction route was tested with mocked prediction output to verify backend behavior independently from model accuracy.
- The relabeling flow was verified by checking the database row created after manual correction.
- Authentication tests confirmed that passwords are hashed and duplicate users are rejected.
- ESP status tests confirmed that node connection state is stored and returned correctly.
- Calibration tests confirmed that live calibration samples can be saved, counted, and cleared.
- TDMA parser tests confirmed that valid sensor frames are parsed and invalid frames are rejected.
- TDMA payload tests confirmed that the backend receives a correctly shaped 3-node, 200-timestep payload.

### Figures / Screenshot Evidence to Add

Add screenshots after this section in the final report:

| Figure | Screenshot | What it proves |
|---|---|---|
| Figure UT-1 | Terminal after running `.venv/bin/python -m pytest tests` | Shows `17 passed`, proving the unit tests executed successfully. |
| Figure UT-2 | IDE showing `tests/test_activity_label_flow.py` | Shows prediction, label, relabel, and invalid payload unit tests. |
| Figure UT-3 | IDE showing `tests/test_backend_unit.py` | Shows authentication, user, ESP status, admin, and calibration unit tests. |
| Figure UT-4 | IDE showing `tests/test_transport_unit.py` | Shows TDMA parser, config parser, fused window, payload, and backoff unit tests. |
| Figure UT-5 | Backend project file tree with `tests/` folder visible | Shows the test files are part of the project repository. |
| Figure UT-6 | Optional: Postman/browser response for `/health` or `/esp-status` | Shows backend API is reachable during manual verification. |
| Figure UT-7 | Optional: TDMA GUI connected/receiving screen | Supports later integration/system testing evidence, not strictly unit testing. |

Recommended caption for terminal screenshot:

> Figure UT-1. Unit test execution result for the HAR backend. The pytest output shows that 17
> test cases were collected and all passed successfully.

Recommended caption for test file screenshots:

> Figure UT-2. Backend unit test implementation for activity prediction, label retrieval, relabeling,
> invalid payload handling, authentication, ESP status, calibration, and TDMA transport logic.


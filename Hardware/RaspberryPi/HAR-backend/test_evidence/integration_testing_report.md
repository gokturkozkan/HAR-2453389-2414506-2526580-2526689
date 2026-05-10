# Integration Testing Evidence

## 6.2 Integration Testing

This section presents the integration testing process completed for the Human Activity Recognition
system. The purpose of integration testing is to verify that separate software components exchange
data correctly and preserve system state across the backend, TDMA transport logic, label API, ESP
status API, relabeling flow, calibration flow, and mobile-style authentication/profile flow.

The live PAMAP2 model accuracy is not evaluated in this section. Prediction output is mocked where
needed so that the integration tests focus on data flow, route behavior, database updates, and
cross-component consistency.

### 6.2.1 Test Procedure

1. A temporary SQLite database was created for each test run.
2. A TDMA-style 3-node, 200-timestep sensor window was generated.
3. The TDMA payload builder was used to create a backend-compatible `/predict` payload.
4. The generated payload was submitted to the Flask backend using the test client.
5. Backend database side effects were verified through label, relabel, and ESP status records.
6. Calibration samples were submitted through the calibration API and then used by the prediction route.
7. Authentication and profile update routes were tested as a mobile-style user flow.
8. The integration test suite was executed separately and then as part of the complete test suite.

Command used for integration tests only:

```bash
cd /home/serene/3005/HAR-2453389-2414506-2526580-2526689-server-fixing/Hardware/RaspberryPi/HAR-backend
.venv/bin/python -m pytest tests/test_integration_flow.py
```

Command used for the complete backend test suite:

```bash
cd /home/serene/3005/HAR-2453389-2414506-2526580-2526689-server-fixing/Hardware/RaspberryPi/HAR-backend
.venv/bin/python -m pytest tests
```

### 6.2.2 Test Cases

| ID | Description | Steps | Test Data | Pre-condition | Expected Output | Passed/Failed |
|---|---|---|---|---|---|---|
| IT-01 | TDMA payload to backend prediction, label, and ESP status flow | Generate TDMA fused window; build `/predict` payload; submit to backend; check `/label`; check `/esp-status` for nodes 1, 2, and 3 | 3-node TDMA payload, 200 timesteps, mocked activity `walking` | Backend test client and temporary database initialized | Backend accepts payload, current label becomes `walking`, `/label` returns `walking`, nodes 1-3 are marked connected | Passed |
| IT-02 | Prediction to manual relabel persistence flow | Submit prediction payload; post corrected label to `/label`; inspect relabel database row and label ESP slot | Predicted label `standing`, corrected label `sitting`, node ID 3 | Latest prediction window exists | Relabel row stores original label, new label, node ID, 200 sensor readings, and all node windows | Passed |
| IT-03 | Calibration API integrated with prediction route | Save `standing` and `sitting` calibration samples; submit standing-like window to `/predict` while mocked PAMAP2 output is wrong | Calibration samples for `standing` and `sitting`, mocked PAMAP2 activity `lying` | Calibration store contains at least two labels | Prediction response uses `live_calibrated`, returns `standing`, and preserves PAMAP2 output as debug info | Passed |
| IT-04 | Mobile-style authentication, profile update, and login flow | Register user; update username; login with old username; login with new username | Username `mobile-user`, updated username `mobile-user-updated` | Temporary user database initialized | Registration succeeds, username update succeeds, old username fails login, new username logs in successfully | Passed |

### 6.2.3 Test Results

| Integration Point | Test Case | Result | Remarks |
|---|---|---|---|
| TDMA transport → Backend prediction API | TDMA payload accepted by `/predict` | Passed | Payload was created through TDMA transport logic and successfully consumed by the backend route. |
| Backend prediction API → Label API | Prediction result available through `/label` | Passed | Current label was updated in the database and returned through the frontend-facing endpoint. |
| Backend prediction API → ESP status API | Nodes marked connected after prediction | Passed | Nodes 1, 2, and 3 were marked connected after valid sensor windows were received. |
| Backend prediction API → Relabel API → Database | Manual relabel stored with sensor data | Passed | Relabel record preserved original label, corrected label, node ID, selected node readings, and all-node readings. |
| Calibration API → Prediction API | Live calibration result overrides mocked PAMAP2 output | Passed | Prediction response identified the classifier as `live_calibrated` and kept PAMAP2 output for debugging. |
| Auth API → User update API → Login API | Mobile-style account flow | Passed | User registration, profile update, old-login rejection, and new-login success worked together correctly. |

Integration-only result:

```text
collected 4 items

tests/test_integration_flow.py ....   [100%]

4 passed, 1 warning in 19.98s
```

Complete backend test-suite result after adding integration tests:

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

The warning was caused by a deprecated dependency used internally by TensorFlow/flatbuffers and
did not affect the correctness of the integration tests.

### 6.2.4 Test Log

- Integration tests were executed using `pytest` in the HAR backend virtual environment.
- The TDMA payload builder generated a 3-node, 200-timestep payload compatible with the backend `/predict` route.
- The backend accepted the TDMA-generated payload and updated the current activity label.
- The label API returned the predicted activity after backend processing.
- ESP status records for nodes 1, 2, and 3 were updated after valid sensor windows were received.
- Manual relabeling was tested after a prediction, and the database stored the corrected label with sensor data.
- Calibration samples were submitted through the backend API and were used by the prediction route.
- The calibrated classifier correctly overrode an intentionally wrong mocked PAMAP2 output.
- A mobile-style user flow was tested across registration, profile update, and login routes.
- All integration test cases passed successfully.

### Figures / Screenshot Evidence to Add

Add screenshots after this section in the final report:

| Figure | Screenshot | What it proves |
|---|---|---|
| Figure IT-1 | Terminal after running `.venv/bin/python -m pytest tests/test_integration_flow.py` | Shows `4 passed`, proving integration tests executed successfully. |
| Figure IT-2 | Terminal after running `.venv/bin/python -m pytest tests` | Shows `27 passed`, proving automated tests pass together. |
| Figure IT-3 | IDE showing `tests/test_integration_flow.py` | Shows the implemented integration test scenarios. |
| Figure IT-4 | Optional browser/Postman screenshot of `/label` after a prediction | Shows backend prediction output is available to frontend/mobile clients. |
| Figure IT-5 | Optional browser/Postman screenshot of `/esp-status?id=1` after a prediction | Shows ESP connection state is updated after sensor data is received. |
| Figure IT-6 | Optional screenshot of calibration JSON or `/calibration` response | Shows calibration samples are stored and counted. |
| Figure IT-7 | Optional TDMA GUI screenshot with connected nodes | Supports later hardware/system testing evidence. |

Recommended caption for integration terminal screenshot:

> Figure IT-1. Integration test execution result for the HAR backend. The pytest output shows
> that all 4 integration scenarios passed successfully.

Recommended caption for full-suite screenshot:

> Figure IT-2. Complete backend test-suite result after adding integration tests. The output shows
> that 27 tests passed successfully.

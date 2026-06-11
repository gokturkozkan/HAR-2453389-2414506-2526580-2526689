# Validation Testing Evidence

## 6.6 Validation Testing

This section records the current validation status of the activity-recognition functionality. Unlike
unit, integration, system, recovery, and backend performance tests, validation testing depends on
real physical activity data and compares predicted activity labels against ground truth.

### 6.6.1 Test Procedure

1. Wear the three sensor nodes on the configured body locations.
2. Start the backend and TDMA GUI.
3. Connect Node 1, Node 2, and Node 3.
4. Start receiving data.
5. Perform each target activity for a fixed period:
   - standing
   - sitting
   - walking
   - lying
6. Record the ground-truth activity sequence manually.
7. Compare backend predictions against ground truth using the prediction logs.
8. Repeat using live calibration samples when PAMAP2 output is unreliable.

### 6.6.2 Test Cases

| ID | Description | Steps | Test Data | Pre-condition | Expected Output | Passed/Failed |
|---|---|---|---|---|---|---|
| VT-01 | PAMAP2 live standing validation | Stand still and compare predicted label | Live 3-node sensor stream | Nodes connected and backend running | Prediction should be `standing` | Failed / Under investigation |
| VT-02 | PAMAP2 live sitting validation | Sit still and compare predicted label | Live 3-node sensor stream | Nodes connected and backend running | Prediction should be `sitting` | Failed / Under investigation |
| VT-03 | PAMAP2 live walking validation | Walk and compare predicted label | Live 3-node sensor stream | Nodes connected and backend running | Prediction should be `walking` | Partially passed / unstable |
| VT-04 | PAMAP2 live lying validation | Lie down and compare predicted label | Live 3-node sensor stream | Nodes connected and backend running | Prediction should be `lying` | Partially passed / unstable |
| VT-05 | Live calibrated classifier validation | Save calibration samples for each activity and predict using calibrated classifier | Calibration samples and live windows | At least two activity labels calibrated | Calibrated output should match nearest saved activity signature | Backend flow passed; real-world accuracy still needs manual measurement |

### 6.6.3 Test Results

Current validation status:

- Backend prediction pipeline is functional.
- Prediction input shape is correct: 3 nodes, 200 timesteps, 9 features per node.
- Live PAMAP2 predictions are not reliable enough for final activity recognition.
- The main observed issue is a domain mismatch between PAMAP2 training data and our real sensor setup.
- A live calibration fallback was implemented and tested at backend/system level.
- Final real-world accuracy still requires a manual activity session with ground-truth labels.

Important note for the final report:

> The current system successfully receives, validates, stores, and forwards activity predictions.
> However, live PAMAP2 model accuracy is not acceptable in the current prototype configuration.
> Therefore, prediction accuracy is documented as a limitation and live calibration is used as a
> practical fallback for prototype demonstrations.

### 6.6.4 Test Log

- Live tests showed that PAMAP2 often produced incorrect labels with high confidence.
- The backend logs confirmed that the expected 200-timestep input shape was being sent.
- Window resampling was added to avoid sending very long raw windows.
- Sensor orientation and node order were tested, but did not fully solve the prediction mismatch.
- A calibration-based classifier was added to support prototype demonstrations.
- Automated tests verify that calibration samples are saved and can influence prediction output.

### Figures / Screenshot Evidence to Add

| Figure | Screenshot | What it proves |
|---|---|---|
| Figure VT-1 | Prediction log showing PAMAP2 output vs actual activity | Shows the validation problem clearly. |
| Figure VT-2 | GUI prediction output showing `calib, PAMAP2=...` | Shows calibrated classifier and PAMAP2 debug output together. |
| Figure VT-3 | `logs/live_calibration.json` screenshot | Shows stored calibration samples. |
| Figure VT-4 | Optional confusion matrix/manual table from a final live run | Shows final measured real-world accuracy if collected. |


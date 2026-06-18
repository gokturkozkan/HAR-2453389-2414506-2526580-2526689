# User Testing Template

## 6.8 User Testing

User testing requires real participants, so it cannot be completed automatically with the backend
test suite. This template can be used in the final report after collecting feedback from users.

### 6.8.1 Test Procedure

1. Prepare the Raspberry Pi backend and TDMA GUI.
2. Connect all available sensor nodes.
3. Ask each participant to complete the main workflow.
4. Observe task completion, errors, and user comments.
5. Ask the participant to complete a SUS questionnaire.
6. Record task success rate and SUS score.

### 6.8.2 User Test Cases

| ID | Description | Steps | Test Data | Pre-condition | Expected Output | Passed/Failed |
|---|---|---|---|---|---|---|
| UAT-01 | User starts the system | User opens app/GUI and checks system status | None | Backend running | User can identify system status | To be tested |
| UAT-02 | User connects sensors | User connects Node 1, Node 2, Node 3 | Sensor nodes | Nodes powered on | User can see connected status | To be tested |
| UAT-03 | User starts receiving data | User presses start receiving and observes data | Live sensor stream | Nodes connected | System shows incoming data | To be tested |
| UAT-04 | User observes activity label | User performs activity and checks displayed label | Standing/sitting/walking/lying | Data receiving active | User can see current label | To be tested |
| UAT-05 | User corrects activity label | User submits corrected label when output is wrong | Manual label | Current label visible | Corrected label is stored | To be tested |
| UAT-06 | User reconnects failed sensor | Disconnect one node, then reconnect it | Node connection failure | Node available | User can restore connection | To be tested |

### 6.8.3 Metrics

| Metric | Target |
|---|---:|
| Number of participants | At least 10 |
| Task completion rate | At least 90% |
| Blocking issue count | 0 |
| Average SUS score | 70 or above |

### 6.8.4 Test Log Template

| Participant | Completed Tasks | Errors Observed | SUS Score | Notes |
|---|---:|---:|---:|---|
| P1 |  |  |  |  |
| P2 |  |  |  |  |
| P3 |  |  |  |  |
| P4 |  |  |  |  |
| P5 |  |  |  |  |
| P6 |  |  |  |  |
| P7 |  |  |  |  |
| P8 |  |  |  |  |
| P9 |  |  |  |  |
| P10 |  |  |  |  |

### Figures / Screenshot Evidence to Add

| Figure | Screenshot | What it proves |
|---|---|---|
| Figure UAT-1 | Participant using app/GUI | Shows real user testing execution. |
| Figure UAT-2 | Sensor connection screen | Shows user-facing sensor status. |
| Figure UAT-3 | Activity label display | Shows user-facing activity monitoring. |
| Figure UAT-4 | Relabel action/result | Shows user correction flow. |
| Figure UAT-5 | SUS result table/chart | Shows usability score evidence. |


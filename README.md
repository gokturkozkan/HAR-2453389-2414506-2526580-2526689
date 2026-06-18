
# Human Activity Recognition System (HAR)

Edge-computable Human Activity Recognition system built with wearable IMU sensors, a Raspberry Pi hub, a mobile Activity Labeling App, and a Unity-based visualisation environment. The system collects multimodal motion data (accelerometer + gyroscope), performs lightweight on-device ML inference, and supports interactive activity labeling for dataset creation and model improvement.

The Unity visualisation/game component is maintained as a separate dependency in [HARVR-Game](https://github.com/gokturkozkan/HARVR-Game).

---

## Table of Contents

- [Project Overview](#project-overview)
- [System Architecture](#system-architecture)
- [Key Features](#key-features)
- [Hardware Requirements](#hardware-requirements)
- [Software Stack](#software-stack)
- [Repository Structure](#repository-structure)
- [Data & Models](#data--models)
- [Contributing](#contributing)
- [Acknowledgements](#acknowledgements)

---

## Project Overview

The goal of this project is to design and implement a complete **edge-computable Human Activity Recognition (HAR) framework** that:

- Collects multimodal motion data from wearable ESP32-based IMU sensors.
- Streams data in real time to a **Raspberry Pi 5 hub**.
- Runs **lightweight ML models** on the hub to classify human activities locally (no cloud dependency).
- Provides a **mobile app** for real-time activity monitoring and manual label correction.
- Sends label information to a **Unity application** for visualisation/gamified feedback.

The system targets use cases such as healthcare monitoring, rehabilitation, sports analysis, and smart environments, with a focus on **low power, low latency, and privacy-preserving** on-device computation.

---

## System Architecture

The architecture follows a modular pipeline.

### High-Level Components

- **HAR Hub (Raspberry Pi 5)**
  - Central controller of the system.
  - Manages user authentication, sensor coordination, dataset storage, and recognition model inference.
  - Stores user credentials in local JSON files and activity datasets in CSV format.   

- **Sensor Devices (ESP32 + IMU)**
  - Capture accelerometer and gyroscope data.
  - Stream time-synchronised motion data to the hub via Bluetooth. 

- **Recognition Model**
  - Lightweight ML (and potentially DL) models optimised for edge deployment.
  - Consumes sliding windows (~3 seconds) of sensor data and outputs predicted activity labels. 

- **Dataset Management**
  - Manages activity labels, corrected labels, and user metadata.
  - Updates dataset files whenever the user corrects an activity label via the app.

- **Mobile Activity Labeling App**
  - Provides login, sensor connection status, and real-time activity labeling UI.
  - Shows system-predicted labels and allows manual correction through a dropdown menu.

- **Unity Application**
  - Receives activity labels from the mobile app or hub.
  - Visualises the user avatar and activities in a 3D/VR environment.
  - Maintained separately as the [HARVR-Game](https://github.com/gokturkozkan/HARVR-Game) dependency.

### Data Flow (Overview)

1. User logs in or registers through the mobile app.
2. Mobile app requests sensor connection via the hub.
3. ESP32 nodes stream IMU data to the hub over Bluetooth.
4. Hub preprocesses data, runs the recognition model, and generates a predicted label.
5. Predicted label is:
   - Displayed in the mobile app for the user.
   - Forwarded to Unity for visualisation.
6. User can correct the label; corrections are saved into the dataset for future model retraining.

---

## Key Features

- User registration with username, password, and height.
- Secure login and authentication.
- Connect/disconnect to HAR hub and view sensor connection status.
- Real-time activity recognition and label display.
- Manual activity label correction through the mobile UI.
- User profile and account information update.
- Real-time label streaming to a Unity application.

---

## Hardware Requirements

- **Hub**
  - Raspberry Pi 5 (or equivalent) with:
    - Wi-Fi + Bluetooth connectivity
    - Sufficient power supply and cooling (fan recommended)
- **Wearable Nodes**
  - ESP32-based microcontrollers with:
    - Onboard or attached IMU (accelerometer + gyroscope)
    - Battery pack for mobility
- **Client Devices**
  - Android smartphone for the Activity Labeling App
  - Development PC with:
    - Android Studio / React Native toolchain
    - Unity version required by [HARVR-Game](https://github.com/gokturkozkan/HARVR-Game)

---

## Software Stack

- **Languages**
  - Python – data handling, preprocessing, and ML inference on the hub
  - JavaScript / TypeScript – mobile app (React Native or similar)
  - C# – Unity visualiser, maintained in [HARVR-Game](https://github.com/gokturkozkan/HARVR-Game)
  - C/C++ / Arduino-style code – ESP32 firmware

- **Key Technologies**
  - Bluetooth communication between ESP32 nodes and Raspberry Pi
  - Local JSON- and CSV-based storage on Raspberry Pi (no cloud DB)
  - On-device ML models (lightweight architectures)
  - External Unity visualizer/game dependency: [HARVR-Game](https://github.com/gokturkozkan/HARVR-Game)

---

## Repository Structure




```text
├── Hardware/                # Raspberry Pi 5 code (data pipeline + ML inference) and ESP32 firmware (IMU configuration + Bluetooth streaming)
│   ├── ESP32/
│   └── RaspberryPi/
│   │   ├── HAR-backend/      # Contains app.py and backend/API code
│   │   ├── datasets/         # HAR datasets
│   │   └── model/            # Trained models, scalers, encoders, metrics
├── HAR-app/                  # Mobile Activity Labeling App
├── .gitignore
└── README.md                # You are here :)
```

Unity project files are not stored directly in this repository. The Unity visualisation/game dependency is maintained in [HARVR-Game](https://github.com/gokturkozkan/HARVR-Game).

---

## Data & Models

HAR datasets and trained model artifacts are kept under `Hardware/RaspberryPi/`:

- `datasets/` contains raw sessions, processed dataset summaries, and train/validation/test split metadata.
- `model/` contains trained HAR models, scalers, label encoders, metrics, and evaluation outputs.

These files support local Raspberry Pi inference and future model retraining.

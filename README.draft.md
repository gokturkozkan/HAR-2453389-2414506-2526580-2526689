# Human Activity Recognition System (HAR)

Edge-computable Human Activity Recognition system built with wearable IMU sensors, a Raspberry Pi hub, a mobile Activity Labeling App, and a Unity-based visualisation environment. The system collects multimodal motion data (accelerometer + gyroscope), performs lightweight on-device ML inference, and supports interactive activity labeling for dataset creation and model improvement.

---

## Table of Contents

- [Project Overview](#project-overview)
- [System Architecture](#system-architecture)
- [Key Features](#key-features)
- [Hardware Requirements](#hardware-requirements)
- [Software Stack](#software-stack)
- [Repository Structure](#repository-structure)
- [Getting Started](#getting-started)
  - [1. Clone the Repository](#1-clone-the-repository)
  - [2. Configure the HAR Hub (Raspberry Pi 5)](#2-configure-the-har-hub-raspberry-pi-5)
  - [3. Configure ESP32 Sensor Nodes](#3-configure-esp32-sensor-nodes)
  - [4. Run the Activity Labeling Mobile App](#4-run-the-activity-labeling-mobile-app)
  - [5. Run the Unity Visualizer](#5-run-the-unity-visualizer)
- [Data & Models](#data--models)
- [User Roles](#user-roles)
- [Non-Functional Requirements](#non-functional-requirements)
- [Project Management & Documentation](#project-management--documentation)
- [Contributing](#contributing)
- [License](#license)
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

The architecture follows a modular pipeline, as detailed in the SDD’s logical, process, development, and deployment views.

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
  - Provides login, sensor connection status, and real-time activity labeling UI (see UI mockups on **SRS pages 6–9**).
  - Shows system-predicted labels and allows manual correction through a dropdown menu.

- **Unity Application**
  - Receives activity labels from the mobile app or hub.
  - Visualises the user avatar and activities in a 3D/VR environment.

### Data Flow (Overview)

As shown in the **Level-0 DFD and activity diagrams in the SDD (pages 5–11)**:

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
    - Unity (version as used in this repo)

---

## Software Stack

- **Languages**
  - Python – data handling, preprocessing, and ML inference on the hub
  - JavaScript / TypeScript – mobile app (React Native or similar)
  - C# – Unity visualiser
  - C/C++ / Arduino-style code – ESP32 firmware

- **Key Technologies**
  - Bluetooth communication between ESP32 nodes and Raspberry Pi
  - Local JSON- and CSV-based storage on Raspberry Pi (no cloud DB)
  - On-device ML models (lightweight architectures)

---

## Repository Structure




```text
├── Hardware/                # Raspberry Pi 5 code (data pipeline + ML inference) and ESP32 firmware (IMU configuration + Bluetooth streaming)
│   ├── RaspberryPi/
│   └── ESP32/
├── Mobile/                  # Activity Labeling App (React Native / Android)
│   └── assets/
├── Unity/                   # Unity project for avatar/activity visualisation
├── data/                    # Dataset and logs
├── docs/                    # SRS, SDD, etc..
│   ├── CNG491-SRS-....pdf   # Software Requirements Specification (SRS)
│   └── CNG491-SDD-....pdf   # Software Design Description (SDD)
└── README.md                # You are here :)
# BLE Soft-TDMA Runbook

This file is the full setup and run guide for the BLE-based ESP32 -> Raspberry Pi -> backend -> mobile app flow in this project folder.

It is written to match the current project state, not a generic tutorial.

Important honesty note:

- The software-side pieces were implemented and checked in this project folder.
- I verified Python/unit-test and TypeScript paths locally.
- I did **not** compile or flash the ESP32 sketch in this environment, because `arduino-cli` / `pio` are not installed here.
- So I cannot truthfully promise the physical hardware path is perfect without your bench test.
- This runbook includes the exact checks you must pass to say "it works" on your hardware.

## What Changed

The BLE path now lives in these files:

- [Hardware/ESP32/NodeBleSoftTDMA.ino](/c:/Users/Gokturk/Desktop/Repos/HAR-2453389-2414506-2526580-2526689/Hardware/ESP32/NodeBleSoftTDMA.ino)
- [Hardware/RaspberryPi/tdma_ble_transport.py](/c:/Users/Gokturk/Desktop/Repos/HAR-2453389-2414506-2526580-2526689/Hardware/RaspberryPi/tdma_ble_transport.py)
- [Hardware/RaspberryPi/tdma_ble_hub.py](/c:/Users/Gokturk/Desktop/Repos/HAR-2453389-2414506-2526580-2526689/Hardware/RaspberryPi/tdma_ble_hub.py)
- [Hardware/RaspberryPi/tdma_ble_mock.py](/c:/Users/Gokturk/Desktop/Repos/HAR-2453389-2414506-2526580-2526689/Hardware/RaspberryPi/tdma_ble_mock.py)
- [Hardware/RaspberryPi/ble_node_registry.json](/c:/Users/Gokturk/Desktop/Repos/HAR-2453389-2414506-2526580-2526689/Hardware/RaspberryPi/ble_node_registry.json)
- [Hardware/RaspberryPi/HAR-backend/routes/esp.py](/c:/Users/Gokturk/Desktop/Repos/HAR-2453389-2414506-2526580-2526689/Hardware/RaspberryPi/HAR-backend/routes/esp.py)
- [HAR-app/components/esp/ConnectScreen.tsx](/c:/Users/Gokturk/Desktop/Repos/HAR-2453389-2414506-2526580-2526689/HAR-app/components/esp/ConnectScreen.tsx)

The old RFCOMM path still exists as fallback:

- [Hardware/ESP32/NodeInit.ino](/c:/Users/Gokturk/Desktop/Repos/HAR-2453389-2414506-2526580-2526689/Hardware/ESP32/NodeInit.ino)
- [Hardware/RaspberryPi/tdma_formatted.py](/c:/Users/Gokturk/Desktop/Repos/HAR-2453389-2414506-2526580-2526689/Hardware/RaspberryPi/tdma_formatted.py)
- [Hardware/RaspberryPi/rfcommstarter.sh](/c:/Users/Gokturk/Desktop/Repos/HAR-2453389-2414506-2526580-2526689/Hardware/RaspberryPi/rfcommstarter.sh)

## Target Architecture

The intended runtime is:

1. ESP32 nodes sample IMU data continuously at 25 Hz.
2. ESP32 nodes expose a BLE service with:
   - control characteristic: write-with-response
   - stream characteristic: notify
3. Raspberry Pi connects to every ESP32 with Bleak.
4. Pi sends sync packets and receives packetized sensor batches.
5. Pi resamples aligned 3-second windows and calls the backend `/predict`.
6. Backend stores live ESP status and current label.
7. Mobile app reads status from backend and shows a real dashboard.

The phone does **not** manage Bluetooth connections directly in this design.

## Hardware You Need

- Raspberry Pi 5 or equivalent Linux machine with Bluetooth
- 1 to 7 ESP32 boards
- MPU6050 connected to each ESP32
- USB cables for flashing
- Android phone for the app
- Wi-Fi or Ethernet so phone can reach the Pi backend

## Software You Need

### On Raspberry Pi

- Raspberry Pi OS / Debian-like Linux
- Python 3.10+
- `python3-venv`
- `python3-pip`
- BlueZ / `bluetoothctl`

### On Your Development PC

- Arduino IDE 2.x
  or
- `arduino-cli`

### In Arduino IDE

Install these:

- `esp32` board support by Espressif Systems
- `NimBLE-Arduino`
- `Adafruit MPU6050`
- `Adafruit Unified Sensor`
- `Adafruit BusIO`

## Step 1: Prepare the Raspberry Pi

Open a terminal on the Pi:

```bash
sudo apt update
sudo apt install -y python3-venv python3-pip bluez bluez-tools bluetooth
sudo systemctl enable bluetooth
sudo systemctl start bluetooth
sudo rfkill unblock bluetooth
bluetoothctl show
```

Expected result:

- Bluetooth controller exists
- `Powered: yes`

If `Powered: no`, run:

```bash
bluetoothctl power on
```

## Step 2: Put the Project Folder on the Pi

Copy the whole project folder onto the Pi in whatever way you normally use.

Examples:

- copy it with a USB drive
- copy it over the network
- use shared storage
- use any version-control workflow you already have

After that, open a terminal and go into the project folder.

## Step 3: Create the Python Environment for the Pi Side

From the project root:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
```

Install backend requirements:

```bash
pip install -r Hardware/RaspberryPi/HAR-backend/requirements.txt
pip install -r Hardware/RaspberryPi/requirements-ble.txt
```

Install the ML dependencies that the backend actually imports:

```bash
pip install numpy scikit-learn torch
```

Why this matters:

- `routes/activity.py` imports `torch`, `numpy`, and `sklearn`
- they are not currently listed in `Hardware/RaspberryPi/HAR-backend/requirements.txt`
- if you skip this, the backend can fail at startup or `/predict` can fail later

## Step 4: Check That the Model Files Exist

These must exist:

- [activity_recognition_model.pt](/c:/Users/Gokturk/Desktop/Repos/HAR-2453389-2414506-2526580-2526689/Hardware/RaspberryPi/model/activity_recognition_model.pt)
- [scaler.npz](/c:/Users/Gokturk/Desktop/Repos/HAR-2453389-2414506-2526580-2526689/Hardware/RaspberryPi/model/scaler.npz)

On the Pi:

```bash
ls -l Hardware/RaspberryPi/model/
```

If either file is missing, stop here and restore them first.

## Step 5: Configure the Backend

Go to backend folder:

```bash
cd Hardware/RaspberryPi/HAR-backend
```

Create `.env.local` if you do not already have one:

```bash
cat > .env.local <<'EOF'
PORT=3000
NODE_ENV=development
JWT_SECRET=change-this-secret
DB_PATH=./har.db
ADMIN_TOKEN=
EOF
```

Important:

- backend code uses `load_dotenv()`
- keep the backend port at `3000` unless you also update the app

## Step 6: Start the Backend

From:

```bash
Hardware/RaspberryPi/HAR-backend
```

run:

```bash
source ../../../.venv/bin/activate
python app.py
```

Expected output includes:

- `Database initialized`
- `Loading model...`
- `Model loaded successfully`
- `HAR Backend running on http://localhost:3000`

Quick health check in another terminal:

```bash
curl http://127.0.0.1:3000/health
```

Expected:

```json
{"status":"ok", ...}
```

## Step 7: Initialize ESP Records in the Backend

This is optional because status posts can auto-create rows, but it is cleaner to initialize them.

From another terminal:

```bash
curl -X POST http://127.0.0.1:3000/esp-devices/init \
  -H "Content-Type: application/json" \
  -d '{"count":7}'
```

Then check:

```bash
curl http://127.0.0.1:3000/esp-status
```

Expected:

- 7 ESP rows
- all initially `disconnected`

## Step 8: Update the Mobile App API URL

Right now the app uses:

- [HAR-app/apis/api_url.ts](/c:/Users/Gokturk/Desktop/Repos/HAR-2453389-2414506-2526580-2526689/HAR-app/apis/api_url.ts)

and it currently points to:

```ts
export const API_URL = "http://localhost:3000";
```

That only works if the app runs on the same machine as the backend.

For a real Android phone, change it to your Pi IP:

```ts
export const API_URL = "http://<PI_IP>:3000";
```

Example:

```ts
export const API_URL = "http://192.168.1.42:3000";
```

Do **not** skip this.

If you leave `localhost`, the phone will try to call itself, not the Pi.

## Step 9: Flash the BLE Firmware to Each ESP32

The new BLE sketch is:

- [Hardware/ESP32/NodeBleSoftTDMA.ino](/c:/Users/Gokturk/Desktop/Repos/HAR-2453389-2414506-2526580-2526689/Hardware/ESP32/NodeBleSoftTDMA.ino)

Before every flash, edit these lines:

```cpp
const uint8_t NODE_ID = 4;
const char* DEVICE_NAME = "ESP32_NODE_4";
```

For each board:

1. Set `NODE_ID` to the correct node number
2. Set `DEVICE_NAME` to match it
3. Flash the board
4. Repeat for the next board

Recommended mapping:

- node 1 -> `ESP32_NODE_1`
- node 2 -> `ESP32_NODE_2`
- node 3 -> `ESP32_NODE_3`
- node 4 -> `ESP32_NODE_4`
- node 5 -> `ESP32_NODE_5`
- node 6 -> `ESP32_NODE_6`
- node 7 -> `ESP32_NODE_7`

### Wiring Assumption

This sketch expects:

- SDA = GPIO 21
- SCL = GPIO 22
- MPU6050 on I2C address `0x68`

If your wiring differs, edit:

```cpp
const int SDA_PIN = 21;
const int SCL_PIN = 22;
```

### Arduino IDE Settings

Typical safe settings:

- Board: your ESP32 board model
- Upload Speed: `921600` or `460800`
- Partition Scheme: default is fine
- CPU Frequency: default is fine

### Serial Monitor Check

After flashing, open Serial Monitor at `115200`.

Expected output:

- `BLE soft-TDMA node ready: ESP32_NODE_X`
- `Boot ID: ...`

If you get `Failed to find MPU6050!`, fix the sensor wiring before going further.

## Step 10: Discover Real BLE MAC Addresses

The registry file is:

- [Hardware/RaspberryPi/ble_node_registry.json](/c:/Users/Gokturk/Desktop/Repos/HAR-2453389-2414506-2526580-2526689/Hardware/RaspberryPi/ble_node_registry.json)

You must make sure:

- `id`
- `name`
- `mac`

all match the real devices.

On the Pi:

```bash
bluetoothctl
scan on
```

Wait until you see `ESP32_NODE_1`, `ESP32_NODE_2`, etc.

Then:

```bash
devices
```

Copy the MAC addresses into:

```json
Hardware/RaspberryPi/ble_node_registry.json
```

Rule:

- `ESP32_NODE_1` must be the MAC of node 1
- `ESP32_NODE_2` must be the MAC of node 2
- and so on

If the registry is wrong, the hub will connect to the wrong device or fail to connect.

## Step 11: Run the BLE Mock First

Before touching real hardware, test the software flow:

From the project root on the Pi:

```bash
source .venv/bin/activate
python Hardware/RaspberryPi/tdma_ble_mock.py
```

If backend is running, you should see:

- mock dashboard updates
- `/predict` calls
- backend ESP statuses updating

If you only want dry-run mode:

```bash
MOCK_SEND_TO_BACKEND=0 python Hardware/RaspberryPi/tdma_ble_mock.py
```

This step checks the transport shape without real BLE devices.

## Step 12: Run the Real BLE Hub

From the project root on the Pi:

```bash
source .venv/bin/activate
python Hardware/RaspberryPi/tdma_ble_hub.py
```

To restrict to a subset of nodes:

```bash
HAR_ACTIVE_NODES=1,2,3 python Hardware/RaspberryPi/tdma_ble_hub.py
```

Expected terminal behavior:

- nodes move through `joining`
- then `synced`
- then `streaming`
- sensor dashboard starts filling
- prediction lines appear

## Step 13: Start the Mobile App

From:

```bash
HAR-app
```

run:

```bash
npm install
npx expo start
```

Then:

1. Open the app on Android
2. Login or register
3. Open the Connect tab

Expected:

- you see the new dashboard
- each ESP card shows state, transport, last seen, sequence, missed packets
- the page refreshes periodically

## Step 14: Exact Startup Order for Real Use

Use this order every time:

1. Power on Raspberry Pi
2. Make sure Bluetooth is powered on
3. Start backend
4. Power on ESP32 nodes
5. Confirm registry MACs are still correct
6. Start BLE hub
7. Wait until nodes become `streaming`
8. Start mobile app
9. Open Connect tab and verify all nodes

Do not run these at the same time as the BLE hub:

- `tdma_formatted.py`
- `tdma_hub.py`
- any other script that tries to use the same ESP nodes

Also do not run the classic RFCOMM path and BLE path against the same boards at the same time.

## Step 15: How to Know It Really Works

You should not call it done until these pass.

### Minimum Software Checks

Run these from the project root:

```bash
python -m unittest Hardware/RaspberryPi/tests/test_tdma_ble_transport.py
```

From:

```bash
Hardware/RaspberryPi/HAR-backend
```

run:

```bash
python -m unittest discover -s tests
```

From:

```bash
HAR-app
```

run:

```bash
npx tsc --noEmit
```

### Minimum Hardware Checks

#### 1-node check

- start only one node
- run hub for 10 minutes
- make sure it stays `streaming`
- missed packets should stay at or near zero
- app should show real updates

#### 7-node check

- power on all 7 nodes
- run the hub for 10 minutes
- check dashboard and backend
- prediction should continue after warmup
- no node should flap constantly between `streaming` and `disconnected`

#### Stale/disconnect behavior

While hub is running:

1. turn off one ESP32
2. check backend/app

Expected:

- around 2 seconds: node becomes `stale`
- around 5 seconds: node becomes `disconnected`

Then power it on again.

Expected:

- it returns through `joining`
- then `synced`
- then `streaming`

#### Boot-ID reset behavior

Power-cycle one node while the hub is running.

Expected:

- node reconnects cleanly
- old sequence state does not corrupt the new stream

## Step 16: Useful API Checks

### View all ESP statuses

```bash
curl http://<PI_IP>:3000/esp-status
```

### View one ESP status

```bash
curl "http://<PI_IP>:3000/esp-status?id=4"
```

Expected fields now include:

- `id`
- `isConnected`
- `transport`
- `state`
- `lastSeenMs`
- `lastSeenAt`
- `lastSeq`
- `missedPackets`
- `bootId`
- `firmwareVersion`
- `lastError`

## Step 17: Troubleshooting

### Backend does not start

Check:

```bash
source .venv/bin/activate
python Hardware/RaspberryPi/HAR-backend/app.py
```

If it fails on imports:

```bash
pip install -r Hardware/RaspberryPi/HAR-backend/requirements.txt
pip install -r Hardware/RaspberryPi/requirements-ble.txt
pip install numpy scikit-learn torch
```

### BLE hub says `bleak is not installed`

Run:

```bash
pip install -r Hardware/RaspberryPi/requirements-ble.txt
```

### ESP32 does not appear in `bluetoothctl`

Check:

- board is powered
- firmware flashed correctly
- correct `DEVICE_NAME`
- BLE advertising restarted after boot

Use Serial Monitor and confirm the sketch booted.

### ESP32 appears, but hub cannot connect

Check:

- MAC in `ble_node_registry.json` is correct
- no other process is already connected to that node
- Pi Bluetooth is powered on

You can rescan:

```bash
bluetoothctl
scan on
```

### App cannot talk to backend

Most common cause:

- `HAR-app/apis/api_url.ts` still points to `localhost`

Fix it to:

```ts
export const API_URL = "http://<PI_IP>:3000";
```

### Node always becomes stale

Check:

- BLE signal quality
- ESP32 power stability
- Pi Bluetooth interference
- whether the node is too far away

Also try:

- run Pi on Ethernet instead of Wi-Fi
- move crowded 2.4 GHz devices away
- test with fewer nodes first

### Prediction is not working

Check:

- backend is running
- model files exist
- hub dashboard is receiving real samples
- `/predict` is not returning errors in backend logs

## Step 18: Fallback Plan

If BLE is not stable yet and you need a temporary demo path:

1. keep using [NodeInit.ino](/c:/Users/Gokturk/Desktop/Repos/HAR-2453389-2414506-2526580-2526689/Hardware/ESP32/NodeInit.ino)
2. run [rfcommstarter.sh](/c:/Users/Gokturk/Desktop/Repos/HAR-2453389-2414506-2526580-2526689/Hardware/RaspberryPi/rfcommstarter.sh)
3. run [tdma_formatted.py](/c:/Users/Gokturk/Desktop/Repos/HAR-2453389-2414506-2526580-2526689/Hardware/RaspberryPi/tdma_formatted.py)

That is the old path.

Do not mix the old path and new BLE path for the same session.

## Step 19: Final Checklist

Before saying the system is ready, confirm all of these:

- backend starts with no import errors
- `/health` works
- `/esp-status` works
- app `API_URL` points to the Pi IP
- every ESP32 has correct `NODE_ID` and `DEVICE_NAME`
- `ble_node_registry.json` has correct MAC addresses
- BLE mock runs
- real BLE hub runs
- 1-node bench test passes
- 7-node bench test passes
- stale/disconnect timing behaves correctly
- reconnect after power-cycle works

## One More Important Note

If you want this to be even safer for teammates, the next improvement should be:

1. add missing ML packages directly into `Hardware/RaspberryPi/HAR-backend/requirements.txt`
2. add a compile/run script for the Pi hub
3. add an environment-based API URL for the mobile app instead of hardcoding it
4. create one firmware folder per node or parameterize `NODE_ID` at build time

That would reduce manual mistakes a lot.

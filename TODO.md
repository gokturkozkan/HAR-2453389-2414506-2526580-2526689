# HAR System Runbook

This file is the practical bring-up checklist for the current repo.

It is written for the system as it exists now, not for the older Bluetooth design.

## What is integrated right now

- `ESP32 -> Raspberry Pi Wi-Fi TDMA hub -> Flask backend -> mobile app` is the main working path.
- Unity is still a separate Python bridge flow.
- Unity is **not** automatically fed by the backend `/label` endpoint yet.
- If you want Unity movement right now, you must run the Unity Python bridge flow described below.

## Internal default ports

You normally should not change these unless you have a reason.

- Backend HTTP: `3000`
- ESP32 SYNC UDP: `39000`
- ESP32 DATA UDP: `39001`
- Unity bridge TCP: `5005`
- Unity bridge discovery UDP: `5006`

## Important truth before you start

- The checked-in backend file [`Hardware/RaspberryPi/HAR-backend/.env`](./Hardware/RaspberryPi/HAR-backend/.env) currently uses `PORT=5000`.
- The mobile app default in [`HAR-app/apis/api_url.ts`](./HAR-app/apis/api_url.ts) expects `3000`.
- The Pi setup script in [`Hardware/RaspberryPi/setup_har_wifi.sh`](./Hardware/RaspberryPi/setup_har_wifi.sh) also writes `3000`.
- To avoid confusion, set the backend to `3000` and keep the rest of the system on that same port.

## One-time setup

### 1. Prepare the Raspberry Pi

Run this on the Raspberry Pi:

```bash
sudo apt update
sudo apt install -y python3 python3-venv python3-pip avahi-daemon
```

If you want the Pi to join your Wi-Fi and generate shared config files:

```bash
cd /path/to/HAR-2453389-2414506-2526580-2526689
sudo ./Hardware/RaspberryPi/setup_har_wifi.sh \
  --ssid "YOUR_WIFI_NAME" \
  --password "YOUR_WIFI_PASSWORD" \
  --hostname har-hub
```

What this does:

- sets the Pi hostname to `har-hub`
- enables mDNS so other devices can try `har-hub.local`
- writes:
  - `Hardware/RaspberryPi/har_network.env`
  - `HAR-app/.env.local`
  - `Hardware/ESP32/NodeConfig.local.h`

### 2. Fix backend port and install backend dependencies

Go to the backend folder on the Pi:

```bash
cd /path/to/HAR-2453389-2414506-2526580-2526689/Hardware/RaspberryPi/HAR-backend
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt
pip install numpy scikit-learn torch
```

Then edit [`Hardware/RaspberryPi/HAR-backend/.env`](./Hardware/RaspberryPi/HAR-backend/.env) so it contains at least:

```env
PORT=3000
DB_PATH=./har.db
NODE_ENV=development
```

Notes:

- The backend code loads `.env`, not `.env.local`.
- `requirements.txt` currently does not include the ML packages needed by `routes/activity.py`, so the extra `pip install` above is required.
- The model files must exist here:
  - `Hardware/RaspberryPi/model/activity_recognition_model.pt`
  - `Hardware/RaspberryPi/model/scaler.npz`

### 3. Prepare the mobile app

On the machine where you will run the Expo app:

```bash
cd /path/to/HAR-2453389-2414506-2526580-2526689/HAR-app
npm install
```

If the Pi setup script did not generate `HAR-app/.env.local` on this same machine, create it manually:

```env
EXPO_PUBLIC_HAR_BACKEND_PROTOCOL=http
EXPO_PUBLIC_HAR_HUB_HOST=har-hub.local
EXPO_PUBLIC_HAR_BACKEND_PORT=3000
```

If `har-hub.local` does not resolve on your phone, use a static Pi IP instead:

```env
EXPO_PUBLIC_API_URL=http://192.168.1.50:3000
```

### 4. Prepare the ESP32 firmware

On the machine you use to flash the boards:

- install Arduino IDE
- install the ESP32 board package by Espressif
- install:
  - `Adafruit MPU6050`
  - `Adafruit Unified Sensor`

If the Pi setup script did not generate `Hardware/ESP32/NodeConfig.local.h` on this same machine, create it manually.

Use this as the template:

```cpp
#pragma once

#define HAR_WIFI_SSID "YOUR_WIFI_NAME"
#define HAR_WIFI_PASSWORD "YOUR_WIFI_PASSWORD"
#define HAR_WIFI_COUNTRY "CY"
#define HAR_HUB_HOSTNAME "har-hub.local"
#define HAR_HUB_IP_1 192
#define HAR_HUB_IP_2 168
#define HAR_HUB_IP_3 1
#define HAR_HUB_IP_4 50
#define HAR_HUB_SYNC_PORT 39000
#define HAR_HUB_DATA_PORT 39001

#define HAR_NODE_ID 1
#define HAR_DEVICE_HOSTNAME "har-node-1"
```

Before each flash:

- change `HAR_NODE_ID`
- change `HAR_DEVICE_HOSTNAME`

Example node identities:

- node 1 -> `HAR_NODE_ID 1`, `har-node-1`
- node 2 -> `HAR_NODE_ID 2`, `har-node-2`
- node 3 -> `HAR_NODE_ID 3`, `har-node-3`

Do **not** flash multiple boards with the same node ID.

Open [`Hardware/ESP32/NodeInit.ino`](./Hardware/ESP32/NodeInit.ino), select the correct board and COM port, then upload one board at a time.

Recommended network note:

- Put all ESP32 boards on a stable `2.4 GHz` Wi-Fi network.

### 5. Prepare Unity if you want the Unity demo

Open the Unity project with:

- Unity `6000.0.60f1`

Important limitation:

- Unity currently reads `Unity/Python/unity_commands.log` through [`Unity/Assets/LabelDataReader.cs`](./Unity/Assets/LabelDataReader.cs).
- That log is produced by [`Unity/Python/bridge_server.py`](./Unity/Python/bridge_server.py).
- The backend `/label` route is not automatically forwarded into Unity yet.

So Unity is a separate demo/control path for now, not a full automatic backend subscriber.

## Exact run order every time

Run the system in this order.

### 1. Start the backend on the Pi

Terminal 1 on the Pi:

```bash
cd /path/to/HAR-2453389-2414506-2526580-2526689/Hardware/RaspberryPi/HAR-backend
source .venv/bin/activate
python app.py
```

What success looks like:

- prints `Database initialized`
- prints `Loading model...`
- prints the backend URL on port `3000`

Quick check:

```bash
curl http://127.0.0.1:3000/health
```

### 2. Start the Wi-Fi TDMA hub on the Pi

Terminal 2 on the Pi:

```bash
cd /path/to/HAR-2453389-2414506-2526580-2526689/Hardware/RaspberryPi
source ./har_network.env
export HAR_BACKEND_URL="http://127.0.0.1:3000"
export HAR_ACTIVE_NODES="1,2,3,4,5,6,7"
python tdma_formatted.py
```

What success looks like:

- prints `Using nodes: [1, 2, 3, 4, 5, 6, 7]`
- prints `Listening for HELLO/DATA on UDP 39001`
- prints `Broadcasting SYNC on 255.255.255.255:39000`

Notes:

- `HAR_ACTIVE_NODES` is optional, but setting it removes ambiguity.
- The hub starts the ESP device rows automatically by posting status snapshots to the backend.

### 3. Power on the ESP32 nodes

Power on or reset the flashed nodes after the hub is already running.

What success looks like on the serial monitor:

- Wi-Fi connect message
- hub hostname resolved or fallback IP used
- `HELLO` messages
- `SYNC` messages
- `DATA` messages

What success looks like on the Pi hub terminal:

- `HELLO` lines with node IDs
- status changes to `joining`, `synced`, then `streaming`
- prediction messages from `/predict`

### 4. Start the mobile app

On the Expo machine:

```bash
cd /path/to/HAR-2453389-2414506-2526580-2526689/HAR-app
npx expo start
```

Or:

```bash
npx expo start --android
```

Requirements:

- phone and Pi must be on the same Wi-Fi
- if you use `har-hub.local`, your phone must resolve mDNS correctly
- if it does not, use `EXPO_PUBLIC_API_URL=http://<PI_IP>:3000` in `HAR-app/.env.local`

What success looks like:

- the connection screen loads
- nodes appear in the table
- states move to `streaming` as sensors come online

### 5. Optional: start the Unity demo flow

This is only for the current Unity bridge path.

Open the Unity project and load the scene you want.

Then:

1. Make sure the Unity machine is on the same Wi-Fi.
2. Make sure Python is available on that machine.
3. In Unity, use the `PairingUIController` UI to enter the pairing code shown by the remote controller.
4. Start the bridge from Unity.

On the machine where you want to send labels to Unity:

```bash
cd /path/to/HAR-2453389-2414506-2526580-2526689/Unity/Python
python remote_controller.py
```

Then:

1. The script shows a pairing code.
2. Enter that code into the Unity pairing UI.
3. Press connect in Unity.
4. Press Enter in the remote controller terminal.
5. Send labels manually.

Current Unity animation labels are effectively:

- `walk` or `Walk`
- `idle` or `Idle`
- `sit` or `Sit`

Do not expect `walking`, `standing`, `sitting`, `lying` from the backend to animate Unity automatically yet.

## Recommended real-world startup sequence

If you want the cleanest bring-up:

1. Make sure the Pi is on Wi-Fi and reachable.
2. Start the Flask backend.
3. Start the TDMA hub.
4. Power on the ESP32 nodes.
5. Confirm `/health` works.
6. Confirm nodes appear as `streaming` in the mobile app.
7. Only then bring up Unity if you want the separate Unity bridge demo.

## Smoke test checklist

- Pi answers:

```bash
curl http://127.0.0.1:3000/health
```

- Hub prints `HELLO` for each node.
- Hub prints prediction messages.
- Mobile app fetches `GET /esp` and shows rows.
- Mobile app connection screen shows node states instead of an empty list.
- ESP serial monitor shows Wi-Fi connected and `SYNC`.

## If something is wrong

### Mobile app cannot reach the backend

Do this:

- confirm backend is really on `3000`
- confirm phone and Pi are on the same Wi-Fi
- if `har-hub.local` fails, use a static Pi IP in `HAR-app/.env.local`
- restart Expo after changing `.env.local`

### Hub cannot talk to backend

Do this:

- confirm backend is running first
- make sure `HAR_BACKEND_URL=http://127.0.0.1:3000` is exported before running `tdma_formatted.py`

### ESP nodes never connect

Do this:

- confirm `HAR_WIFI_SSID` and `HAR_WIFI_PASSWORD` are correct
- confirm each board has a unique `HAR_NODE_ID`
- confirm the Pi IP fallback matches the real Pi IP if hostname resolution fails
- use a `2.4 GHz` Wi-Fi network

### Mobile app shows no ESP rows

Do this:

- start the hub before opening the app
- the hub posts initial status rows automatically
- if needed, restart the app after the hub is running

### Unity does not react

Do this:

- remember Unity is not connected to backend labels yet
- make sure `bridge_server.py` is actually started by Unity
- make sure `remote_controller.py` successfully connects
- send `walk`, `idle`, or `sit`

## Current limitations you should know

- Unity is not automatically subscribed to backend labels.
- The Pi setup script centralizes config, but it does not start backend and hub services for you.
- The same generated ESP config file is not magically copied to every machine; if you flash from another computer, recreate `NodeConfig.local.h` there too.
- The backend dependencies in `requirements.txt` are incomplete for ML inference, so install `numpy`, `scikit-learn`, and `torch` explicitly.

## Minimum “works correctly” target

The system is in a good state when all of these are true:

- backend is running on `3000`
- hub is broadcasting sync and receiving data
- every ESP32 has a unique node ID
- mobile app can reach the backend from the same Wi-Fi
- nodes show `streaming`
- predictions appear in the Pi hub console

That is the current full-path definition of “running correctly” for this repo.

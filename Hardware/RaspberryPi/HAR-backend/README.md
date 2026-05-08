# HAR Backend

Backend server for the HAR (Human Activity Recognition) mobile application.

Built with Flask (Python).

## Current Run Steps

From the Raspberry Pi project root:

```bash
cd /home/serene/3005/HAR-2453389-2414506-2526580-2526689-server-fixing/Hardware/RaspberryPi/HAR-backend
source .venv/bin/activate
pip install -r requirements.txt
python app.py
```

In another terminal, start the sensor hub:

```bash
cd /home/serene/3005/HAR-2453389-2414506-2526580-2526689-server-fixing/Hardware/RaspberryPi
python tdma_hub.py
```

Or use the Bluetooth GUI hub:

```bash
cd /home/serene/3005/HAR-2453389-2414506-2526580-2526689-server-fixing/Hardware/RaspberryPi
python tdma_hub_gui.py
```

In the GUI, connect or reconnect Node 1, Node 2, and Node 3 individually. The serial connection stays open after the first probe. Full polling and prediction only start after pressing `Start Receiving Data`.

For a mock sensor run instead of real serial devices:

```bash
cd /home/serene/3005/HAR-2453389-2414506-2526580-2526689-server-fixing/Hardware/RaspberryPi
HAR_BACKEND_URL=http://127.0.0.1:3000 MOCK_RUN_SECONDS=60 python tdma_formatted_mock.py
```

The PAMAP2 backend expects `windows_by_node` with nodes `1`, `2`, and `3`, each containing 200 readings with `ax`, `ay`, `az`, `gx`, `gy`, `gz`, `mx`, `my`, and `mz`.

Sensor payloads sent to `/predict` are saved as JSON Lines at:

```bash
HAR-backend/logs/sensor_readings.jsonl
```

To inspect the latest entries:

```bash
tail -n 5 logs/sensor_readings.jsonl
```

Set `SENSOR_LOG_PATH=/some/path/sensor_readings.jsonl` before `python app.py` to write the debug log somewhere else.

## Features

- User authentication (login/register) with JWT tokens
- ESP device status monitoring
- User session management
- SQLite database for persistence
- Admin dashboard for monitoring

## Setup

### Prerequisites
- Python 3.8+
- pip

### Installation

1. Navigate to the backend directory:
```bash
cd HAR-backend
```

2. Create a virtual environment (optional but recommended):
```bash
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

3. Install dependencies:
```bash
pip install -r requirements.txt
```

4. Create a `.env` file (copy from .env example):
```bash
cp .env .env.local
```

5. Update `.env.local` with your configuration:
```
PORT=3000
NODE_ENV=development
JWT_SECRET=your-secure-secret-key
DB_PATH=./har.db
ADMIN_TOKEN=
```

## Running the Server

### Development Mode
```bash
python app.py
```

The server will start on `http://localhost:3000`

### Production Mode
Set `NODE_ENV=production` in `.env` file before running.

## API Endpoints

### Authentication
- `POST /register` - Register a new user
- `POST /login` - Login with credentials

### ESP Devices
- `GET /esp` - Get list of ESP device IDs
- `GET /esp-status` - Get status of all devices
- `GET /esp-status?id=<device_id>` - Get status of specific device
- `POST /esp-status/<device_id>` - Update device status

### User Management
- `POST /user/update` - Update user credentials

### Labels
- `GET /label` - Get current label and image
- `POST /label` - Update label

### Admin
- `GET /admin` - Admin dashboard
- `GET /admin/users.json` - Get all users (requires ADMIN_TOKEN)
- `GET /admin/esp-devices.json` - Get all ESP devices (requires ADMIN_TOKEN)

## Environment Variables

- `PORT` - Server port (default: 3000)
- `NODE_ENV` - Environment mode (development/production)
- `JWT_SECRET` - Secret key for JWT tokens
- `DB_PATH` - Path to SQLite database file
- `ADMIN_TOKEN` - Optional token to protect admin endpoints

## Database

The application uses SQLite for data persistence. The database file (`har.db`) is created automatically on first run.

### Tables
- `users` - User accounts with hashed passwords
- `esp_devices` - Connected ESP device information
- `labels` - Current labels for activity recognition
- `unity_images` - Reference images from mock Unity data

```bash
npm run build
npm start
```

## API Endpoints

### Authentication

#### Register
- **POST** `/register`
- Request body:
```json
{
  "credentials": {
    "username": "user@example.com",
    "password": "password123"
  }
}
```
- Response:
```json
{
  "token": "jwt_token",
  "user": {
    "id": "user_id",
    "username": "user@example.com"
  }
}
```

#### Login
- **POST** `/login`
- Request body:
```json
{
  "credentials": {
    "username": "user@example.com",
    "password": "password123"
  }
}
```
- Response:
```json
{
  "token": "jwt_token",
  "user": {
    "id": "user_id",
    "username": "user@example.com"
  }
}
```

### ESP Devices

#### Get ESP Status
- **GET** `/esp-status`
- Authorization: Bearer token (optional)
- Response:
```json
[
  {
    "id": 1,
    "isConnected": true
  },
  {
    "id": 2,
    "isConnected": false
  }
]
```

## Project Structure

```
HAR-backend/
├── app.py                 # Flask app setup
├── database.py            # Database initialization
├── middleware/
│   ├── auth.py            # JWT authentication
│   └── error_handler.py   # Error handling
├── routes/
│   ├── auth.py            # Authentication routes
│   ├── esp.py             # ESP device routes
│   ├── admin.py           # Admin dashboard routes
│   ├── user.py            # User management routes
│   └── label.py           # Label management routes
├── mock-Unity/            # Mock image data
├── requirements.txt       # Python dependencies
├── .env                   # Environment variables
└── README.md              # This file
```

## License

This project is part of the HAR system.
│   │   └── errorHandler.ts # Error handling middleware
│   ├── routes/
│   │   ├── auth.ts        # Authentication routes
│   │   └── esp.ts         # ESP device routes
│   ├── controllers/
│   │   ├── authController.ts
│   │   └── espController.ts
│   └── types/
│       └── index.ts       # TypeScript type definitions
├── package.json
├── tsconfig.json
├── .env.example
└── README.md
```

## Environment Variables

- `PORT`: Server port (default: 3000)
- `NODE_ENV`: Environment mode (development/production)
- `JWT_SECRET`: Secret key for signing JWT tokens
- `DB_PATH`: Path to SQLite database file

## Database Schema

### Users Table
```sql
CREATE TABLE users (
  id TEXT PRIMARY KEY,
  username TEXT UNIQUE NOT NULL,
  password TEXT NOT NULL,
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);
```

### ESP Devices Table
```sql
CREATE TABLE esp_devices (
  id INTEGER PRIMARY KEY,
  is_connected BOOLEAN DEFAULT 0,
  last_heartbeat DATETIME,
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);
```

## Security Notes

- Always use a strong JWT_SECRET in production
- Change the default JWT_SECRET in `.env`
- Passwords are hashed using bcryptjs
- HTTPS should be enabled in production
- CORS is configured for the mobile app

## License

MIT

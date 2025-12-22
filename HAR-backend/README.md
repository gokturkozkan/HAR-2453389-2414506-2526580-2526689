# HAR Backend

Backend server for the HAR (Human Activity Recognition) mobile application.

## Features

- User authentication (login/register) with JWT tokens
- ESP device status monitoring
- User session management
- SQLite database for persistence

## Setup

### Prerequisites
- Node.js 18+ 
- npm or yarn

### Installation

1. Clone the repository and navigate to the backend directory:
```bash
cd HAR-backend
```

2. Install dependencies:
```bash
npm install
```

3. Create a `.env` file based on `.env.example`:
```bash
cp .env.example .env
```

4. Update `.env` with your configuration:
```
PORT=3000
NODE_ENV=development
JWT_SECRET=your-secure-secret-key
DB_PATH=./har.db
```

## Running the Server

### Development Mode
```bash
npm run dev
```

### Production Build
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
├── src/
│   ├── server.ts          # Express app setup
│   ├── database.ts        # Database initialization
│   ├── middleware/
│   │   ├── auth.ts        # JWT authentication middleware
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

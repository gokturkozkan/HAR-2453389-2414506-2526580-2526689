export interface User {
  id: string;
  username: string;
  password?: string;
  created_at?: string;
}

export interface EspDevice {
  id: number;
  isConnected: boolean;
  last_heartbeat?: string;
}

export interface LoginRequest {
  credentials: {
    username: string;
    password: string;
  };
}

export interface AuthResponse {
  token: string;
  user: {
    id: string;
    username: string;
  };
}

export interface AuthRequest extends Express.Request {
  user?: {
    id: string;
    username: string;
  };
}

declare global {
  namespace Express {
    interface Request {
      user?: {
        id: string;
        username: string;
      };
    }
  }
}

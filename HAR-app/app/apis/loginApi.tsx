
import { API_URL } from "./api_url";

export interface LoginCredentials {
  username: string;
  password: string;
}

export interface LoginResponse {
  token: string;
  user: {
    id: string;
    username: string;
  };
}

export const loginApi = () => {

  const login = async (credentials: LoginCredentials) => {

      const response = await fetch(`${API_URL}/login`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ credentials }),
    });

      if (!response.ok) {
        const errorData = await response.json().catch(() => null);
        throw new Error(errorData?.message || "Invalid username or password");
      }

      return response.json();
  }

  return { login };
}
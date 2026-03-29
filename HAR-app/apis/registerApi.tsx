import { API_URL } from "./api_url";

export interface RegisterCredentials {
  username: string;
  password: string;
}

export interface RegisterResponse {
  token: string;
  user: {
    id: string;
    username: string;
  };
}

export const registerApi = () => {
  const register = async (credentials: RegisterCredentials) => {
    const response = await fetch(`${API_URL}/register`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ credentials }),
    });

    if (!response.ok) {
      const errorData = await response.json().catch(() => null);
      throw new Error(errorData?.message || "Error creating account");
    }

    return response.json();
  };

  return { register };
};

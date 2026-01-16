import { API_URL } from "./api_url";

export interface userCredentials {
  username: string
}

export interface UserResponse {
  token: string;
  user: {
    id: string;
    username: string;
  };
}

export const userApi = () => {
  
  const updateUser = async (credentials: userCredentials, userId: string) => {

    const response = await fetch(`${API_URL}/user/update`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ credentials, userId }),
    })
  
      if (!response.ok) {
        const errorData = await response.json().catch(() => null);
        throw new Error(errorData?.message || "Error updating credentials");
      }

      return response.json();
  }

  return { updateUser };
}
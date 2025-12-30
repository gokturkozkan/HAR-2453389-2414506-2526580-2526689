
import { API_URL } from "./api_url";

export const labelApi = () => {
  const getLabel = async() => {
    const response = await fetch(`${API_URL}/label`, {
      method: "GET"
    });

    if (!response.ok) {
      const errorData = await response.json().catch(() => null);
      throw new Error(errorData?.message || "Error fetching label");
    }

    return response.json();
  }

  return { getLabel };
}
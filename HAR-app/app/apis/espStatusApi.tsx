
import { API_URL } from "./api_url";
import { EspStatus } from "../types/espTypes";

export const espStatusApi = () => {

  const getEspStatus = async (): Promise<EspStatus[]> => {
    const response = await fetch(`${API_URL}/esp-status`, {
      method: "GET",
    });

    if (!response.ok) {
      const errorData = await response.json().catch(() => null);
      throw new Error(errorData?.message || "Error fetching ESP status");
    }

    return response.json();
  };

  return { getEspStatus };
}
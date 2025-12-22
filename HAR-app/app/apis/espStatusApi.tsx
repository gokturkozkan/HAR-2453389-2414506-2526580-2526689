
import { API_URL } from "./api_url";
import { EspStatus, EspId } from "../types/espTypes";

export const espStatusApi = () => {

  const getEspStatus = async (id: number): Promise<EspStatus> => {
    const response = await fetch(`${API_URL}/esp-status?id=${encodeURIComponent(id)}`, {
      method: "GET",
    });

    if (!response.ok) {
      const errorData = await response.json().catch(() => null);
      throw new Error(errorData?.message || `Error fetching ESP ${id} status`);
    }

    return response.json();
  };

  const getEsp = async (): Promise<EspId[]> => {
    const response = await fetch(`${API_URL}/esp`, {
      method: "GET",
    });

    if (!response.ok) {
      const errorData = await response.json().catch(() => null);
      throw new Error(errorData?.message || "Error fetching ESPs");
    }

    return response.json();
  }


  return { getEspStatus, getEsp };
}
import { API_URL } from "./api_url";
import { EspStatus, EspId } from "../app/types/espTypes";

export const espStatusApi = () => {
  const getEspStatus = async (id: number): Promise<EspStatus> => {
    const response = await fetch(
      `${API_URL}/esp-status?id=${encodeURIComponent(id)}`,
      { method: "GET" }
    );

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

    const data = await response.json();

    return data
      .filter((esp: EspId) => [1, 2, 3].includes(esp.id))
      .sort((a: EspId, b: EspId) => a.id - b.id);
  };

  return { getEspStatus, getEsp };
};
import { API_URL } from "./api_url";

export const labelApi = () => {
  const getLabel = async () => {
    const response = await fetch(`${API_URL}/label`, {
      method: "GET",
    });

    if (!response.ok) {
      const errorData = await response.json().catch(() => null);
      throw new Error(errorData?.message || "Error fetching label");
    }

    return response.json();
  };

  const sendLabel = async (label: string, nodeId?: number | null) => {
    const payload: { label: string; node_id?: number } = { label };
    if (typeof nodeId === "number") {
      payload.node_id = nodeId;
    }

    const response = await fetch(`${API_URL}/label`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify(payload),
    });

    if (!response.ok) {
      const errorData = await response.json().catch(() => null);
      throw new Error(errorData?.message || "Error sending label");
    }

    return response.json();
  };

  return { getLabel, sendLabel };
};

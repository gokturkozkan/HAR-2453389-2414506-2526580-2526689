export interface EspStatus {
  id: number;
  isConnected: boolean | null;
  status?: string;
  detail?: string;
  name?: string;
  port?: string;
  latestLine?: string;
  updatedAt?: string;
}

export interface EspId {
  id: number;
}

export type EspCommandAction = "connect" | "disconnect" | "reconnect" | "probe";

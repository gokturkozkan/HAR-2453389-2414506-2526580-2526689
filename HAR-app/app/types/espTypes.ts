export type EspConnectionState =
  | "joining"
  | "synced"
  | "streaming"
  | "stale"
  | "disconnected";

export interface EspStatus {
  id: number;
  isConnected: boolean | null;
  transport?: string | null;
  state?: EspConnectionState | null;
  lastSeenMs?: number | null;
  lastSeenAt?: string | null;
  lastSeq?: number | null;
  missedPackets?: number | null;
  bootId?: number | null;
  firmwareVersion?: number | null;
  lastError?: string | null;
}

export interface EspId {
  id: number;
}

export type EspConnectionState =
  | "joining"
  | "synced"
  | "streaming"
  | "stale"
  | "disconnected";

export interface EspStatus {
  id: number;
  isConnected: boolean | null;
  state: EspConnectionState;
  lastSeenMs: number | null;
  lastSeq: number;
  missedPackets: number;
}

export interface EspId {
  id: number;
}

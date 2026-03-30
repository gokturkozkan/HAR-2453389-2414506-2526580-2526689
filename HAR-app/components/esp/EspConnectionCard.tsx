import React from "react";
import { View, Text, StyleSheet } from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { EspConnectionState, EspStatus } from "@/app/types/espTypes";

interface EspConnectionCardProps {
  esp: EspStatus;
}

function deriveState(esp: EspStatus): EspConnectionState {
  return esp.state ?? (esp.isConnected ? "streaming" : "disconnected");
}

function stateMeta(state: EspConnectionState) {
  switch (state) {
    case "streaming":
      return { label: "Streaming", color: "#0f766e", tint: "#ccfbf1", icon: "pulse" as const };
    case "synced":
      return { label: "Synced", color: "#1d4ed8", tint: "#dbeafe", icon: "bluetooth" as const };
    case "joining":
      return { label: "Joining", color: "#7c3aed", tint: "#ede9fe", icon: "time" as const };
    case "stale":
      return { label: "Stale", color: "#b45309", tint: "#fef3c7", icon: "alert-circle" as const };
    case "disconnected":
    default:
      return { label: "Disconnected", color: "#b91c1c", tint: "#fee2e2", icon: "close-circle" as const };
  }
}

function formatLastSeen(lastSeenMs?: number | null) {
  if (lastSeenMs == null) return "No signal yet";
  if (lastSeenMs < 1000) return `${lastSeenMs} ms ago`;
  return `${(lastSeenMs / 1000).toFixed(1)} s ago`;
}

export const EspConnectionCard: React.FC<EspConnectionCardProps> = ({ esp }) => {
  const state = deriveState(esp);
  const meta = stateMeta(state);

  const detailRows = [
    { label: "Transport", value: esp.transport ?? "unknown" },
    { label: "Last seen", value: formatLastSeen(esp.lastSeenMs) },
    { label: "Sequence", value: esp.lastSeq != null ? String(esp.lastSeq) : "0" },
    { label: "Missed packets", value: esp.missedPackets != null ? String(esp.missedPackets) : "0" },
    { label: "Boot ID", value: esp.bootId != null ? String(esp.bootId) : "n/a" },
    {
      label: "Firmware",
      value: esp.firmwareVersion != null ? `v${esp.firmwareVersion}` : "n/a",
    },
  ];

  return (
    <View style={styles.card}>
      <View style={styles.header}>
        <View style={styles.titleGroup}>
          <Text style={styles.title}>ESP {esp.id}</Text>
          <Text style={styles.subtitle}>
            {state === "streaming"
              ? "Hub is receiving live TDMA samples."
              : "Status is reported by the Raspberry Pi BLE hub."}
          </Text>
        </View>

        <View style={[styles.badge, { backgroundColor: meta.tint }]}>
          <Ionicons name={meta.icon} size={16} color={meta.color} />
          <Text style={[styles.badgeText, { color: meta.color }]}>{meta.label}</Text>
        </View>
      </View>

      <View style={styles.grid}>
        {detailRows.map((row) => (
          <View key={row.label} style={styles.metric}>
            <Text style={styles.metricLabel}>{row.label}</Text>
            <Text style={styles.metricValue}>{row.value}</Text>
          </View>
        ))}
      </View>

      {esp.lastError ? (
        <View style={styles.errorBox}>
          <Ionicons name="warning" size={16} color="#b45309" />
          <Text style={styles.errorText}>{esp.lastError}</Text>
        </View>
      ) : null}
    </View>
  );
};

const styles = StyleSheet.create({
  card: {
    width: "100%",
    maxWidth: 560,
    paddingVertical: 16,
    paddingHorizontal: 20,
    backgroundColor: "#ffffff",
    borderRadius: 18,
    borderWidth: 1,
    borderColor: "#e5e7eb",
    shadowColor: "#000",
    shadowOffset: { width: 0, height: 2 },
    shadowOpacity: 0.08,
    shadowRadius: 8,
    elevation: 2,
  },
  header: {
    flexDirection: "row",
    alignItems: "flex-start",
    justifyContent: "space-between",
    gap: 16,
  },
  titleGroup: {
    flex: 1,
    gap: 4,
  },
  title: {
    fontSize: 18,
    fontWeight: "700",
    color: "#111827",
  },
  subtitle: {
    fontSize: 13,
    lineHeight: 18,
    color: "#475569",
  },
  badge: {
    flexDirection: "row",
    alignItems: "center",
    gap: 6,
    paddingHorizontal: 10,
    paddingVertical: 8,
    borderRadius: 999,
  },
  badgeText: {
    fontSize: 13,
    fontWeight: "600",
  },
  grid: {
    marginTop: 16,
    flexDirection: "row",
    flexWrap: "wrap",
    gap: 12,
  },
  metric: {
    width: "47%",
    padding: 12,
    borderRadius: 14,
    backgroundColor: "#f8fafc",
    borderWidth: 1,
    borderColor: "#e2e8f0",
  },
  metricLabel: {
    fontSize: 12,
    color: "#64748b",
    marginBottom: 4,
    textTransform: "uppercase",
    letterSpacing: 0.3,
  },
  metricValue: {
    fontSize: 14,
    fontWeight: "600",
    color: "#0f172a",
  },
  errorBox: {
    marginTop: 16,
    flexDirection: "row",
    alignItems: "center",
    gap: 8,
    padding: 12,
    borderRadius: 14,
    backgroundColor: "#fff7ed",
    borderWidth: 1,
    borderColor: "#fed7aa",
  },
  errorText: {
    flex: 1,
    fontSize: 13,
    lineHeight: 18,
    color: "#9a3412",
  },
});

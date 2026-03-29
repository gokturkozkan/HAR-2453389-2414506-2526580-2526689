import React from "react";
import { View, Text, StyleSheet, TouchableOpacity, ActivityIndicator } from "react-native";
import { Ionicons } from "@expo/vector-icons";

import { EspStatus, EspConnectionState } from "@/app/types/espTypes";

interface EspConnectionCardProps {
  device: EspStatus;
  onRefresh?: (id: number) => void;
  loading?: boolean;
}

const STATE_META: Record<
  EspConnectionState,
  { label: string; color: string; icon: keyof typeof Ionicons.glyphMap }
> = {
  joining: { label: "Joining Wi-Fi", color: "#2563eb", icon: "wifi-outline" },
  synced: { label: "Synced", color: "#7c3aed", icon: "time-outline" },
  streaming: { label: "Streaming", color: "#16a34a", icon: "checkmark-circle" },
  stale: { label: "Stale", color: "#d97706", icon: "alert-circle-outline" },
  disconnected: { label: "Disconnected", color: "#dc2626", icon: "close-circle" },
};

function formatLastSeen(lastSeenMs: number | null) {
  if (lastSeenMs == null) return "No data yet";
  if (lastSeenMs < 1000) return `${lastSeenMs} ms ago`;
  return `${(lastSeenMs / 1000).toFixed(1)} s ago`;
}

export const EspConnectionCard: React.FC<EspConnectionCardProps> = ({
  device,
  onRefresh,
  loading,
}) => {
  const meta = STATE_META[device.state];

  return (
    <View style={styles.card}>
      <View style={styles.headerRow}>
        <Text style={styles.title}>ESP {device.id}</Text>
        <View style={[styles.badge, { backgroundColor: `${meta.color}18` }]}>
          <Ionicons name={meta.icon} size={16} color={meta.color} />
          <Text style={[styles.badgeText, { color: meta.color }]}>{meta.label}</Text>
        </View>
      </View>

      <View style={styles.metricsRow}>
        <View style={styles.metric}>
          <Text style={styles.metricLabel}>Last seen</Text>
          <Text style={styles.metricValue}>{formatLastSeen(device.lastSeenMs)}</Text>
        </View>
        <View style={styles.metric}>
          <Text style={styles.metricLabel}>Sequence</Text>
          <Text style={styles.metricValue}>{device.lastSeq}</Text>
        </View>
        <View style={styles.metric}>
          <Text style={styles.metricLabel}>Missed</Text>
          <Text style={styles.metricValue}>{device.missedPackets}</Text>
        </View>
      </View>

      <View style={styles.footerRow}>
        <Text style={styles.footerText}>
          {device.isConnected ? "Node is actively streaming." : "Tap refresh to re-check node health."}
        </Text>
        <TouchableOpacity
          onPress={() => onRefresh?.(device.id)}
          activeOpacity={0.8}
          style={[styles.actionButton, loading && styles.actionButtonDisabled]}
          disabled={loading}
        >
          {loading ? (
            <ActivityIndicator color="white" size="small" />
          ) : (
            <>
              <Ionicons name="refresh" size={16} color="white" />
              <Text style={styles.actionText}>Refresh</Text>
            </>
          )}
        </TouchableOpacity>
      </View>
    </View>
  );
};

const styles = StyleSheet.create({
  card: {
    width: "100%",
    maxWidth: 540,
    paddingVertical: 16,
    paddingHorizontal: 18,
    backgroundColor: "#ffffff",
    borderRadius: 16,
    borderWidth: 1,
    borderColor: "#e5e7eb",
    shadowColor: "#000",
    shadowOffset: { width: 0, height: 2 },
    shadowOpacity: 0.1,
    shadowRadius: 6,
    elevation: 3,
    gap: 14,
  },
  headerRow: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    gap: 12,
  },
  title: {
    fontSize: 18,
    fontWeight: "700",
    color: "#0f172a",
  },
  badge: {
    flexDirection: "row",
    alignItems: "center",
    gap: 6,
    paddingVertical: 6,
    paddingHorizontal: 10,
    borderRadius: 999,
  },
  badgeText: {
    fontSize: 12,
    fontWeight: "700",
  },
  metricsRow: {
    flexDirection: "row",
    gap: 12,
  },
  metric: {
    flex: 1,
    backgroundColor: "#f8fafc",
    borderRadius: 12,
    paddingVertical: 10,
    paddingHorizontal: 12,
    gap: 4,
  },
  metricLabel: {
    fontSize: 12,
    color: "#64748b",
    fontWeight: "600",
  },
  metricValue: {
    fontSize: 14,
    color: "#0f172a",
    fontWeight: "700",
  },
  footerRow: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    gap: 12,
  },
  footerText: {
    flex: 1,
    fontSize: 13,
    color: "#475569",
  },
  actionButton: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "center",
    gap: 8,
    backgroundColor: "#1e293b",
    paddingVertical: 10,
    paddingHorizontal: 14,
    borderRadius: 999,
    minWidth: 108,
  },
  actionButtonDisabled: {
    opacity: 0.7,
  },
  actionText: {
    color: "white",
    fontSize: 14,
    fontWeight: "700",
  },
});

import React from "react";
import {
  View,
  Text,
  StyleSheet,
  TouchableOpacity,
  ActivityIndicator,
} from "react-native";
import { Ionicons } from "@expo/vector-icons";

interface EspConnectionCardProps {
  isConnected?: boolean | null;
  count: number;
  onConnect?: (id: number) => void;
  loading?: boolean;
}

const NODE_NAMES: Record<number, string> = {
  1: "Wrist",
  2: "Chest",
  3: "Ankle",
};

export const EspConnectionCard: React.FC<EspConnectionCardProps> = ({
  isConnected = false,
  count,
  onConnect,
  loading = false,
}) => {
  const connected = isConnected === true;
  const unknown = isConnected === null || isConnected === undefined;

  const icon = loading ? (
    <ActivityIndicator size="small" color="#2563eb" />
  ) : connected ? (
    <Ionicons name="checkmark-circle" size={38} color="#22c55e" />
  ) : unknown ? (
    <Ionicons name="help-circle" size={38} color="#94a3b8" />
  ) : (
    <Ionicons name="close-circle" size={38} color="#ef4444" />
  );

  const statusText = loading
    ? "Checking..."
    : connected
      ? "Connected"
      : unknown
        ? "Unknown"
        : "Disconnected";

  return (
    <TouchableOpacity
      onPress={() => onConnect?.(count)}
      activeOpacity={0.85}
      disabled={loading}
      style={[
        styles.card,
        connected && styles.cardConnected,
        !connected && !unknown && styles.cardDisconnected,
      ]}
    >
      <View style={styles.content}>
        <View style={styles.left}>
          <Text style={styles.title}>Node {count}</Text>
          <Text style={styles.subtitle}>{NODE_NAMES[count] ?? "Sensor"}</Text>
        </View>

        <View style={styles.iconWrapper}>{icon}</View>

        <Text
          style={[
            styles.statusText,
            connected && styles.statusConnected,
            !connected && !unknown && styles.statusDisconnected,
          ]}
        >
          {statusText}
        </Text>
      </View>
    </TouchableOpacity>
  );
};

const styles = StyleSheet.create({
  card: {
    width: "100%",
    maxWidth: 520,
    paddingVertical: 14,
    paddingHorizontal: 18,
    backgroundColor: "#ffffff",
    borderRadius: 18,
    borderWidth: 1,
    borderColor: "#e5e7eb",
    shadowColor: "#0f172a",
    shadowOffset: { width: 0, height: 6 },
    shadowOpacity: 0.08,
    shadowRadius: 12,
    elevation: 3,
  },
  cardConnected: {
    borderColor: "#bbf7d0",
    backgroundColor: "#f0fdf4",
  },
  cardDisconnected: {
    borderColor: "#fecaca",
    backgroundColor: "#fff1f2",
  },
  content: {
    flexDirection: "row",
    alignItems: "center",
    gap: 14,
  },
  left: {
    flex: 1,
  },
  title: {
    fontSize: 16,
    fontWeight: "800",
    color: "#0f172a",
  },
  subtitle: {
    marginTop: 2,
    fontSize: 13,
    color: "#64748b",
    fontWeight: "600",
  },
  iconWrapper: {
    width: 42,
    height: 42,
    alignItems: "center",
    justifyContent: "center",
  },
  statusText: {
    fontSize: 13,
    color: "#64748b",
    minWidth: 96,
    textAlign: "right",
    fontWeight: "800",
  },
  statusConnected: {
    color: "#15803d",
  },
  statusDisconnected: {
    color: "#dc2626",
  },
});
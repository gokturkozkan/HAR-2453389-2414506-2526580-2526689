import React from "react";
import {
  View,
  Text,
  StyleSheet,
  TouchableOpacity,
} from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { EspCommandAction } from "@/app/types/espTypes";

interface EspConnectionCardProps {
  isConnected?: boolean | null;
  status?: string;
  detail?: string;
  port?: string;
  count: number;
  onAction?: (id: number, action: EspCommandAction) => void;
  loadingAction?: EspCommandAction | null;
}

const NODE_NAMES: Record<number, string> = {
  1: "Wrist",
  2: "Chest",
  3: "Ankle",
};

const ACTION_LABELS: Record<EspCommandAction, string> = {
  connect: "Connect",
  disconnect: "Disconnect",
  reconnect: "Reconnect",
  probe: "Probe",
};

const LOADING_LABELS: Record<EspCommandAction, string> = {
  connect: "Connecting...",
  disconnect: "Disconnecting...",
  reconnect: "Reconnecting...",
  probe: "Probing...",
};

type IconName = React.ComponentProps<typeof Ionicons>["name"];

export const EspConnectionCard: React.FC<EspConnectionCardProps> = ({
  isConnected = false,
  status,
  detail,
  port,
  count,
  onAction,
  loadingAction = null,
}) => {
  const connected = isConnected === true;
  const unknown = isConnected === null || isConnected === undefined;
  const loading = loadingAction !== null;
  const tapReconnectEnabled = !connected && !unknown && !loading && Boolean(onAction);

  const icon = loading ? (
    <Ionicons name="refresh-circle" size={38} color="#2563eb" />
  ) : connected ? (
    <Ionicons name="checkmark-circle" size={38} color="#22c55e" />
  ) : unknown ? (
    <Ionicons name="help-circle" size={38} color="#94a3b8" />
  ) : (
    <Ionicons name="close-circle" size={38} color="#ef4444" />
  );

  const statusText = loading
    ? "Working..."
    : connected
      ? "Connected"
      : unknown
        ? "Unknown"
        : "Disconnected";
  const displayStatus = loadingAction
    ? LOADING_LABELS[loadingAction]
    : status || statusText;
  const actions: {
    action: EspCommandAction;
    label: string;
    icon: IconName;
    variant: "primary" | "secondary";
  }[] = [
    {
      action: "disconnect",
      label: ACTION_LABELS.disconnect,
      icon: "close-circle-outline",
      variant: "secondary",
    },
    {
      action: "probe",
      label: ACTION_LABELS.probe,
      icon: "pulse-outline",
      variant: "secondary",
    },
    {
      action: "reconnect",
      label: ACTION_LABELS.reconnect,
      icon: "refresh-outline",
      variant: "primary",
    },
  ];
  const mutedDetail = detail || port || NODE_NAMES[count] || "Sensor";

  return (
    <TouchableOpacity
      activeOpacity={tapReconnectEnabled ? 0.86 : 1}
      disabled={!tapReconnectEnabled}
      onPress={() => onAction?.(count, "reconnect")}
      style={[
        styles.card,
        connected && styles.cardConnected,
        !connected && !unknown && styles.cardDisconnected,
      ]}
    >
      <View style={styles.content}>
        <View style={styles.left}>
          <Text style={styles.title}>Node {count}</Text>
          <Text style={styles.subtitle}>{mutedDetail}</Text>
        </View>

        <View style={styles.iconWrapper}>{icon}</View>

        <Text
          style={[
            styles.statusText,
            connected && styles.statusConnected,
            !connected && !unknown && styles.statusDisconnected,
          ]}
        >
          {displayStatus}
        </Text>
      </View>

      {connected ? (
        <View style={styles.actionRow}>
          {actions.map((item) => {
            const primary = item.variant === "primary";

            return (
              <TouchableOpacity
                key={item.action}
                activeOpacity={0.85}
                disabled={loading || !onAction}
                onPress={() => onAction?.(count, item.action)}
                style={[
                  styles.actionButton,
                  primary ? styles.actionPrimary : styles.actionSecondary,
                  (loading || !onAction) && styles.actionDisabled,
                ]}
              >
                <Ionicons
                  name={item.icon}
                  size={16}
                  color={primary ? "#ffffff" : "#2563eb"}
                />
                <Text
                  style={[
                    styles.actionText,
                    primary ? styles.actionTextPrimary : styles.actionTextSecondary,
                  ]}
                >
                  {item.label}
                </Text>
              </TouchableOpacity>
            );
          })}
        </View>
      ) : (
        <View style={[styles.tapRow, unknown && styles.tapRowDisabled]}>
          <Ionicons name="refresh-outline" size={16} color="#2563eb" />
          <Text style={styles.tapText}>
            {loading ? LOADING_LABELS[loadingAction] : "Tap node to reconnect"}
          </Text>
        </View>
      )}
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
  actionRow: {
    marginTop: 14,
    flexDirection: "row",
    flexWrap: "wrap",
    gap: 10,
  },
  actionButton: {
    minHeight: 42,
    minWidth: 132,
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "center",
    gap: 8,
    borderRadius: 999,
    paddingVertical: 10,
    paddingHorizontal: 14,
  },
  actionPrimary: {
    backgroundColor: "#2563eb",
  },
  actionSecondary: {
    backgroundColor: "#eff6ff",
    borderWidth: 1,
    borderColor: "#bfdbfe",
  },
  actionDisabled: {
    opacity: 0.55,
  },
  actionText: {
    fontSize: 13,
    fontWeight: "800",
  },
  actionTextPrimary: {
    color: "#ffffff",
  },
  actionTextSecondary: {
    color: "#2563eb",
  },
  tapRow: {
    marginTop: 14,
    minHeight: 42,
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "center",
    gap: 8,
    borderRadius: 999,
    backgroundColor: "#eff6ff",
    borderWidth: 1,
    borderColor: "#bfdbfe",
  },
  tapRowDisabled: {
    opacity: 0.55,
  },
  tapText: {
    color: "#2563eb",
    fontSize: 13,
    fontWeight: "800",
  },
});

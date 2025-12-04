import React from "react";
import { View, Text, StyleSheet } from "react-native";
import { Ionicons } from "@expo/vector-icons";

interface EspConnectionCardProps {
  isConnected?: boolean;
  count: number;
}

export const EspConnectionCard: React.FC<EspConnectionCardProps> = ({
  isConnected = false,
  count,
}) => {
  return (
    <View style={styles.card}>
      <View style={styles.content}>
        <Text style={styles.title}>ESP {count}</Text>

        <View style={styles.iconWrapper}>
          {isConnected ? (
            <Ionicons name="checkmark-circle" size={64} color="#22c55e" />
          ) : (
            <Ionicons name="reload" size={64} color="#3b82f6" style={styles.spin} />
          )}
        </View>

        <Text style={styles.statusText}>
          {isConnected ? "Connected" : "Connecting..."}
        </Text>
      </View>
    </View>
  );
};

const styles = StyleSheet.create({
  card: {
    width: 256, // ~ w-64
    padding: 24,
    backgroundColor: "#ffffff",
    borderRadius: 16,
    borderWidth: 1,
    borderColor: "#e5e7eb",
    shadowColor: "#000",
    shadowOffset: { width: 0, height: 4 },
    shadowOpacity: 0.1,
    shadowRadius: 8,
    elevation: 4,
  },
  content: {
    alignItems: "center",
    justifyContent: "center",
    gap: 16,
  },
  title: {
    fontSize: 18,
    fontWeight: "600",
    color: "#1f2933",
  },
  iconWrapper: {
    width: 64,
    height: 64,
    alignItems: "center",
    justifyContent: "center",
  },
  statusText: {
    fontSize: 14,
    color: "#4b5563",
  },
  spin: {
    transform: [{ rotate: "0deg" }],
  },
});

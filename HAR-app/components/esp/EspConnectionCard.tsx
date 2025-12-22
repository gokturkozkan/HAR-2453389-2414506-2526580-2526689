import React, { useEffect, useState } from "react";
import { View, Text, StyleSheet, TouchableOpacity, ActivityIndicator } from "react-native";
import { Ionicons } from "@expo/vector-icons";

interface EspConnectionCardProps {
  isConnected?: boolean;
  count: number;
  onConnect?: (id: number) => void;
  loading?: boolean;
}

type CardState = "idle" | "connecting" | "success" | "failed";

export const EspConnectionCard: React.FC<EspConnectionCardProps> = ({
  isConnected = false,
  count,
  onConnect,
  loading,
}) => {
  const [state, setState] = useState<CardState>("idle");

  useEffect(() => {
    if (loading) {
      setState("connecting");
    }
  }, [loading]);

  useEffect(() => {
    if (!loading && state === "connecting") {
      if (isConnected) {
        setState("success");
      } else {
        setState("failed");
      }
    }
  }, [loading, state, isConnected]);

  useEffect(() => {
    if (state === "failed") {
      const timer = setTimeout(() => setState("idle"), 2000);
      return () => clearTimeout(timer);
    }
  }, [state]);

  const renderContent = () => {
    switch (state) {
      case "connecting":
        return {
          icon: <Ionicons name="reload" size={40} color="#3b82f6" />,
          text: "Connecting...",
        };
      case "success":
        return {
          icon: <Ionicons name="checkmark-circle" size={40} color="#22c55e" />,
          text: "Connected",
        };
      case "failed":
        return {
          icon: <Ionicons name="close-circle" size={40} color="#ef4444" />,
          text: "Failed",
        };
      default:
        return null;
    }
  };

  if (state !== "idle") {
    const content = renderContent();
    return (
      <View style={styles.card}>
        <View style={styles.content}>
          <Text style={styles.title}>ESP {count}</Text>
          <View style={styles.iconWrapper}>{content?.icon}</View>
          <Text style={styles.statusText}>{content?.text}</Text>
        </View>
      </View>
    );
  }

  return (
    <TouchableOpacity
      onPress={() => {
        setState("connecting");
        onConnect?.(count);
      }}
      activeOpacity={0.8}
      style={styles.card}
    >
      <View style={styles.content}>
        <Text style={styles.title}>ESP {count}</Text>
        <View style={styles.iconWrapper}>
          <Ionicons name="enter" size={40} color="#97a5cbff" />
        </View>
        <Text style={styles.statusText}>Connect</Text>
      </View>
    </TouchableOpacity>
  );
};

const styles = StyleSheet.create({
  card: {
    width: "100%",
    maxWidth: 480,
    paddingVertical: 12,
    paddingHorizontal: 20,
    backgroundColor: "#ffffff",
    borderRadius: 12,
    borderWidth: 1,
    borderColor: "#e5e7eb",
    shadowColor: "#000",
    shadowOffset: { width: 0, height: 2 },
    shadowOpacity: 0.1,
    shadowRadius: 4,
    elevation: 2,
  },
  content: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    gap: 16,
  },
  title: {
    fontSize: 16,
    fontWeight: "600",
    color: "#1f2933",
    flex: 1,
  },
  iconWrapper: {
    width: 40,
    height: 40,
    alignItems: "center",
    justifyContent: "center",
  },
  statusText: {
    fontSize: 13,
    color: "#4b5563",
    minWidth: 80,
    textAlign: "right",
  },
  spin: {
    transform: [{ rotate: "0deg" }],
  },
});

import React, { useContext, useEffect, useMemo, useState } from "react";
import { View, StyleSheet, ActivityIndicator, Text, Pressable, ScrollView } from "react-native";
import { EspConnectionTable } from "./EspConnectionTable";
import { EspStatus } from "@/app/types/espTypes";
import { espStatusApi } from "@/apis/espStatusApi";
import { ConnectionContext } from "../../app/contexts/ConnectionContext";

const POLL_INTERVAL_MS = 3000;

function deriveState(esp: EspStatus) {
  return esp.state ?? (esp.isConnected ? "streaming" : "disconnected");
}

function areAllNodesStreaming(statuses: EspStatus[]) {
  return statuses.length > 0 && statuses.every((esp) => deriveState(esp) === "streaming");
}

function formatLastUpdated(value: Date | null) {
  if (!value) return "Waiting for first status snapshot...";
  return `Last refreshed at ${value.toLocaleTimeString()}`;
}

export default function ConnectScreen() {
  const [esps, setEsps] = useState<EspStatus[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null);
  const { getEspStatuses } = espStatusApi();
  const { setConnection } = useContext(ConnectionContext);

  const fetchEsps = async (initial: boolean = false) => {
    if (initial) setLoading(true);
    if (!initial) setRefreshing(true);
    try {
      const nextEsps = await getEspStatuses();
      setEsps(nextEsps);
      setConnection(areAllNodesStreaming(nextEsps));
      setLastUpdated(new Date());
    } catch (e) {
      console.error("Failed to fetch ESPs", e);
    } finally {
      if (initial) setLoading(false);
      if (!initial) setRefreshing(false);
    }
  };

  const summary = useMemo(() => {
    return esps.reduce(
      (acc, esp) => {
        const state = deriveState(esp);
        if (state === "streaming") acc.streaming += 1;
        else if (state === "joining" || state === "synced") acc.connecting += 1;
        else if (state === "stale") acc.stale += 1;
        else acc.disconnected += 1;
        return acc;
      },
      { streaming: 0, connecting: 0, stale: 0, disconnected: 0 }
    );
  }, [esps]);

  useEffect(() => {
    fetchEsps(true);

    const interval = setInterval(() => {
      fetchEsps(false);
    }, POLL_INTERVAL_MS);

    return () => clearInterval(interval);
  }, []);

  if (loading) {
    return (
      <View style={styles.loadingScreen}>
        <ActivityIndicator size="large" />
        <Text style={styles.loadingText}>Loading devices...</Text>
      </View>
    );
  }

  return (
    <ScrollView contentContainerStyle={styles.screen}>
      <View style={styles.hero}>
        <View style={styles.heroText}>
          <Text style={styles.title}>Bluetooth Sensor Hub</Text>
          <Text style={styles.subtitle}>
            The phone now mirrors the Raspberry Pi BLE hub status. Pairing and TDMA control happen on the Pi, not here.
          </Text>
          <Text style={styles.lastUpdated}>{formatLastUpdated(lastUpdated)}</Text>
        </View>

        <Pressable style={styles.refreshButton} onPress={() => fetchEsps(false)}>
          <Text style={styles.refreshButtonText}>
            {refreshing ? "Refreshing..." : "Refresh"}
          </Text>
        </Pressable>
      </View>

      <View style={styles.summaryRow}>
        <View style={[styles.summaryCard, { backgroundColor: "#ecfeff" }]}>
          <Text style={styles.summaryLabel}>Streaming</Text>
          <Text style={styles.summaryValue}>{summary.streaming}</Text>
        </View>
        <View style={[styles.summaryCard, { backgroundColor: "#eef2ff" }]}>
          <Text style={styles.summaryLabel}>Joining/Synced</Text>
          <Text style={styles.summaryValue}>{summary.connecting}</Text>
        </View>
        <View style={[styles.summaryCard, { backgroundColor: "#fff7ed" }]}>
          <Text style={styles.summaryLabel}>Stale</Text>
          <Text style={styles.summaryValue}>{summary.stale}</Text>
        </View>
        <View style={[styles.summaryCard, { backgroundColor: "#fef2f2" }]}>
          <Text style={styles.summaryLabel}>Disconnected</Text>
          <Text style={styles.summaryValue}>{summary.disconnected}</Text>
        </View>
      </View>

      <View style={styles.noteBox}>
        <Text style={styles.noteText}>
          `isConnected` remains compatible for older code, but the detailed state is the real source of truth for BLE health.
        </Text>
      </View>

      <View style={styles.tableContainer}>
        <EspConnectionTable esps={esps} />
      </View>
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  screen: {
    padding: 16,
    paddingBottom: 32,
  },
  loadingScreen: {
    flex: 1,
    alignItems: "center",
    justifyContent: "center",
  },
  loadingText: {
    marginTop: 8,
    fontSize: 16,
    color: "#4b5563",
  },
  hero: {
    flexDirection: "row",
    justifyContent: "space-between",
    gap: 16,
    padding: 20,
    borderRadius: 24,
    backgroundColor: "#f8fafc",
    borderWidth: 1,
    borderColor: "#e2e8f0",
  },
  heroText: {
    flex: 1,
    gap: 6,
  },
  title: {
    fontSize: 24,
    fontWeight: "800",
    color: "#0f172a",
  },
  subtitle: {
    fontSize: 14,
    lineHeight: 20,
    color: "#475569",
  },
  lastUpdated: {
    marginTop: 4,
    fontSize: 12,
    color: "#64748b",
  },
  refreshButton: {
    alignSelf: "center",
    paddingHorizontal: 16,
    paddingVertical: 12,
    borderRadius: 999,
    backgroundColor: "#0f766e",
  },
  refreshButtonText: {
    color: "#ffffff",
    fontSize: 14,
    fontWeight: "700",
  },
  summaryRow: {
    marginTop: 16,
    flexDirection: "row",
    flexWrap: "wrap",
    gap: 12,
  },
  summaryCard: {
    flexGrow: 1,
    minWidth: 140,
    padding: 16,
    borderRadius: 18,
  },
  summaryLabel: {
    fontSize: 12,
    color: "#475569",
    textTransform: "uppercase",
    letterSpacing: 0.4,
  },
  summaryValue: {
    marginTop: 6,
    fontSize: 26,
    fontWeight: "800",
    color: "#0f172a",
  },
  noteBox: {
    marginTop: 16,
    padding: 14,
    borderRadius: 16,
    backgroundColor: "#fffbeb",
    borderWidth: 1,
    borderColor: "#fde68a",
  },
  noteText: {
    fontSize: 13,
    lineHeight: 18,
    color: "#92400e",
  },
  tableContainer: {
    paddingTop: 20,
  },
});

import React, { useContext, useEffect, useMemo, useState } from "react";
import { View, StyleSheet, ActivityIndicator, Text, Pressable } from "react-native";

import { EspConnectionTable } from "./EspConnectionTable";
import { EspId, EspStatus } from "@/app/types/espTypes";
import { espStatusApi } from "@/apis/espStatusApi";
import { ConnectionContext } from "../../app/contexts/ConnectionContext";

const REFRESH_INTERVAL_MS = 3000;

function isStreaming(device: EspStatus) {
  return device.isConnected === true && device.state === "streaming";
}

export default function ConnectScreen() {
  const [esps, setEsps] = useState<EspStatus[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshingId, setRefreshingId] = useState<number | null>(null);
  const [refreshingAll, setRefreshingAll] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const { getEspStatus, getEsp } = useMemo(() => espStatusApi(), []);
  const { setConnection } = useContext(ConnectionContext);

  const fetchEsps = async (initial = false) => {
    if (initial) setLoading(true);
    if (!initial) setRefreshingAll(true);
    try {
      const devices = await getEsp();
      if (!devices || devices.length === 0) {
        setEsps([]);
        setConnection(false);
        setErrorMessage(null);
        return;
      }

      const statusResults = await Promise.allSettled(
        devices.map((device: EspId) => getEspStatus(device.id))
      );

      const nextEsps: EspStatus[] = devices.map((device: EspId, index: number) => {
        const result = statusResults[index];
        if (result.status === "fulfilled") {
          return result.value;
        }
        return {
          id: device.id,
          isConnected: false,
          state: "disconnected",
          lastSeenMs: null,
          lastSeq: 0,
          missedPackets: 0,
        };
      });

      setEsps(nextEsps);
      setConnection(nextEsps.length > 0 && nextEsps.every(isStreaming));
      setErrorMessage(null);
    } catch (error: any) {
      console.error("Failed to fetch ESPs", error);
      setErrorMessage(error?.message ?? "Unable to refresh sensor status.");
    } finally {
      if (initial) setLoading(false);
      if (!initial) setRefreshingAll(false);
    }
  };

  const refreshOne = async (id: number) => {
    setRefreshingId(id);
    try {
      const data = await getEspStatus(id);
      setEsps((previous) => {
        const updated = previous.map((esp) => (esp.id === id ? data : esp));
        setConnection(updated.length > 0 && updated.every(isStreaming));
        return updated;
      });
      setErrorMessage(null);
    } catch (error: any) {
      console.error(`Failed to refresh node ${id}`, error);
      setErrorMessage(error?.message ?? `Unable to refresh ESP ${id}.`);
    } finally {
      setRefreshingId(null);
    }
  };

  useEffect(() => {
    fetchEsps(true);
    const interval = setInterval(() => {
      fetchEsps(false);
    }, REFRESH_INTERVAL_MS);
    return () => clearInterval(interval);
  }, []);

  const streamingCount = esps.filter(isStreaming).length;

  if (loading) {
    return (
      <View style={styles.loadingScreen}>
        <ActivityIndicator size="large" />
        <Text style={styles.loadingText}>Loading device states...</Text>
      </View>
    );
  }

  return (
    <View style={styles.screen}>
      <View style={styles.header}>
        <View>
          <Text style={styles.title}>Sensor Link Monitor</Text>
          <Text style={styles.subtitle}>
            {streamingCount}/{esps.length || 0} nodes streaming
          </Text>
        </View>
        <Pressable
          style={[styles.refreshAllButton, refreshingAll && styles.refreshAllButtonDisabled]}
          onPress={() => fetchEsps(false)}
          disabled={refreshingAll}
        >
          {refreshingAll ? (
            <ActivityIndicator size="small" color="white" />
          ) : (
            <Text style={styles.refreshAllText}>Refresh all</Text>
          )}
        </Pressable>
      </View>

      <View style={styles.infoBanner}>
        <Text style={styles.infoText}>
          The app is monitoring node health reported by the Raspberry Pi hub. "Refresh" re-checks
          status, while pairing and scheduling happen on the hub.
        </Text>
      </View>

      {errorMessage ? <Text style={styles.errorText}>{errorMessage}</Text> : null}

      <View style={styles.tableContainer}>
        <EspConnectionTable esps={esps} onRefresh={refreshOne} loadingId={refreshingId} />
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  screen: {
    flex: 1,
    padding: 16,
    backgroundColor: "#f8fafc",
    gap: 16,
  },
  loadingScreen: {
    flex: 1,
    alignItems: "center",
    justifyContent: "center",
    backgroundColor: "#f8fafc",
  },
  loadingText: {
    marginTop: 8,
    fontSize: 16,
    color: "#475569",
  },
  header: {
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "center",
    gap: 12,
    paddingTop: 32,
  },
  title: {
    fontSize: 24,
    fontWeight: "800",
    color: "#0f172a",
  },
  subtitle: {
    marginTop: 4,
    fontSize: 14,
    color: "#475569",
  },
  refreshAllButton: {
    backgroundColor: "#1e293b",
    paddingVertical: 10,
    paddingHorizontal: 16,
    borderRadius: 999,
    minWidth: 108,
    alignItems: "center",
  },
  refreshAllButtonDisabled: {
    opacity: 0.75,
  },
  refreshAllText: {
    color: "white",
    fontSize: 14,
    fontWeight: "700",
  },
  infoBanner: {
    borderRadius: 14,
    padding: 14,
    backgroundColor: "#e0f2fe",
    borderWidth: 1,
    borderColor: "#bae6fd",
  },
  infoText: {
    color: "#0c4a6e",
    fontSize: 13,
    lineHeight: 20,
  },
  errorText: {
    color: "#b91c1c",
    fontSize: 13,
  },
  tableContainer: {
    flex: 1,
  },
});

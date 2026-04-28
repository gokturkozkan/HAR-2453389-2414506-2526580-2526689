import React, { useContext, useEffect, useState, useCallback, useMemo } from "react";
import {
  View,
  StyleSheet,
  ActivityIndicator,
  Text,
  useWindowDimensions,
  Pressable,
} from "react-native";
import { EspConnectionTable } from "./EspConnectionTable";
import { EspId, EspStatus } from "@/app/types/espTypes";
import { espStatusApi } from "@/apis/espStatusApi";
import { ConnectionContext } from "../../app/contexts/ConnectionContext";

const NODE_IDS = [1, 2, 3];

export default function ConnectScreen() {
  const { width } = useWindowDimensions();
  const isDesktop = width >= 768;

  const [esps, setEsps] = useState<EspStatus[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  const api = useMemo(() => espStatusApi(), []);
  const { setConnection } = useContext(ConnectionContext);

  const withTimeout = async <T,>(promise: Promise<T>, ms = 4000): Promise<T> => {
    return Promise.race([
      promise,
      new Promise<T>((_, reject) =>
        setTimeout(() => reject(new Error("Request timed out")), ms)
      ),
    ]);
  };

  const fetchEsps = useCallback(
    async (initial = false) => {
      if (initial) setLoading(true);
      else setRefreshing(true);

      try {
        setErrorMessage(null);

        const data = await withTimeout(api.getEsp(), 4000);

        const threeNodes = data
          .filter((d: EspId) => NODE_IDS.includes(d.id))
          .sort((a: EspId, b: EspId) => a.id - b.id);

        const safeNodes =
          threeNodes.length > 0
            ? threeNodes
            : NODE_IDS.map((id) => ({ id }));

        const statusResults = await Promise.allSettled(
          safeNodes.map((d: EspId) =>
            withTimeout(api.getEspStatus(d.id), 3000)
          )
        );

        const nextEsps: EspStatus[] = safeNodes.map((d: EspId, index: number) => {
          const result = statusResults[index];

          return {
            id: d.id,
            isConnected:
              result.status === "fulfilled"
                ? result.value.isConnected
                : false,
          };
        });

        setEsps(nextEsps);

        const allConnected =
          nextEsps.length === 3 &&
          nextEsps.every((esp) => esp.isConnected === true);

        setConnection(allConnected);
      } catch (e: any) {
        console.error("ESP fetch error:", e);
        setErrorMessage(e?.message || "Could not load nodes");
        setConnection(false);

        setEsps(
          NODE_IDS.map((id) => ({
            id,
            isConnected: false,
          }))
        );
      } finally {
        setLoading(false);
        setRefreshing(false);
      }
    },
    [api, setConnection]
  );

  useEffect(() => {
    fetchEsps(true);

    const interval = setInterval(() => {
      fetchEsps(false);
    }, 1000);

    return () => clearInterval(interval);
  }, [fetchEsps]);

  if (loading) {
    return (
      <View style={styles.loadingScreen}>
        <ActivityIndicator size="large" color="#2563eb" />
        <Text style={styles.loadingText}>Loading nodes...</Text>

        {errorMessage && (
          <Text style={styles.errorText}>{errorMessage}</Text>
        )}

        <Pressable style={styles.retryButton} onPress={() => fetchEsps(true)}>
          <Text style={styles.retryText}>Retry</Text>
        </Pressable>
      </View>
    );
  }

  return (
    <View style={styles.screen}>
      <View style={[styles.card, isDesktop && styles.cardDesktop]}>
        <View style={styles.header}>
          <Text style={styles.eyebrow}>Device Connection</Text>
          <Text style={styles.title}>3-Node HAR Setup</Text>
          <Text style={styles.subtitle}>
            Node 1 wrist, Node 2 chest, Node 3 ankle.
          </Text>
        </View>

        {refreshing && (
          <View style={styles.refreshRow}>
            <ActivityIndicator size="small" color="#2563eb" />
            <Text style={styles.refreshText}>Checking status...</Text>
          </View>
        )}

        {errorMessage && (
          <Text style={styles.errorText}>{errorMessage}</Text>
        )}

        <EspConnectionTable
          esps={esps}
          onConnect={(id: number) => fetchEsps(false)}
          loadingId={null}
        />

        <Pressable style={styles.retryButton} onPress={() => fetchEsps(false)}>
          <Text style={styles.retryText}>Refresh</Text>
        </Pressable>
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  screen: {
    flex: 1,
    backgroundColor: "#eef2ff",
    padding: 20,
    justifyContent: "center",
    alignItems: "center",
  },
  loadingScreen: {
    flex: 1,
    backgroundColor: "#eef2ff",
    alignItems: "center",
    justifyContent: "center",
    padding: 24,
  },
  loadingText: {
    marginTop: 10,
    fontSize: 16,
    color: "#475569",
    fontWeight: "600",
  },
  card: {
    width: "100%",
    maxWidth: 620,
    backgroundColor: "white",
    borderRadius: 28,
    padding: 22,
  },
  cardDesktop: {
    padding: 32,
  },
  header: {
    marginBottom: 20,
  },
  eyebrow: {
    fontSize: 13,
    fontWeight: "700",
    color: "#2563eb",
    textTransform: "uppercase",
    letterSpacing: 0.8,
    marginBottom: 6,
  },
  title: {
    fontSize: 28,
    fontWeight: "800",
    color: "#0f172a",
  },
  subtitle: {
    marginTop: 8,
    fontSize: 15,
    color: "#64748b",
    lineHeight: 22,
  },
  refreshRow: {
    flexDirection: "row",
    alignItems: "center",
    gap: 8,
    marginBottom: 12,
    backgroundColor: "#f8fafc",
    padding: 10,
    borderRadius: 999,
  },
  refreshText: {
    color: "#475569",
    fontWeight: "600",
  },
  errorText: {
    marginTop: 12,
    marginBottom: 12,
    color: "#dc2626",
    textAlign: "center",
    fontWeight: "600",
  },
  retryButton: {
    marginTop: 16,
    backgroundColor: "#2563eb",
    paddingVertical: 12,
    paddingHorizontal: 20,
    borderRadius: 999,
    alignItems: "center",
  },
  retryText: {
    color: "white",
    fontWeight: "800",
  },
});
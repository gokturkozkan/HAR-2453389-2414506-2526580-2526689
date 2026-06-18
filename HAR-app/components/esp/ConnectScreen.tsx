import React, {
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import {
  View,
  StyleSheet,
  Text,
  useWindowDimensions,
  Pressable,
} from "react-native";
import { EspConnectionTable } from "./EspConnectionTable";
import { EspCommandAction, EspId, EspStatus } from "@/app/types/espTypes";
import { espStatusApi } from "@/apis/espStatusApi";
import { ConnectionContext } from "../../app/contexts/ConnectionContext";

const NODE_IDS = [1, 2, 3];
const STATUS_TIMEOUT_MS = 4000;
const NODE_STATUS_TIMEOUT_MS = 3000;
const ACTION_TIMEOUT_MS: Record<EspCommandAction, number> = {
  connect: 30000,
  disconnect: 10000,
  reconnect: 35000,
  probe: 8000,
};

const RECEIVING_STATUSES = new Set([
  "open",
  "ready",
  "receiving",
  "open - no data",
  "open - unreadable",
]);

const initialNodes = (): EspStatus[] =>
  NODE_IDS.map((id) => ({
    id,
    isConnected: null,
    status: "Unknown",
  }));

const isNodeConnected = (node: EspStatus) => {
  const status = node.status?.trim().toLowerCase();

  return node.isConnected === true || Boolean(status && RECEIVING_STATUSES.has(status));
};

const withTimeout = async <T,>(promise: Promise<T>, ms: number): Promise<T> => {
  return Promise.race([
    promise,
    new Promise<T>((_, reject) =>
      setTimeout(() => reject(new Error("Request timed out")), ms)
    ),
  ]);
};

export default function ConnectScreen() {
  const { width } = useWindowDimensions();
  const isDesktop = width >= 768;

  const [esps, setEsps] = useState<EspStatus[]>(initialNodes);
  const [pendingAction, setPendingAction] = useState<{
    id: number;
    action: EspCommandAction;
  } | null>(null);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const pendingActionRef = useRef(false);

  const api = useMemo(() => espStatusApi(), []);
  const { setConnection } = useContext(ConnectionContext);

  const fetchEsps = useCallback(
    async (initial = false, force = false) => {
      if (!initial && pendingActionRef.current && !force) return;

      try {
        setErrorMessage(null);

        const data = await withTimeout(api.getEsp(), STATUS_TIMEOUT_MS);

        const threeNodes = data
          .filter((d: EspId) => NODE_IDS.includes(d.id))
          .sort((a: EspId, b: EspId) => a.id - b.id);

        const safeNodes =
          threeNodes.length > 0
            ? threeNodes
            : NODE_IDS.map((id) => ({ id }));

        const statusResults = await Promise.allSettled(
          safeNodes.map((d: EspId) =>
            withTimeout(api.getEspStatus(d.id), NODE_STATUS_TIMEOUT_MS)
          )
        );

        const nextEsps: EspStatus[] = safeNodes.map((d: EspId, index: number) => {
          const result = statusResults[index];
          const statusNode: EspStatus =
            result.status === "fulfilled"
              ? result.value
              : {
                  id: d.id,
                  isConnected: false,
                  status: "Disconnected",
                  detail: "Status request failed",
                };
          const normalizedNode = { ...statusNode, id: d.id };

          return {
            ...normalizedNode,
            isConnected: isNodeConnected(normalizedNode),
          };
        });

        setEsps(nextEsps);

        const allConnected =
          nextEsps.length === 3 &&
          nextEsps.every(isNodeConnected);

        setConnection(allConnected);
      } catch (e: any) {
        console.error("ESP fetch error:", e);
        setErrorMessage(e?.message || "Could not load nodes");
        setConnection(false);

        setEsps((current) =>
          current.map((esp) => ({
            ...esp,
            isConnected: false,
            status: "Disconnected",
            detail: e?.message || "Could not load node status",
          }))
        );
      }
    },
    [api, setConnection]
  );

  const handleNodeAction = useCallback(
    async (id: number, action: EspCommandAction) => {
      if (pendingActionRef.current) return;

      pendingActionRef.current = true;
      setPendingAction({ id, action });
      setErrorMessage(null);
      setEsps((current) =>
        current.map((esp) =>
          esp.id === id
            ? {
                ...esp,
                status: action === "reconnect" ? "Reconnecting" : esp.status,
                detail:
                  action === "reconnect"
                    ? "Closing, rebinding, opening, then requesting a sample."
                    : esp.detail,
              }
            : esp
        )
      );

      try {
        const updatedNode = await withTimeout(
          api.runEspCommand(id, action),
          ACTION_TIMEOUT_MS[action]
        );

        setEsps((current) =>
          current.map((esp) =>
            esp.id === id
              ? {
                  ...esp,
                  ...updatedNode,
                  isConnected: isNodeConnected(updatedNode),
                }
              : esp
          )
        );

        await fetchEsps(false, true);
      } catch (e: any) {
        console.error("ESP command error:", e);
        const message = e?.message || `Could not ${action} node ${id}`;

        try {
          await fetchEsps(false, true);
        } catch {
          setConnection(false);
        } finally {
          setErrorMessage(message);
        }
      } finally {
        pendingActionRef.current = false;
        setPendingAction(null);
      }
    },
    [api, fetchEsps, setConnection]
  );

  useEffect(() => {
    fetchEsps(true);

    const interval = setInterval(() => {
      fetchEsps(false);
    }, 1000);

    return () => clearInterval(interval);
  }, [fetchEsps]);

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

        {errorMessage && (
          <Text style={styles.errorText}>{errorMessage}</Text>
        )}

        <EspConnectionTable
          esps={esps}
          onAction={handleNodeAction}
          pendingAction={pendingAction}
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

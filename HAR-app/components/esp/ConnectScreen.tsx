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
import { EspCommandAction, EspStatus } from "@/app/types/espTypes";
import { espStatusApi } from "@/apis/espStatusApi";
import { ConnectionContext } from "../../app/contexts/ConnectionContext";

const NODE_IDS = [1, 2, 3];
const STATUS_TIMEOUT_MS = 10000;
const STATUS_POLL_MS = 3000;
const ACTION_TIMEOUT_MS: Record<EspCommandAction, number> = {
  connect: 30000,
  disconnect: 10000,
  reconnect: 35000,
  probe: 8000,
};
const RFCOMM_REBIND_TIMEOUT_MS = 35000;
const START_RECEIVING_TIMEOUT_MS = 8000;

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

const normalizeNodes = (
  nodes: EspStatus[],
  current: EspStatus[],
): EspStatus[] => {
  return NODE_IDS.map((id) => {
    const previous = current.find((node) => node.id === id);
    const next = nodes.find((node) => node.id === id);
    const normalizedNode: EspStatus = {
      ...(previous || { id, isConnected: null, status: "Unknown" }),
      ...(next || {}),
      id,
    };

    if (next && next.isConnected === false && !next.status) {
      normalizedNode.status = "Disconnected";
    }

    return {
      ...normalizedNode,
      isConnected: isNodeConnected(normalizedNode),
    };
  });
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
  const [rebindRunning, setRebindRunning] = useState(false);
  const [receivingRunning, setReceivingRunning] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const pendingActionRef = useRef(false);
  const espsRef = useRef<EspStatus[]>(initialNodes());

  const api = useMemo(() => espStatusApi(), []);
  const { setConnection } = useContext(ConnectionContext);
  const updateEsps = useCallback((updater: (current: EspStatus[]) => EspStatus[]) => {
    const next = updater(espsRef.current);
    espsRef.current = next;
    setEsps(next);

    return next;
  }, []);

  const fetchEsps = useCallback(
    async (initial = false, force = false) => {
      if (!initial && pendingActionRef.current && !force) return;

      try {
        setErrorMessage(null);

        const data = await withTimeout(api.getAllEspStatus(), STATUS_TIMEOUT_MS);
        const nextEsps = updateEsps((current) => normalizeNodes(data, current));

        const allConnected =
          nextEsps.length === 3 &&
          nextEsps.every(isNodeConnected);

        setConnection(allConnected);
      } catch (e: any) {
        console.error("ESP fetch error:", e);

        if (initial || force) {
          setErrorMessage(
            `Status refresh delayed; keeping last known state. ${
              e?.message || "Could not load nodes"
            }`
          );
        }
      }
    },
    [api, setConnection, updateEsps]
  );

  const handleNodeAction = useCallback(
    async (id: number, action: EspCommandAction) => {
      if (pendingActionRef.current) return;

      pendingActionRef.current = true;
      setPendingAction({ id, action });
      setErrorMessage(null);
      updateEsps((current) =>
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

        updateEsps((current) =>
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
          // Keep the last known state when a refresh fails after an action.
        } finally {
          setErrorMessage(message);
        }
      } finally {
        pendingActionRef.current = false;
        setPendingAction(null);
      }
    },
    [api, fetchEsps, updateEsps]
  );

  const handleRebindRfcomm = useCallback(async () => {
    if (pendingActionRef.current || rebindRunning || receivingRunning) return;

    pendingActionRef.current = true;
    setRebindRunning(true);
    setErrorMessage(null);
    setConnection(false);
    updateEsps((current) =>
      current.map((esp) => ({
        ...esp,
        isConnected: false,
        status: "Rebinding",
        detail: "Closing serial ports and running rfcommstarter.sh.",
      }))
    );

    try {
      await withTimeout(api.rebindRfcomm(), RFCOMM_REBIND_TIMEOUT_MS);
      await fetchEsps(false, true);
    } catch (e: any) {
      console.error("rfcomm rebind error:", e);
      setErrorMessage(e?.message || "Could not rebind rfcomm");
      await fetchEsps(false, true).catch(() => undefined);
    } finally {
      pendingActionRef.current = false;
      setRebindRunning(false);
    }
  }, [api, fetchEsps, receivingRunning, rebindRunning, setConnection, updateEsps]);

  const handleStartReceiving = useCallback(async () => {
    if (pendingActionRef.current || receivingRunning || rebindRunning) return;

    pendingActionRef.current = true;
    setReceivingRunning(true);
    setErrorMessage(null);
    updateEsps((current) =>
      current.map((esp) =>
        isNodeConnected(esp)
          ? {
              ...esp,
              status: "Receiving",
              detail: "Starting receive loop.",
            }
          : esp
      )
    );

    try {
      await withTimeout(api.startReceiving(), START_RECEIVING_TIMEOUT_MS);
      await fetchEsps(false, true);
    } catch (e: any) {
      console.error("start receiving error:", e);
      setErrorMessage(e?.message || "Could not start receiving data");
      await fetchEsps(false, true).catch(() => undefined);
    } finally {
      pendingActionRef.current = false;
      setReceivingRunning(false);
    }
  }, [api, fetchEsps, receivingRunning, rebindRunning, updateEsps]);

  useEffect(() => {
    fetchEsps(true);

    const interval = setInterval(() => {
      fetchEsps(false);
    }, STATUS_POLL_MS);

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

        <View style={styles.actionRow}>
          <Pressable
            style={[
              styles.receiveButton,
              (receivingRunning || rebindRunning || Boolean(pendingAction)) &&
                styles.disabledButton,
            ]}
            onPress={handleStartReceiving}
            disabled={receivingRunning || rebindRunning || Boolean(pendingAction)}
          >
            <Text style={styles.receiveText}>
              {receivingRunning ? "Starting receiving..." : "Start Receiving Data"}
            </Text>
          </Pressable>

          <Pressable
            style={[
              styles.rebindButton,
              (rebindRunning || receivingRunning || Boolean(pendingAction)) &&
                styles.disabledButton,
            ]}
            onPress={handleRebindRfcomm}
            disabled={rebindRunning || receivingRunning || Boolean(pendingAction)}
          >
            <Text style={styles.rebindText}>
              {rebindRunning ? "Rebinding rfcomm..." : "Rebind rfcomm"}
            </Text>
          </Pressable>

          <Pressable style={styles.retryButton} onPress={() => fetchEsps(false)}>
            <Text style={styles.retryText}>Refresh</Text>
          </Pressable>
        </View>
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
  actionRow: {
    marginTop: 16,
    flexDirection: "row",
    flexWrap: "wrap",
    gap: 10,
  },
  retryButton: {
    flex: 1,
    minWidth: 140,
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
  rebindButton: {
    flex: 1,
    minWidth: 180,
    backgroundColor: "#eff6ff",
    borderWidth: 1,
    borderColor: "#bfdbfe",
    paddingVertical: 12,
    paddingHorizontal: 20,
    borderRadius: 999,
    alignItems: "center",
  },
  rebindText: {
    color: "#2563eb",
    fontWeight: "800",
  },
  receiveButton: {
    flex: 1,
    minWidth: 210,
    backgroundColor: "#16a34a",
    paddingVertical: 12,
    paddingHorizontal: 20,
    borderRadius: 999,
    alignItems: "center",
  },
  receiveText: {
    color: "white",
    fontWeight: "800",
  },
  disabledButton: {
    opacity: 0.6,
  },
});

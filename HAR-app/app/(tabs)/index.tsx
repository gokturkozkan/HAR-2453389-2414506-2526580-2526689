import {
  View,
  Text,
  StyleSheet,
  Image,
  ImageSourcePropType,
  ActivityIndicator,
  Modal,
  ScrollView,
  Pressable,
  useWindowDimensions,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { router } from "expo-router";
import { useContext, useState, useEffect, useCallback, useMemo } from "react";
import { labelApi } from "@/apis/labelApi";
import { ConnectionContext } from "../contexts/ConnectionContext";
import {
  ACTIVITY_LABELS,
  formatActivityLabel,
  getActivityLabelImage,
} from "@/constants/activity-labels";

type LabelType = {
  label: string;
  image?: string;
  imageMime?: string;
  node_id?: number | null;
};

export default function HomeScreen() {
  const { width } = useWindowDimensions();
  const isDesktop = width >= 768;

  const [loading, setLoading] = useState(false);
  const [message, setMessage] = useState<[string, string] | null>(null);
  const [label, setLabel] = useState<LabelType | null>(null);
  const [isRelabelOpen, setIsRelabelOpen] = useState(false);

  const { connection } = useContext(ConnectionContext);
  const { getLabel, sendLabel } = useMemo(() => labelApi(), []);
  const labelImageSource: ImageSourcePropType | undefined = label?.image
    ? { uri: `data:${label.imageMime || "image/png"};base64,${label.image}` }
    : getActivityLabelImage(label?.label);

  const fetchLabel = useCallback(async () => {
    if (!connection) return;

    try {
      const data = await getLabel();

      setLabel((prev) => {
        if (prev?.label !== data.label) {
          setMessage(["success", `Current activity: ${formatActivityLabel(data.label)}`]);
        }
        return data;
      });
    } catch (e: any) {
      setMessage(["error", e.message]);
    }
  }, [connection, getLabel]);

  useEffect(() => {
    if (!connection) return;

    fetchLabel();

    const interval = setInterval(() => {
      fetchLabel();
    }, 1000);

    return () => clearInterval(interval);
  }, [connection, fetchLabel]);

  const handleRelabel = useCallback(
    async (nextLabel: string) => {
      if (!connection) return;

      try {
        setLoading(true);
        setIsRelabelOpen(false);
        await sendLabel(nextLabel, label?.node_id);
        await fetchLabel();
        setMessage(["success", `Relabeled as: ${formatActivityLabel(nextLabel)}`]);
      } catch (e: any) {
        setMessage(["error", e.message]);
      } finally {
        setLoading(false);
      }
    },
    [connection, sendLabel, fetchLabel, label?.node_id]
  );

  return (
    <SafeAreaView style={styles.safe}>
      <View style={styles.page}>
        <View style={[styles.card, isDesktop && styles.cardDesktop]}>
          <View style={styles.header}>
            <Text style={styles.eyebrow}>Human Activity Recognition</Text>
            <Text style={styles.title}>Live Activity Monitor</Text>
            <Text style={styles.subtitle}>
              3-node PAMAP2 setup: wrist, chest, and ankle.
            </Text>
          </View>

          <View style={styles.statusRow}>
            <View
              style={[
                styles.statusDot,
                connection ? styles.statusDotConnected : styles.statusDotDisconnected,
              ]}
            />
            <Text style={styles.statusText}>
              {connection ? "Connected to HAR Hub" : "Devices not connected"}
            </Text>
          </View>

          {connection ? (
            <>
              <View style={styles.activityBox}>
                {loading && <ActivityIndicator size="large" color="#2563eb" />}

                <Text style={styles.activityLabel}>
                  {label?.label
                    ? formatActivityLabel(label.label)
                    : "Waiting for prediction..."}
                </Text>

                {labelImageSource ? (
                  <Image
                    source={labelImageSource}
                    style={styles.labelImage}
                    resizeMode="contain"
                  />
                ) : (
                  <View style={styles.emptyImageBox}>
                    <Text style={styles.emptyImageText}>No image</Text>
                  </View>
                )}

                <Pressable
                  style={({ pressed }) => [
                    styles.primaryButton,
                    pressed && styles.pressed,
                  ]}
                  onPress={() => setIsRelabelOpen(true)}
                  disabled={loading}
                >
                  <Text style={styles.primaryButtonText}>Relabel Activity</Text>
                </Pressable>
              </View>

              {message?.[0] === "error" && (
                <Text style={styles.error}>{message[1]}</Text>
              )}
            </>
          ) : (
            <View style={styles.emptyState}>
              <Text style={styles.emptyTitle}>Start by connecting devices</Text>
              <Text style={styles.emptySubtitle}>
                Make sure wrist, chest, and ankle nodes are running.
              </Text>

              <Pressable
                style={({ pressed }) => [
                  styles.primaryButton,
                  pressed && styles.pressed,
                ]}
                onPress={() => router.push("/connect")}
              >
                <Text style={styles.primaryButtonText}>Go to Connect</Text>
              </Pressable>
            </View>
          )}
        </View>
      </View>

      <Modal
        visible={isRelabelOpen}
        animationType="fade"
        transparent
        onRequestClose={() => setIsRelabelOpen(false)}
      >
        <View style={styles.modalBackdrop}>
          <View style={styles.modalCard}>
            <Text style={styles.modalTitle}>Choose correct label</Text>

            <ScrollView>
              {ACTIVITY_LABELS.map((option) => (
                <Pressable
                  key={option}
                  style={styles.optionButton}
                  onPress={() => handleRelabel(option)}
                >
                  <Text style={styles.optionText}>{formatActivityLabel(option)}</Text>
                </Pressable>
              ))}
            </ScrollView>

            <Pressable
              style={styles.cancelButton}
              onPress={() => setIsRelabelOpen(false)}
            >
              <Text style={styles.cancelButtonText}>Cancel</Text>
            </Pressable>
          </View>
        </View>
      </Modal>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe: {
    flex: 1,
    backgroundColor: "#eef2ff",
  },
  page: {
    flex: 1,
    padding: 20,
    justifyContent: "center",
    alignItems: "center",
  },
  card: {
    width: "100%",
    maxWidth: 520,
    backgroundColor: "#ffffff",
    borderRadius: 28,
    padding: 22,
    shadowColor: "#0f172a",
    shadowOffset: { width: 0, height: 12 },
    shadowOpacity: 0.12,
    shadowRadius: 24,
    elevation: 6,
  },
  cardDesktop: {
    maxWidth: 680,
    padding: 32,
  },
  header: {
    marginBottom: 22,
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
    fontSize: 30,
    fontWeight: "800",
    color: "#0f172a",
  },
  subtitle: {
    marginTop: 8,
    fontSize: 15,
    color: "#64748b",
    lineHeight: 22,
  },
  statusRow: {
    flexDirection: "row",
    alignItems: "center",
    backgroundColor: "#f8fafc",
    borderRadius: 999,
    paddingVertical: 10,
    paddingHorizontal: 14,
    marginBottom: 22,
  },
  statusDot: {
    width: 10,
    height: 10,
    borderRadius: 999,
    marginRight: 8,
  },
  statusDotConnected: {
    backgroundColor: "#22c55e",
  },
  statusDotDisconnected: {
    backgroundColor: "#ef4444",
  },
  statusText: {
    color: "#334155",
    fontWeight: "600",
  },
  activityBox: {
    alignItems: "center",
    gap: 14,
  },
  activityLabel: {
    fontSize: 34,
    fontWeight: "800",
    color: "#111827",
    textTransform: "capitalize",
    textAlign: "center",
  },
  labelImage: {
    width: 180,
    height: 180,
  },
  emptyImageBox: {
    width: 160,
    height: 160,
    borderRadius: 24,
    backgroundColor: "#f1f5f9",
    alignItems: "center",
    justifyContent: "center",
  },
  emptyImageText: {
    color: "#94a3b8",
    fontWeight: "600",
  },
  emptyState: {
    alignItems: "center",
    gap: 12,
  },
  emptyTitle: {
    fontSize: 20,
    fontWeight: "800",
    color: "#0f172a",
  },
  emptySubtitle: {
    fontSize: 14,
    color: "#64748b",
    textAlign: "center",
    lineHeight: 20,
  },
  primaryButton: {
    marginTop: 8,
    backgroundColor: "#2563eb",
    paddingVertical: 14,
    paddingHorizontal: 22,
    borderRadius: 999,
    minWidth: 180,
    alignItems: "center",
  },
  pressed: {
    opacity: 0.85,
    transform: [{ scale: 0.98 }],
  },
  primaryButtonText: {
    color: "white",
    fontWeight: "800",
    fontSize: 15,
  },
  error: {
    color: "#dc2626",
    marginTop: 14,
    textAlign: "center",
    fontWeight: "600",
  },
  modalBackdrop: {
    flex: 1,
    backgroundColor: "rgba(15,23,42,0.45)",
    justifyContent: "center",
    alignItems: "center",
    padding: 24,
  },
  modalCard: {
    width: "100%",
    maxWidth: 420,
    maxHeight: 420,
    backgroundColor: "white",
    borderRadius: 24,
    padding: 18,
  },
  modalTitle: {
    fontSize: 18,
    fontWeight: "800",
    color: "#0f172a",
    marginBottom: 12,
  },
  optionButton: {
    paddingVertical: 14,
    paddingHorizontal: 14,
    borderRadius: 16,
    backgroundColor: "#f1f5f9",
    marginBottom: 10,
  },
  optionText: {
    fontSize: 16,
    color: "#0f172a",
    textTransform: "capitalize",
    fontWeight: "700",
  },
  cancelButton: {
    marginTop: 4,
    paddingVertical: 13,
    borderRadius: 16,
    alignItems: "center",
    backgroundColor: "#e2e8f0",
  },
  cancelButtonText: {
    color: "#1e293b",
    fontWeight: "800",
  },
});

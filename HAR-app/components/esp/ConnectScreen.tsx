import React, { useEffect, useState } from "react";
import { View, StyleSheet, ActivityIndicator, Text } from "react-native";
import { EspConnectionTable } from "./EspConnectionTable";
import { EspStatus } from "@/app/types/espTypes";
import { espStatusApi } from "@/app/apis/espStatusApi";

export default function ConnectScreen() {
  const [esps, setEsps] = useState<EspStatus[]>([]);
  const [loading, setLoading] = useState(true);
  const { getEspStatus } = espStatusApi();

  const fetchEspStatuses = async () => {
    try {
      try {
        const data = await getEspStatus();
        setEsps(data);
      } catch (e: any) {
        console.error("ESP fetch error:", e.message);
      }
    } catch (e) {
      console.error("Failed to fetch ESP statuses", e);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchEspStatuses();
    const interval = setInterval(fetchEspStatuses, 3000);
    return () => clearInterval(interval);
  }, []);

  const isAllDone = esps.length > 0 && esps.every(esp => esp.isConnected !== null);

  return (
    <View style={styles.screen}>
      {!isAllDone && (
        <View style={styles.disabledOverlay}>
          <ActivityIndicator size="large" />
          <Text style={styles.overlayText}>Connecting to devices...</Text>
        </View>
      )}
      <EspConnectionTable esps={esps} />
    </View>
  );
}

const styles = StyleSheet.create({
  screen: {
    flex: 1,
    padding: 16,
  },
  disabledOverlay: {
    ...StyleSheet.absoluteFillObject,
    backgroundColor: "rgba(0,0,0,0.35)",
    justifyContent: "center",
    alignItems: "center",
    zIndex: 10,
  },
  overlayText: {
    color: "white",
    fontSize: 16,
    marginTop: 8,
  },
});

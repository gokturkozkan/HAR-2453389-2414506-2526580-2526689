import React, { useContext, useEffect, useState } from "react";
import { View, StyleSheet, ActivityIndicator, Text } from "react-native";
import { EspConnectionTable } from "./EspConnectionTable";
import { EspId, EspStatus } from "@/app/types/espTypes";
import { espStatusApi } from "@/app/apis/espStatusApi";
import { ConnectionContext } from "../../app/contexts/ConnectionContext";

export default function ConnectScreen() {
  const [esps, setEsps] = useState<EspStatus[]>([]);
  const [loading, setLoading] = useState(true);
  const [connectingId, setConnectingId] = useState<number | null>(null);
  const [espStatus, setEspStatus] = useState<EspStatus[]>([]);
  const { getEspStatus, getEsp } = espStatusApi();
  const { connection, setConnection } = useContext(ConnectionContext);

  const fetchEsps = async (initial: boolean = false) => {
    if (initial) setLoading(true);
    try {
      try {
        const data = await getEsp();
        setEsps((prev) => {
          const prevMap = new Map(prev.map((e) => [e.id, e.isConnected]));
          return data.map((d: EspId) => ({
            id: d.id,
            isConnected: prevMap.get(d.id) ?? null,
          }));
        });
      } catch (e: any) {
        console.error("ESP fetch error:", e.message);
      }
    } catch (e) {
      console.error("Failed to fetch ESPs", e);
    } finally {
      if (initial) setLoading(false);
    }
  };

  const onConnect = async (id: number) => {
    setConnectingId(id);
    try {
      const data = await getEspStatus(id);
      setEsps((prev) => {
        const updated = prev.map((esp) => (
          esp.id === id ? { ...esp, isConnected: data.isConnected } : esp
        ));
        
        // Check connection status after updating
        const allConnected = updated.every((esp) => esp.isConnected === true);
        console.log("After update - all connected:", allConnected);
        setConnection(allConnected);
        console.log(connection)
        return updated;
      });
    } finally {
      setConnectingId(null);
    }
  }

  useEffect(() => {
    fetchEsps(true);
  }, []);

  if(loading) {
    return (
      <View style={styles.loadingScreen}>
        <ActivityIndicator size="large" />
        <Text style={styles.loadingText}>Loading devices...</Text>
      </View>
    );
  }
  return (
    <View style={styles.screen}>
      {connectingId !== null && (
        <View style={styles.disabledOverlay}>
          <ActivityIndicator size="large" />
          <Text style={styles.overlayText}>Connecting to devices...</Text>
        </View>
      )}
      <View style={styles.tableContainer}>
        <EspConnectionTable esps={esps} onConnect={onConnect} loadingId={connectingId}/>
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  screen: {
    flex: 1,
    padding: 16,
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
  tableContainer: {
    paddingTop: 48,
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

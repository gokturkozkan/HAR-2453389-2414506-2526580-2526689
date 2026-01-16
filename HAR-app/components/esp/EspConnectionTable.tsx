import React from "react";
import { ScrollView, View, StyleSheet } from "react-native";
import { EspConnectionCard } from "./EspConnectionCard";
import { EspStatus } from "@/app/types/espTypes";

interface EspConnectionTableProps {
  esps: EspStatus[];
  onConnect?: (id: number) => void;
  loadingId?: number | null;
}

export const EspConnectionTable: React.FC<EspConnectionTableProps> = ({ 
  esps, 
  onConnect,
  loadingId
}) => {
  return (
    <ScrollView contentContainerStyle={styles.container}>
      {esps.map((esp) => (
        <View key={esp.id} style={styles.item}>
          <EspConnectionCard count={esp.id} isConnected={esp.isConnected ?? undefined} onConnect={onConnect} loading={loadingId === esp.id} />
        </View>
      ))}
    </ScrollView>
  );
};

const styles = StyleSheet.create({
  container: {
    paddingVertical: 8,
    gap: 16,
  },
  item: {
    justifyContent: "center",
    alignItems: "center",
  },
});

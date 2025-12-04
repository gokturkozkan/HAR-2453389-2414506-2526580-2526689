import React from "react";
import { ScrollView, View, StyleSheet } from "react-native";
import { EspConnectionCard } from "./EspConnectionCard";

export interface EspStatus {
  id: number;
  isConnected: boolean | null;
}

interface EspConnectionTableProps {
  esps: EspStatus[];
}

export const EspConnectionTable: React.FC<EspConnectionTableProps> = ({ esps }) => {
  return (
    <ScrollView contentContainerStyle={styles.container}>
      {esps.map((esp) => (
        <View key={esp.id} style={styles.item}>
          <EspConnectionCard count={esp.id} isConnected={esp.isConnected ?? undefined} />
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

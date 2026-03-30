import React from "react";
import { View, StyleSheet } from "react-native";
import { EspConnectionCard } from "./EspConnectionCard";
import { EspStatus } from "@/app/types/espTypes";

interface EspConnectionTableProps {
  esps: EspStatus[];
}

export const EspConnectionTable: React.FC<EspConnectionTableProps> = ({ esps }) => {
  return (
    <View style={styles.container}>
      {esps.map((esp) => (
        <View key={esp.id} style={styles.item}>
          <EspConnectionCard esp={esp} />
        </View>
      ))}
    </View>
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

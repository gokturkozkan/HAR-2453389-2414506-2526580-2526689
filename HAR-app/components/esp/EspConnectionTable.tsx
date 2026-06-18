import React from "react";
import { ScrollView, View, StyleSheet } from "react-native";
import { EspConnectionCard } from "./EspConnectionCard";
import { EspCommandAction, EspStatus } from "@/app/types/espTypes";

interface EspConnectionTableProps {
  esps: EspStatus[];
  onAction?: (id: number, action: EspCommandAction) => void;
  pendingAction?: { id: number; action: EspCommandAction } | null;
}

export const EspConnectionTable: React.FC<EspConnectionTableProps> = ({ 
  esps, 
  onAction,
  pendingAction
}) => {
  return (
    <ScrollView contentContainerStyle={styles.container}>
      {esps.map((esp) => (
        <View key={esp.id} style={styles.item}>
          <EspConnectionCard
            count={esp.id}
            isConnected={esp.isConnected ?? undefined}
            status={esp.status}
            detail={esp.detail}
            port={esp.port}
            onAction={onAction}
            loadingAction={
              pendingAction?.id === esp.id ? pendingAction.action : null
            }
          />
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

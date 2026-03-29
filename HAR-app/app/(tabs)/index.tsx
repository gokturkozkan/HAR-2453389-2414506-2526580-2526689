import { View, Text, StyleSheet, Image, ActivityIndicator, Modal, ScrollView } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Pressable } from "react-native";
import { router } from "expo-router";
import { useContext, useState, useEffect, useCallback } from "react";
import { useFocusEffect } from '@react-navigation/native';
import { labelApi } from "@/apis/labelApi";
import { ConnectionContext } from "../contexts/ConnectionContext";

const handleConnection = () => {
  router.push("/connect");
};

type labelType = {
  label: string;
  image: string;
}

const relabelOptions = ["sitting", "standing", "walking", "jumping", "lying"];

export default function HomeScreen() {
  const [ loading, setLoading ] = useState<boolean>(false);
  const [ message, setMessage ] = useState<[string, string] | null>(null);
  const [ label, setLabel ] = useState<labelType>();
  const [ isRelabelOpen, setIsRelabelOpen ] = useState<boolean>(false);
  const { connection, setConnection } = useContext(ConnectionContext);
  const { getLabel, sendLabel } = labelApi();

  console.log("HomeScreen render - connection state:", connection);

  const fetchLabel = useCallback(async() => {
    if(!connection) return;
    
    try {
      setLoading(true);
      const data = await getLabel();
      setLabel(data);
      setMessage(["success", `Received label: ${data.label}`]);
    } catch (e: any) {
      setMessage(["error", e.message]);
      console.error("Label fetch error:", e);
    } finally {
      setLoading(false);
    }
  }, [connection, getLabel]);

  const handleRelabel = useCallback(async (nextLabel: string) => {
    if (!connection) return;

    try {
      setLoading(true);
      setIsRelabelOpen(false);
      await sendLabel(nextLabel);
      await fetchLabel();
      setMessage(["success", `Relabeled as: ${nextLabel}`]);
    } catch (e: any) {
      setMessage(["error", e.message]);
      console.error("Label update error:", e);
    } finally {
      setLoading(false);
    }
  }, [connection, sendLabel, fetchLabel]);

  useEffect(() => {
    if(connection) {
      console.log("useEffect triggered - fetching label");
      fetchLabel();
    }
  }, [connection, fetchLabel]);

  // Also refetch when the Home tab gains focus
  useFocusEffect(
    useCallback(() => {
      setConnection(true);
      console.log("Home tab focused - connection:", connection);
      if (connection) {
        fetchLabel();
      }
    }, [connection, fetchLabel])
  );

  return (
    <SafeAreaView style={styles.safe}>
      <View style={styles.container}>
        <View style={styles.inner}>
          <View style={styles.card}>
            <Text style={{ marginBottom: 8, color: '#475569' }}>Status: {connection ? 'Connected' : 'Not connected'}</Text>
            {connection ? ( 
              <>
                <Text style={{ marginBottom: 8 }}>Connected</Text>
                {loading && <ActivityIndicator size="large" color="#1e293b" style={{ marginBottom: 16 }} />}
                {message && message[0] == "success" && 
                  <View style={styles.labelContainer}>
                    <Text style={styles.labelText}>{label?.label}</Text>
                    {label?.image && (
                      <Image
                        source={{ uri: `data:image/png;base64,${label.image}` }}
                        style={styles.labelImage}
                      />
                    )}
                    <Pressable
                      style={styles.dropdownButton}
                      onPress={() => setIsRelabelOpen(true)}
                      disabled={loading}
                    >
                      <Text style={styles.dropdownButtonText}>Relabel</Text>
                    </Pressable>
                  </View>
                }
                {message && message[0] == "error" && <Text style={styles.error}>{message[1]}</Text>}

                <Modal
                  visible={isRelabelOpen}
                  animationType="fade"
                  transparent
                  onRequestClose={() => setIsRelabelOpen(false)}
                >
                  <View style={styles.modalBackdrop}>
                    <View style={styles.modalCard}>
                      <Text style={styles.modalTitle}>Choose a new label</Text>
                      <ScrollView>
                        {relabelOptions.map((option) => (
                          <Pressable
                            key={option}
                            style={styles.optionButton}
                            onPress={() => handleRelabel(option)}
                          >
                            <Text style={styles.optionText}>{option}</Text>
                          </Pressable>
                        ))}
                      </ScrollView>
                      <Pressable style={styles.cancelButton} onPress={() => setIsRelabelOpen(false)}>
                        <Text style={styles.cancelButtonText}>Cancel</Text>
                      </Pressable>
                    </View>
                  </View>
                </Modal>
              </>
            ) : (
              <>
                <Text style={styles.title}>Get started</Text>
                <Text>Welcome to the HAR app.</Text>
                <Pressable style={styles.button} onPress={handleConnection}>
                  <Text style={styles.buttonText}>Connect</Text>
                </Pressable>
              </>
            )}

          </View>
        </View>
      </View>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe: {
    flex: 1,
    backgroundColor: "#97a5cbff", 
  },
  container: {
    flex: 1,
  },
  inner: {
    flex: 1,
    justifyContent: "center",
    alignItems: "center", 
    paddingHorizontal: 24,
  },
  card: {
    width: "100%",
    backgroundColor: "white",
    borderRadius: 20,
    paddingHorizontal: 20,
    paddingVertical: 24,
    shadowColor: "#000",
    shadowOffset: { width: 0, height: 6 },
    shadowOpacity: 0.15,
    shadowRadius: 10,
    elevation: 5,
  },
  headerContainer: {
    alignItems: "center",
    marginBottom: 20,
  },
  row: {
    flexDirection: "row",
    alignItems: "center",
  },
  title: {
    fontSize: 28,
    fontWeight: "700",
  },
  subtitle: {
    marginTop: 6,
    fontSize: 14,
    opacity: 0.7,
  },
  form: {
    gap: 12,
  },
  label: {
    fontSize: 14,
    fontWeight: "500",
    marginTop: 8,
    marginBottom: 4,
  },
  input: {
    borderWidth: 1,
    borderRadius: 10,
    paddingHorizontal: 12,
    paddingVertical: 10,
    fontSize: 15,
    backgroundColor: "#f8fafc",
    borderColor: "#cbd5e1",
  },
  error: {
    color: "red",
    marginTop: 6,
    fontSize: 13,
  },
  labelContainer: {
    alignItems: "center",
    marginBottom: 16,
    paddingBottom: 12,
    borderBottomWidth: 1,
    borderBottomColor: "#e0e0e0",
  },
  labelText: {
    fontSize: 18,
    fontWeight: "600",
    marginBottom: 8,
    textTransform: "capitalize",
  },
  labelImage: {
    width: 120,
    height: 120,
    resizeMode: "contain",
  },
  dropdownButton: {
    marginTop: 12,
    borderRadius: 999,
    paddingVertical: 10,
    paddingHorizontal: 18,
    backgroundColor: "#0f766e",
  },
  dropdownButtonText: {
    color: "white",
    fontSize: 14,
    fontWeight: "600",
  },
  modalBackdrop: {
    flex: 1,
    backgroundColor: "rgba(0,0,0,0.35)",
    justifyContent: "center",
    alignItems: "center",
    paddingHorizontal: 24,
  },
  modalCard: {
    width: "100%",
    maxHeight: 380,
    backgroundColor: "white",
    borderRadius: 14,
    padding: 16,
    gap: 10,
  },
  modalTitle: {
    fontSize: 16,
    fontWeight: "700",
    color: "#0f172a",
    marginBottom: 6,
  },
  optionButton: {
    paddingVertical: 10,
    paddingHorizontal: 10,
    borderRadius: 8,
    backgroundColor: "#f1f5f9",
    marginBottom: 8,
  },
  optionText: {
    fontSize: 15,
    color: "#0f172a",
    textTransform: "capitalize",
  },
  cancelButton: {
    marginTop: 2,
    paddingVertical: 10,
    borderRadius: 8,
    alignItems: "center",
    backgroundColor: "#e2e8f0",
  },
  cancelButtonText: {
    color: "#1e293b",
    fontWeight: "600",
  },
  button: {
    marginTop: 16,
    borderRadius: 999,
    paddingVertical: 12,
    alignItems: "center",
    backgroundColor: "#1e293b", 
  },
  buttonText: {
    fontSize: 16,
    fontWeight: "600",
    color: "white",
  },
});

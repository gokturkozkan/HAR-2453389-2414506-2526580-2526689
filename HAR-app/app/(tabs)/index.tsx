import { View, Text, StyleSheet, Image, ActivityIndicator, Modal, ScrollView } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Pressable } from "react-native";
import { router } from "expo-router";
import { useContext, useState, useEffect, useCallback, useRef } from "react";
import { useFocusEffect } from '@react-navigation/native';
import { labelApi } from "../apis/labelApi";
import { espStatusApi } from "../apis/espStatusApi";
import { ConnectionContext } from "../contexts/ConnectionContext";

const handleConnection = () => {
  router.push("/connect");
};

type labelType = {
  label: string;
  image: string;
}

export default function HomeScreen() {
  const [ loading, setLoading ] = useState<boolean>(false);
  const [ message, setMessage ] = useState<[string, string] | null>(null);
  const [ label, setLabel ] = useState<labelType>();
  const { connection } = useContext(ConnectionContext);
  const [ newLabel, setNewLabel ] = useState<string>("");
  const [ dropdownVisible, setDropdownVisible ] = useState<boolean>(false);
  const getLabelRef = useRef(labelApi().getLabel);
  const sendLabel = labelApi().sendLabel;

  const activityLabels = [
    "walk",
    "sit",
    "idle"
  ];

  console.log("HomeScreen render - connection state:", connection);

  // Initial fetch when screen gains focus
  useFocusEffect(
    useCallback(() => {
      if (!connection) return;

      let isActive = true;

      (async () => {
        setLoading(true);
        try {
          const data = await getLabelRef.current();
          if (!isActive) return; // prevent state updates if user leaves screen
          setLabel(data);
          setMessage(["success", `Received label: ${data.label}`]);
        } catch (e: any) {
          if (!isActive) return;
          setMessage(["error", e.message]);
        } finally {
          if (isActive) setLoading(false);
        }
      })();

      return () => {
        isActive = false;
      };
    }, [connection])
  );

  // Poll for label updates every 2 seconds when connected
  useEffect(() => {
    if (!connection) return;

    const pollLabel = async () => {
      try {
        const data = await getLabelRef.current();
        // Only update if label changed
        if (data.label !== label?.label) {
          console.log(`Label changed from ${label?.label} to ${data.label}`);
          setLabel(data);
        }
      } catch (e: any) {
        console.error("Poll error:", e.message);
      }
    };

    const interval = setInterval(pollLabel, 2000);
    return () => clearInterval(interval);
  }, [connection, label?.label]);

  const labelChangeHandler = async(activity: string) => {
    try {
      const data = await sendLabel(activity);
      console.log(`new label sent ${ activity }`)
      // Update the label state with the new data from the response
      setLabel({ label: data.label, image: data.image });
      setMessage(["success", `Sent new label ${ activity }`]);
    } catch (e: any) {
      setMessage(["error", e.message]);
    }
  }

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
                {!loading && label && 
                  <View style={styles.labelContainer}>
                    <Text style={styles.labelText}>{label?.label}</Text>
                    {label?.image && (
                      <Image
                        source={{ uri: `data:image/png;base64,${label.image}` }}
                        style={styles.labelImage}
                      />
                    )}
                    <Text style={styles.label}>Re-label</Text>
                    <Pressable 
                      style={styles.dropdown}
                      onPress={() => {
                        setDropdownVisible(true);
                      }}
                    >
                      <Text style={newLabel ? styles.dropdownText : styles.dropdownPlaceholder}>
                        {newLabel || "Select a label"}
                      </Text>
                      <Text style={styles.dropdownArrow}>▼</Text>
                    </Pressable>

                    <Modal
                      visible={dropdownVisible}
                      transparent={true}
                      animationType="fade"
                      onRequestClose={() => setDropdownVisible(false)}
                    >
                      <Pressable 
                        style={styles.modalOverlay}
                        onPress={() => setDropdownVisible(false)}
                      >
                        <View style={styles.dropdownMenu}>
                          <ScrollView>
                            {activityLabels.map((activity) => (
                              <Pressable
                                key={activity}
                                style={styles.dropdownItem}
                                onPress={() => {
                                  setNewLabel(activity);
                                  setDropdownVisible(false);
                                  labelChangeHandler(activity);
                                }}
                              >
                                <Text style={styles.dropdownItemText}>{activity}</Text>
                              </Pressable>
                            ))}
                          </ScrollView>
                        </View>
                      </Pressable>
                    </Modal>
                  </View>
                }
                {message && message[0] == "error" && <Text style={styles.error}>{message[1]}</Text>}
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
  dropdown: {
    borderWidth: 1,
    borderRadius: 10,
    paddingHorizontal: 12,
    paddingVertical: 10,
    fontSize: 15,
    backgroundColor: "#f8fafc",
    borderColor: "#cbd5e1",
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "center",
  },
  dropdownText: {
    fontSize: 15,
    color: "#000",
    textTransform: "capitalize",
  },
  dropdownPlaceholder: {
    fontSize: 15,
    color: "#999",
  },
  dropdownArrow: {
    fontSize: 12,
    color: "#666",
  },
  modalOverlay: {
    flex: 1,
    backgroundColor: "rgba(0, 0, 0, 0.5)",
    justifyContent: "center",
    alignItems: "center",
  },
  dropdownMenu: {
    backgroundColor: "white",
    borderRadius: 10,
    width: "80%",
    maxHeight: 300,
    shadowColor: "#000",
    shadowOffset: { width: 0, height: 2 },
    shadowOpacity: 0.25,
    shadowRadius: 4,
    elevation: 5,
  },
  dropdownItem: {
    paddingVertical: 12,
    paddingHorizontal: 16,
    borderBottomWidth: 1,
    borderBottomColor: "#f0f0f0",
  },
  dropdownItemText: {
    fontSize: 16,
    color: "#000",
    textTransform: "capitalize",
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

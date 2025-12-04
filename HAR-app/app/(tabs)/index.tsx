import { View, Text, StyleSheet } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Pressable } from "react-native";
import { router } from "expo-router";

const handleConnection = () => {
  router.replace("/connect");
};

export default function HomeScreen() {
  return (
    <SafeAreaView style = {styles.safe}>
      <View style={styles.container}>
        <View style={styles.inner}>
          <View style={styles.card}>
            <Text style={styles.title}>Get started</Text>
            <Text>Welcome to the HAR app.</Text>
            <Pressable style={styles.button} onPress={handleConnection}>
              <Text style={styles.buttonText}>Connect</Text>
            </Pressable>
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

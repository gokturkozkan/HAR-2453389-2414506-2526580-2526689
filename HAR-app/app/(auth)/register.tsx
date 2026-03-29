import { useContext, useState } from "react";
import {
  View,
  Text,
  KeyboardAvoidingView,
  StyleSheet,
  TextInput,
  Pressable,
  Platform,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { HelloWave } from "@/components/hello-wave";
import { router } from "expo-router";
import { registerApi } from "@/apis/registerApi";
import { UserContext } from "../contexts/UserContext";

export default function RegisterScreen() {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const { setUser } = useContext(UserContext)!;
  const { register } = registerApi();

  const handleRegister = async () => {
    if (!username && !password && !confirmPassword) {
      setError("Please fill all fields.");
    } else if (!username) {
      setError("Please enter username.");
    } else if (!password) {
      setError("Please enter password.");
    } else if (!confirmPassword) {
      setError("Please confirm your password.");
    } else if (password !== confirmPassword) {
      setError("Passwords do not match.");
    } else {
      setError(null);
    }
    try {
      console.log("data being sent to backend..")
      setError(null);
      const data = await register({ username, password })
      setUser({ username: data.user.username, id: data.user.id})
      console.log("TOKEN:", data.token);
      console.log("USER:", data.user);

      router.replace("/(tabs)");
      } catch (e: any) {
        setError(e.message);
    }
  };

  return (
    <SafeAreaView style={styles.safe}>
      <KeyboardAvoidingView
        style={styles.container}
        behavior={Platform.OS === "android" ? "padding" : undefined}
      >
        <View style={styles.inner}>
          <View style={styles.card}>
            <View style={styles.headerContainer}>
              <View style={styles.row}>
                <Text style={styles.title}>Create Account</Text>
                <View style={{ marginLeft: 8 }}>
                  <HelloWave />
                </View>
              </View>
              <Text style={styles.subtitle}>Register to start using the app</Text>
            </View>

            <View style={styles.form}>
              <Text style={styles.label}>Username</Text>
              <TextInput
                style={styles.input}
                value={username}
                onChangeText={setUsername}
                placeholder="Enter username"
                autoCapitalize="none"
              />

              <Text style={styles.label}>Password</Text>
              <TextInput
                style={styles.input}
                value={password}
                onChangeText={setPassword}
                placeholder="Enter password"
                secureTextEntry
              />

              <Text style={styles.label}>Confirm Password</Text>
              <TextInput
                style={styles.input}
                value={confirmPassword}
                onChangeText={setConfirmPassword}
                placeholder="Re-enter password"
                secureTextEntry
              />

              {error && <Text style={styles.error}>{error}</Text>}

              <Pressable style={styles.button} onPress={handleRegister}>
                <Text style={styles.buttonText}>Register</Text>
              </Pressable>

              <Pressable
                onPress={() => router.replace("/login")}
                style={styles.registerButton}
              >
                <Text style={styles.registerText}>
                  Already have an account?{" "}
                  <Text style={styles.registerLink}>Login</Text>
                </Text>
              </Pressable>
            </View>
          </View>
        </View>
      </KeyboardAvoidingView>
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
  registerButton: {
    alignItems: "center",
    marginTop: 12,
  },
  registerText: {
    fontSize: 14,
    opacity: 0.8,
  },
  registerLink: {
    color: "#1e293b",
    fontWeight: "600",
  },
});

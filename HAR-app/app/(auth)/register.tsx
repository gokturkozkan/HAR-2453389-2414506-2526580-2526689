import { useContext, useState } from "react";
import {
  View,
  Text,
  KeyboardAvoidingView,
  StyleSheet,
  TextInput,
  Pressable,
  Platform,
  ActivityIndicator,
  useWindowDimensions,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { router } from "expo-router";
import { registerApi } from "@/apis/registerApi";
import { UserContext } from "../contexts/UserContext";
import { ConnectionContext } from "../contexts/ConnectionContext";

export default function RegisterScreen() {
  const { width } = useWindowDimensions();
  const isDesktop = width >= 768;

  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const { setUser } = useContext(UserContext)!;
  const { setConnection } = useContext(ConnectionContext)!;
  const { register } = registerApi();

  const handleRegister = async () => {
    if (!username.trim() || !password || !confirmPassword) {
      setError("Please fill all fields.");
      return;
    }

    if (password !== confirmPassword) {
      setError("Passwords do not match.");
      return;
    }

    try {
      setLoading(true);
      setError(null);

      const data = await register({ username: username.trim(), password });

      setUser({ username: data.user.username, id: data.user.id });
      setConnection(false);

      router.replace("/");
    } catch (e: any) {
      setError(e.message || "Registration failed.");
    } finally {
      setLoading(false);
    }
  };

  return (
    <SafeAreaView style={styles.safe}>
      <KeyboardAvoidingView
        style={styles.page}
        behavior={Platform.OS === "ios" ? "padding" : undefined}
      >
        <View style={[styles.card, isDesktop && styles.cardDesktop]}>
          <View style={styles.header}>
            <Text style={styles.eyebrow}>Human Activity Recognition</Text>
            <Text style={styles.title}>Create account</Text>
            <Text style={styles.subtitle}>
              Register to start using the HAR live monitoring system.
            </Text>
          </View>

          <View style={styles.statusRow}>
            <View style={styles.statusDot} />
            <Text style={styles.statusText}>New user registration</Text>
          </View>

          <View style={styles.form}>
            <Text style={styles.label}>Username</Text>
            <TextInput
              style={styles.input}
              value={username}
              onChangeText={setUsername}
              placeholder="Enter username"
              placeholderTextColor="#94a3b8"
              autoCapitalize="none"
              autoCorrect={false}
            />

            <Text style={styles.label}>Password</Text>
            <TextInput
              style={styles.input}
              value={password}
              onChangeText={setPassword}
              placeholder="Enter password"
              placeholderTextColor="#94a3b8"
              secureTextEntry
            />

            <Text style={styles.label}>Confirm Password</Text>
            <TextInput
              style={styles.input}
              value={confirmPassword}
              onChangeText={setConfirmPassword}
              placeholder="Re-enter password"
              placeholderTextColor="#94a3b8"
              secureTextEntry
            />

            {error && <Text style={styles.error}>{error}</Text>}

            <Pressable
              style={({ pressed }) => [
                styles.primaryButton,
                pressed && styles.pressed,
                loading && styles.disabledButton,
              ]}
              onPress={handleRegister}
              disabled={loading}
            >
              {loading ? (
                <ActivityIndicator color="white" />
              ) : (
                <Text style={styles.primaryButtonText}>Register</Text>
              )}
            </Pressable>

            <Pressable
              onPress={() => router.replace("/(auth)/login")}
              style={styles.footerLink}
            >
              <Text style={styles.footerText}>
                Already have an account?{" "}
                <Text style={styles.footerTextStrong}>Login</Text>
              </Text>
            </Pressable>
          </View>
        </View>
      </KeyboardAvoidingView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe: {
    flex: 1,
    backgroundColor: "#eef2ff",
  },
  page: {
    flex: 1,
    padding: 20,
    justifyContent: "center",
    alignItems: "center",
  },
  card: {
    width: "100%",
    maxWidth: 520,
    backgroundColor: "#ffffff",
    borderRadius: 28,
    padding: 22,
    shadowColor: "#0f172a",
    shadowOffset: { width: 0, height: 12 },
    shadowOpacity: 0.12,
    shadowRadius: 24,
    elevation: 6,
  },
  cardDesktop: {
    maxWidth: 680,
    padding: 32,
  },
  header: {
    marginBottom: 22,
  },
  eyebrow: {
    fontSize: 13,
    fontWeight: "700",
    color: "#2563eb",
    textTransform: "uppercase",
    letterSpacing: 0.8,
    marginBottom: 6,
  },
  title: {
    fontSize: 30,
    fontWeight: "800",
    color: "#0f172a",
  },
  subtitle: {
    marginTop: 8,
    fontSize: 15,
    color: "#64748b",
    lineHeight: 22,
  },
  statusRow: {
    flexDirection: "row",
    alignItems: "center",
    backgroundColor: "#f8fafc",
    borderRadius: 999,
    paddingVertical: 10,
    paddingHorizontal: 14,
    marginBottom: 22,
  },
  statusDot: {
    width: 10,
    height: 10,
    borderRadius: 999,
    marginRight: 8,
    backgroundColor: "#2563eb",
  },
  statusText: {
    color: "#334155",
    fontWeight: "600",
  },
  form: {
    gap: 10,
  },
  label: {
    marginTop: 8,
    fontSize: 14,
    fontWeight: "700",
    color: "#334155",
  },
  input: {
    borderWidth: 1,
    borderColor: "#cbd5e1",
    borderRadius: 16,
    paddingHorizontal: 14,
    paddingVertical: 13,
    fontSize: 15,
    color: "#0f172a",
    backgroundColor: "#f8fafc",
  },
  error: {
    marginTop: 6,
    color: "#dc2626",
    fontSize: 13,
    fontWeight: "600",
  },
  primaryButton: {
    marginTop: 16,
    backgroundColor: "#2563eb",
    paddingVertical: 14,
    paddingHorizontal: 22,
    borderRadius: 999,
    alignItems: "center",
  },
  disabledButton: {
    opacity: 0.7,
  },
  pressed: {
    opacity: 0.85,
    transform: [{ scale: 0.98 }],
  },
  primaryButtonText: {
    color: "white",
    fontWeight: "800",
    fontSize: 15,
  },
  footerLink: {
    alignItems: "center",
    marginTop: 14,
  },
  footerText: {
    color: "#64748b",
    fontSize: 14,
    fontWeight: "600",
  },
  footerTextStrong: {
    color: "#2563eb",
    fontWeight: "800",
  },
});
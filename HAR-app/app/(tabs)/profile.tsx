import { SafeAreaView } from "react-native-safe-area-context";
import {
  View,
  StyleSheet,
  Text,
  KeyboardAvoidingView,
  Platform,
  TextInput,
  Pressable
} from "react-native"
import { useState, useContext } from "react";
import { UserContext } from "../contexts/UserContext";
import { userApi } from "../apis/userApi";

export default function Profile() {
  const [newUsername, setNewUsername] = useState("")
  const [message, setMessage] = useState<[string, string] | null>(null)
  const { user, setUser } = useContext(UserContext)!;
  const { updateUser } = userApi();

  const handleUpdateUser = async() => {
    if(!newUsername) {
      setMessage(["error", "Please enter new username."])
      return;
    } 
    
    if(newUsername == user?.username) {
      setMessage(["error", "Please enter a new username."])
      return;
    }
    
    if (!user?.id) {
      setMessage(["error", "User not logged in."])
      return;
    }

    setMessage(null);
    
    try {
      const data = await updateUser({username: newUsername}, user.id)
      setUser({username: data.user.username, id: data.user.id})

      setMessage(["success", "Saved new information"])
    } catch (e: any) {
      setMessage(["error", e.message])
    }
  }
  return(
    <SafeAreaView style={styles.safe}>
      <KeyboardAvoidingView
        style={styles.container}
        behavior={Platform.OS === "android" ? "padding" : undefined}
      >
        <View style = {styles.inner}>
          <View style = {styles.card}>
            <View style = {styles.headerContainer}>
              <View style = {styles.row}>
                <Text style = {styles.title}>Change profile</Text>
              </View>
            </View>
            <View style={styles.form}>
              <Text style={styles.label}>Username</Text>
                <TextInput
                  style={styles.input}
                  value={newUsername}
                  onChangeText={setNewUsername}
                  placeholder={user?.username}
                  autoCapitalize="none"
                />
              {message && message[0] == "error" && <Text style={styles.error}>{message[1]}</Text>}
              {message && message[0] == "success" && <Text style={styles.success}>{message[1]}</Text>}
              <Pressable style={styles.button} onPress={handleUpdateUser}>
                <Text style={styles.buttonText}>Save changes</Text>
              </Pressable>
            </View>
          </View>
        </View>
      </KeyboardAvoidingView>
      
    </SafeAreaView>
  )
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
  success: {
    color: "green",
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
    color: "#3a547dff",
    fontWeight: "600",
  },
});

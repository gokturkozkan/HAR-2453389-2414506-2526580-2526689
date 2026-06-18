import { DarkTheme, DefaultTheme, ThemeProvider } from "@react-navigation/native";
import { Stack, Redirect, useSegments } from "expo-router";
import { StatusBar } from "expo-status-bar";
import { useContext } from "react";
import "react-native-reanimated";

import { useColorScheme } from "@/hooks/use-color-scheme";
import { UserProvider, UserContext } from "./contexts/UserContext";
import { ConnectionProvider } from "./contexts/ConnectionContext";

function RootNavigator() {
  const colorScheme = useColorScheme();
  const segments = useSegments();
  const userContext = useContext(UserContext);

  const user = userContext?.user;
  const inAuthGroup = segments[0] === "(auth)";

  return (
    <ThemeProvider value={colorScheme === "dark" ? DarkTheme : DefaultTheme}>
      {!user && !inAuthGroup && <Redirect href="/(auth)/login" />}
      {user && inAuthGroup && <Redirect href="/(tabs)" />}

      <Stack>
        <Stack.Screen name="(auth)" options={{ headerShown: false }} />
        <Stack.Screen name="(tabs)" options={{ headerShown: false }} />
      </Stack>

      <StatusBar style="auto" />
    </ThemeProvider>
  );
}

export default function RootLayout() {
  return (
    <UserProvider>
      <ConnectionProvider>
        <RootNavigator />
      </ConnectionProvider>
    </UserProvider>
  );
}
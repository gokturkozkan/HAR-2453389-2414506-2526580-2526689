import { Tabs, Redirect } from "expo-router";
import React, { useContext } from "react";
import { Ionicons } from "@expo/vector-icons";

import { HapticTab } from "@/components/haptic-tab";
import { IconSymbol } from "@/components/ui/icon-symbol";
import { Colors } from "@/constants/theme";
import { useColorScheme } from "@/hooks/use-color-scheme";
import { UserContext } from "../contexts/UserContext";

export default function TabLayout() {
  const colorScheme = useColorScheme();
  const theme = Colors[colorScheme ?? "light"];

  const userContext = useContext(UserContext);

  if (!userContext?.user) {
    return <Redirect href="/login" />;
  }

  return (
    <Tabs
      screenOptions={{
        tabBarActiveTintColor: theme.tint,
        tabBarInactiveTintColor: "#94a3b8",
        headerShown: false,
        tabBarButton: HapticTab,
      }}
    >
      <Tabs.Screen
        name="index"
        options={{
          title: "Home",
          tabBarIcon: ({ color }) => (
            <IconSymbol size={26} name="house.fill" color={color} />
          ),
        }}
      />

      <Tabs.Screen
        name="connect"
        options={{
          title: "Connect",
          tabBarIcon: ({ color }) => (
            <Ionicons size={26} name="hardware-chip-outline" color={color} />
          ),
        }}
      />

      <Tabs.Screen
        name="profile"
        options={{
          title: "Profile",
          tabBarIcon: ({ color }) => (
            <Ionicons size={26} name="person-outline" color={color} />
          ),
        }}
      />
    </Tabs>
  );
}
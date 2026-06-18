import Constants from "expo-constants";
import { Platform } from "react-native";

const API_PORT = process.env.EXPO_PUBLIC_API_PORT || "3000";

const getHostFromUri = (value?: string | null) => {
  if (!value) return null;

  try {
    const uri = value.includes("://") ? value : `http://${value}`;
    return new URL(uri).hostname || null;
  } catch {
    return null;
  }
};

const getWebHost = () => {
  if (typeof window === "undefined") return null;

  return window.location.hostname || null;
};

const getDevServerHost = () => {
  const constants = Constants as any;
  const candidates = [
    process.env.EXPO_PUBLIC_API_HOST,
    getWebHost(),
    constants.expoConfig?.hostUri,
    constants.expoGoConfig?.debuggerHost,
    constants.manifest?.debuggerHost,
    constants.manifest2?.extra?.expoClient?.hostUri,
    constants.linkingUri,
  ];

  for (const candidate of candidates) {
    const host = getHostFromUri(candidate) || candidate;
    if (host && host !== "localhost" && host !== "127.0.0.1") {
      return host;
    }
  }

  return Platform.OS === "web" ? "localhost" : "127.0.0.1";
};

export const API_URL =
  process.env.EXPO_PUBLIC_API_URL?.trim() ||
  `http://${getDevServerHost()}:${API_PORT}`;

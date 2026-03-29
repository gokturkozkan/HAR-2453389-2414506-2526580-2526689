const HUB_PROTOCOL = process.env.EXPO_PUBLIC_HAR_BACKEND_PROTOCOL ?? "http";
const HUB_HOST = process.env.EXPO_PUBLIC_HAR_HUB_HOST ?? "har-hub.local";
const HUB_PORT = process.env.EXPO_PUBLIC_HAR_BACKEND_PORT ?? "3000";

export const API_URL =
  process.env.EXPO_PUBLIC_API_URL ?? `${HUB_PROTOCOL}://${HUB_HOST}:${HUB_PORT}`;

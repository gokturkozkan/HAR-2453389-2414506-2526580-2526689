import type { ImageSourcePropType } from "react-native";

export const ACTIVITY_LABELS = [
  "standing",
  "sitting",
  "lying",
  "walking",
  "crouching",
  "x_pose",
  "punching",
  "turning",
] as const;

export type ActivityLabel = (typeof ACTIVITY_LABELS)[number];

export const ACTIVITY_LABEL_IMAGES: Partial<
  Record<ActivityLabel, ImageSourcePropType>
> = {
  crouching: require("@/assets/label-images/crouching.jpeg"),
  x_pose: require("@/assets/label-images/x_pose.jpeg"),
  punching: require("@/assets/label-images/punching.jpeg"),
  turning: require("@/assets/label-images/turning.jpeg"),
};

export const normalizeActivityLabel = (label?: string) =>
  String(label || "")
    .trim()
    .toLowerCase()
    .replace(/-/g, "_")
    .replace(/\s+/g, "_");

export const getActivityLabelImage = (
  label?: string
): ImageSourcePropType | undefined => {
  const normalized = normalizeActivityLabel(label) as ActivityLabel;
  return ACTIVITY_LABEL_IMAGES[normalized];
};

export const formatActivityLabel = (label: string) =>
  normalizeActivityLabel(label).replace(/_/g, " ");

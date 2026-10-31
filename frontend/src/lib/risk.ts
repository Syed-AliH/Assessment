import type { Risk } from "../api/types";

export const RISK_LABELS: Record<Risk, string> = {
  low: "Low",
  moderate: "Moderate",
  high: "High",
  severe: "Severe",
  no_travel: "No Travel",
  unknown: "Unknown",
};

// Lightness steps down with severity, so the scale still reads without hue.
export const RISK_COLORS: Record<Risk, string> = {
  low: "#58b58a",
  moderate: "#f2c230",
  high: "#ee8622",
  severe: "#d42f2a",
  no_travel: "#4a1042",
  unknown: "#9aa4af",
};

// Index matches the digit codes in the heatmap payload.
export const RISK_BY_CODE: Risk[] = ["low", "moderate", "high", "severe", "no_travel", "unknown"];

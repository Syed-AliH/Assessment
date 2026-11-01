import type { Heatmap, Risk } from "../api/types";

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

const WORST_FIRST: Risk[] = ["no_travel", "severe", "high", "moderate", "unknown"];

/** The heatmap in words, for anyone who cannot rely on its colours. */
export function corridorSummary(heatmap: Heatmap, hour: number): string {
  const counts = new Map<Risk, number>();
  for (const codes of heatmap.levels) {
    const risk = RISK_BY_CODE[codes.charCodeAt(hour) - 48];
    counts.set(risk, (counts.get(risk) ?? 0) + 1);
  }
  const parts = WORST_FIRST.filter((risk) => counts.has(risk)).map(
    (risk) => `${counts.get(risk)} ${RISK_LABELS[risk]}`,
  );
  if (!parts.length) return "Low risk across the corridor";
  return `${parts.join(" · ")} of ${heatmap.levels.length} areas`;
}

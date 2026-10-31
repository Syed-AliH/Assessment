import { describe, expect, it } from "vitest";
import type { Checkpoint } from "../api/types";
import { corridorSummary } from "../components/ForecastPanel";
import { formatDuration, formatOffset, formatTime } from "./format";
import { truckPositionAt } from "./truckPosition";

function checkpoint(lat: number, eta: string): Checkpoint {
  return {
    index: 0, miles: 0, lat, lon: -97, eta, represented_miles: 1, risk: "low", cause: null,
    load_adjusted: false, wind_mph: 1, gust_mph: 1, rain_in_hr: 0, snow_in_hr: 0,
  };
}

const PATH = [
  checkpoint(30, "2026-11-01T10:00:00Z"),
  checkpoint(31, "2026-11-01T11:00:00Z"),
  checkpoint(33, "2026-11-01T12:00:00Z"),
];

describe("truckPositionAt", () => {
  it("waits at the origin before departure", () => {
    expect(truckPositionAt(PATH, Date.parse("2026-11-01T09:00:00Z"))?.status).toBe("before");
  });
  it("interpolates within the right segment", () => {
    const position = truckPositionAt(PATH, Date.parse("2026-11-01T11:30:00Z"));
    expect(position?.lat).toBeCloseTo(32);
    expect(position?.status).toBe("moving");
  });
  it("stops at the destination", () => {
    const position = truckPositionAt(PATH, Date.parse("2026-11-02T00:00:00Z"));
    expect(position).toEqual({ lat: 33, lon: -97, status: "arrived" });
  });
  it("handles no checkpoints", () => {
    expect(truckPositionAt([], 0)).toBeNull();
  });
});

describe("format", () => {
  it("shows times in the origin zone", () => {
    expect(formatTime("2026-11-01T15:30:00Z", -300)).toBe("Sun 10:30 AM");
  });
  it("labels offsets", () => {
    expect(formatOffset(-300)).toBe("UTC−5");
    expect(formatOffset(-210)).toBe("UTC−3:30");
  });
  it("formats durations", () => {
    expect(formatDuration(1500)).toBe("25 min");
    expect(formatDuration(5400)).toBe("1 h 30 min");
  });
});

describe("corridorSummary", () => {
  const base = { start: "", hours: 1, step: 0.25, cells: [] as [number, number][] };
  it("reads calm hours plainly", () => {
    expect(corridorSummary({ ...base, levels: ["00"] }, 0)).toBe("Low risk across the corridor");
  });
  it("lists the worst risk first and counts areas", () => {
    const levels = ["00", "03", "24", "05"];
    expect(corridorSummary({ ...base, levels }, 1)).toBe("1 No Travel · 1 Severe · 1 Unknown of 4 areas");
  });
});

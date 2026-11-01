import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError, assessTrip, buildHeatmap, planTrip } from "../api/client";
import type { Analysis, Heatmap, TripPlan, TripRequest } from "../api/types";
import { fetchForecasts } from "../api/weather";

export type FieldErrors = Record<string, string>;

export type Phase = "routes" | "weather" | "risk";

export type HeatmapState =
  | { status: "idle" | "loading" }
  | { status: "error"; message: string }
  | { status: "ready"; heatmap: Heatmap };

function firstMessage(value: unknown): string {
  if (Array.isArray(value)) return firstMessage(value[0]);
  if (value && typeof value === "object") return firstMessage(Object.values(value)[0]);
  return String(value);
}

function toFieldErrors(fields: Record<string, unknown> | undefined): FieldErrors {
  return Object.fromEntries(
    Object.entries(fields ?? {}).map(([name, value]) => [name, firstMessage(value)]),
  );
}

function bestRoute(analysis: Analysis): string {
  const { route_id: chosen, least_bad_route_id: leastBad } = analysis.recommendation;
  return chosen ?? leastBad ?? analysis.routes[0].id;
}

/** Runs a trip: plan on the server, weather in the browser, risk on the server. */
export function useTrip() {
  const tripRequest = useRef<AbortController | null>(null);
  const heatmapRequest = useRef<AbortController | null>(null);
  const plan = useRef<TripPlan | null>(null);

  const [trip, setTrip] = useState<TripRequest | null>(null);
  const [analysis, setAnalysis] = useState<Analysis | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [phase, setPhase] = useState<Phase | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [fieldErrors, setFieldErrors] = useState<FieldErrors>({});
  const [heatmap, setHeatmap] = useState<HeatmapState>({ status: "idle" });

  const loadHeatmap = useCallback(async () => {
    if (!plan.current) return;
    const { analysis_id: analysisId, forecast } = plan.current;
    heatmapRequest.current?.abort();
    const controller = new AbortController();
    heatmapRequest.current = controller;
    setHeatmap({ status: "loading" });
    try {
      const weather = await fetchForecasts(forecast, forecast.cells, controller.signal);
      if (weather.failure) {
        setHeatmap({
          status: "error",
          message: weather.reason || "The corridor forecast could not be loaded.",
        });
        return;
      }
      const data = await buildHeatmap(analysisId, weather.locations, controller.signal);
      setHeatmap({ status: "ready", heatmap: data });
    } catch (failure) {
      if (failure instanceof ApiError) setHeatmap({ status: "error", message: failure.message });
    }
  }, []);

  const submit = useCallback(async (request: TripRequest) => {
    tripRequest.current?.abort();
    heatmapRequest.current?.abort();
    const controller = new AbortController();
    tripRequest.current = controller;
    setTrip(request);
    setPhase("routes");
    setError(null);
    setFieldErrors({});
    try {
      const planned = await planTrip(request, controller.signal);
      plan.current = planned;
      setPhase("weather");
      const { forecast } = planned;
      const weather = await fetchForecasts(forecast, forecast.points, controller.signal);
      setPhase("risk");
      const result = await assessTrip(planned.analysis_id, weather, controller.signal);
      setAnalysis(result);
      setSelectedId(bestRoute(result));
      setPhase(null);
      void loadHeatmap();
    } catch (failure) {
      if (failure instanceof DOMException) return; // Replaced by a newer trip.
      setPhase(null);
      if (failure instanceof ApiError) {
        setError(failure.message);
        setFieldErrors(toFieldErrors(failure.fields));
      } else {
        setError("Something went wrong. Try again.");
      }
    }
  }, [loadHeatmap]);

  useEffect(() => () => {
    tripRequest.current?.abort();
    heatmapRequest.current?.abort();
  }, []);

  return {
    trip,
    analysis,
    selectedId,
    setSelectedId,
    phase,
    error,
    fieldErrors,
    heatmap,
    submit,
    retryHeatmap: loadHeatmap,
  };
}

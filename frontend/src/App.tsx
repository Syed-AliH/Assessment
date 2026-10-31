import { useCallback, useEffect, useRef, useState } from "react";
import { analyzeTrip, ApiError, fetchHeatmap } from "./api/client";
import type { Analysis, TripRequest } from "./api/types";
import { ForecastPanel, type HeatmapState } from "./components/ForecastPanel";
import { Results } from "./components/Results";
import { TripForm, type FieldErrors } from "./components/TripForm";
import { truckPositionAt } from "./lib/truckPosition";
import { MapView } from "./map/MapView";
import type { TripMap } from "./map/TripMap";

const HOUR_MS = 3_600_000;
const STACKED_LAYOUT = "(max-width: 860px)";

function firstMessage(value: unknown): string {
  if (Array.isArray(value)) return firstMessage(value[0]);
  if (value && typeof value === "object") return firstMessage(Object.values(value)[0]);
  return String(value);
}

function fieldErrors(fields: Record<string, unknown> | undefined): FieldErrors {
  return Object.fromEntries(
    Object.entries(fields ?? {}).map(([name, value]) => [name, firstMessage(value)]),
  );
}

export default function App() {
  const map = useRef<TripMap | null>(null);
  const analysisRequest = useRef<AbortController | null>(null);
  const heatmapRequest = useRef<AbortController | null>(null);
  const hour = useRef(0);

  const [analysis, setAnalysis] = useState<Analysis | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [serverErrors, setServerErrors] = useState<FieldErrors>({});
  const [heatmap, setHeatmap] = useState<HeatmapState>({ status: "idle" });
  const [formOpen, setFormOpen] = useState(true);
  const [run, setRun] = useState(0);
  const lastTrip = useRef<TripRequest | null>(null);
  const results = useRef<HTMLDivElement>(null);

  const placeTruck = useCallback((current: Analysis, routeId: string) => {
    const route = current.routes.find((candidate) => candidate.id === routeId);
    const moment = Date.parse(current.departure) + hour.current * HOUR_MS;
    map.current?.setTruck(route ? truckPositionAt(route.checkpoints, moment) : null);
  }, []);

  const loadHeatmap = useCallback(async (analysisId: string) => {
    heatmapRequest.current?.abort();
    const controller = new AbortController();
    heatmapRequest.current = controller;
    setHeatmap({ status: "loading" });
    try {
      const data = await fetchHeatmap(analysisId, controller.signal);
      map.current?.setHeatmap(data);
      setHeatmap({ status: "ready", heatmap: data });
    } catch (failure) {
      if (failure instanceof ApiError) setHeatmap({ status: "error", message: failure.message });
    }
  }, []);

  const submit = useCallback(async (trip: TripRequest) => {
    analysisRequest.current?.abort();
    heatmapRequest.current?.abort();
    const controller = new AbortController();
    analysisRequest.current = controller;
    lastTrip.current = trip;
    setBusy(true);
    setError(null);
    setServerErrors({});
    try {
      const result = await analyzeTrip(trip, controller.signal);
      const best =
        result.recommendation.route_id ??
        result.recommendation.least_bad_route_id ??
        result.routes[0].id;
      hour.current = 0;
      setAnalysis(result);
      setSelectedId(best);
      setRun((count) => count + 1);
      setFormOpen(false);
      map.current?.setHeatmap(null);
      map.current?.setHour(0);
      setBusy(false);
      void loadHeatmap(result.analysis_id);
    } catch (failure) {
      if (failure instanceof ApiError) {
        setError(failure.message);
        setServerErrors(fieldErrors(failure.fields));
        setFormOpen(true);
        setBusy(false);
      } else if (!(failure instanceof DOMException)) {
        setError("Something went wrong. Try again.");
        setBusy(false);
      }
    }
  }, [loadHeatmap, placeTruck]);

  const selectRoute = useCallback((id: string) => {
    setSelectedId(id);
    map.current?.selectRoute(id);
    setAnalysis((current) => {
      if (current) placeTruck(current, id);
      return current;
    });
  }, [placeTruck]);

  const focusCheckpoint = useCallback((routeId: string, index: number) => {
    map.current?.focusCheckpoint(routeId, index);
    // On phones the map has scrolled away by the time a table row is tapped.
    if (window.matchMedia(STACKED_LAYOUT).matches) {
      document.querySelector(".map-area")?.scrollIntoView({ block: "start" });
    }
  }, []);

  const changeHour = useCallback((next: number) => {
    hour.current = next;
    map.current?.setHour(next);
    if (analysis && selectedId) placeTruck(analysis, selectedId);
  }, [analysis, selectedId, placeTruck]);

  // Runs after commit: the phone layout changes the map's size when results appear.
  useEffect(() => {
    if (!run || !analysis || !selectedId) return;
    map.current?.setAnalysis(analysis, selectedId);
    placeTruck(analysis, selectedId);
    // The submit button has just been hidden, so focus would otherwise be lost.
    results.current?.focus({ preventScroll: true });
  }, [run]);

  useEffect(() => () => {
    analysisRequest.current?.abort();
    heatmapRequest.current?.abort();
  }, []);

  return (
    <div className={`app${analysis ? " has-results" : ""}`}>
      <aside className="panel">
        <header className="panel-head">
          <h1>Weather-Aware Truck Routing</h1>
          {analysis && (
            <button type="button" className="link" aria-expanded={formOpen} onClick={() => setFormOpen((open) => !open)}>
              {formOpen ? "Hide trip details" : "Edit trip"}
            </button>
          )}
        </header>

        <div hidden={!formOpen}>
          <TripForm busy={busy} serverErrors={serverErrors} onSubmit={submit} />
        </div>

        {error && (
          <div className="alert" role="alert">
            <p>{error}</p>
            {!Object.keys(serverErrors).length && lastTrip.current && (
              <button type="button" className="link" onClick={() => submit(lastTrip.current!)}>Try again</button>
            )}
          </div>
        )}
        {busy && (
          <div role="status" className="loading">
            <p>Finding truck routes and reading the forecast at each checkpoint. Very long trips can take a minute.</p>
            <div className="skeleton" aria-hidden="true"><span /><span /><span /></div>
          </div>
        )}

        {analysis && selectedId && !busy && (
          <div ref={results} tabIndex={-1} aria-label="Trip results" role="region">
            <Results
              analysis={analysis}
              selectedId={selectedId}
              onSelect={selectRoute}
              onFocusCheckpoint={focusCheckpoint}
            />
          </div>
        )}
        {!analysis && !busy && !error && (
          <p className="intro">
            Enter a trip to compare up to three truck routes. Each route is checked against the
            forecast for the time the truck reaches each checkpoint.
          </p>
        )}
      </aside>

      <main id="map-area" className="map-area" tabIndex={-1}>
        <MapView mapRef={map} onSelectRoute={selectRoute} />
        <ForecastPanel
          key={run}
          state={heatmap}
          offset={analysis?.origin_utc_offset_minutes ?? 0}
          onHour={changeHour}
          onRetry={() => analysis && loadHeatmap(analysis.analysis_id)}
        />
      </main>
    </div>
  );
}

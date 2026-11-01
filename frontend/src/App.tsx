import { useCallback, useEffect, useRef, useState } from "react";
import { ForecastPanel } from "./components/ForecastPanel";
import { Icon } from "./components/Icon";
import { Results } from "./components/Results";
import { RiskGuide } from "./components/RiskGuide";
import { TripForm } from "./components/TripForm";
import { useTrip, type Phase } from "./hooks/useTrip";
import { truckPositionAt } from "./lib/truckPosition";
import { MapView } from "./map/MapView";
import type { TripMap } from "./map/TripMap";

const HOUR_MS = 3_600_000;
const STACKED_LAYOUT = "(max-width: 860px)";
const PHASES: [Phase, string][] = [
  ["routes", "Finding truck routes"],
  ["weather", "Reading the forecast along each route"],
  ["risk", "Scoring risk at each checkpoint"],
];

function Progress({ phase }: { phase: Phase }) {
  const current = PHASES.findIndex(([name]) => name === phase);
  return (
    <div role="status" className="loading">
      <ol className="phases">
        {PHASES.map(([name, label], index) => (
          <li key={name} className={index === current ? "is-active" : index < current ? "is-done" : ""}>
            {label}
          </li>
        ))}
      </ol>
      <div className="skeleton" aria-hidden="true"><span /><span /></div>
    </div>
  );
}

export default function App() {
  const map = useRef<TripMap | null>(null);
  const results = useRef<HTMLDivElement>(null);
  const hour = useRef(0);
  const {
    trip, analysis, selectedId, setSelectedId, phase, error, fieldErrors, heatmap, submit, retryHeatmap,
  } = useTrip();
  const [formOpen, setFormOpen] = useState(true);

  const busy = phase !== null;
  const offset = analysis?.origin_utc_offset_minutes ?? 0;

  const placeTruck = useCallback((routeId: string) => {
    const route = analysis?.routes.find((candidate) => candidate.id === routeId);
    if (!analysis || !route) return;
    const moment = Date.parse(analysis.departure) + hour.current * HOUR_MS;
    map.current?.setTruck(truckPositionAt(route.checkpoints, moment));
  }, [analysis]);

  const selectRoute = useCallback((id: string) => {
    setSelectedId(id);
    map.current?.selectRoute(id);
    placeTruck(id);
  }, [placeTruck, setSelectedId]);

  const focusCheckpoint = useCallback((routeId: string, index: number) => {
    map.current?.focusCheckpoint(routeId, index);
    // On phones the map has scrolled away by the time a checkpoint is tapped.
    if (window.matchMedia(STACKED_LAYOUT).matches) {
      document.querySelector(".map-area")?.scrollIntoView({ block: "start" });
    }
  }, []);

  const changeHour = useCallback((next: number) => {
    hour.current = next;
    map.current?.setHour(next);
    if (selectedId) placeTruck(selectedId);
  }, [selectedId, placeTruck]);

  // Runs after commit: the phone layout changes the map's size when results appear.
  useEffect(() => {
    if (!analysis || !selectedId) return;
    hour.current = 0;
    setFormOpen(false);
    map.current?.setHour(0);
    map.current?.setAnalysis(analysis, selectedId);
    placeTruck(selectedId);
    // The submit button is about to be hidden, so focus would otherwise be lost.
    results.current?.focus({ preventScroll: true });
    // A new analysis is the only trigger. Changing route must not refit the map.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [analysis]);

  useEffect(() => {
    if (error) setFormOpen(true);
  }, [error]);

  useEffect(() => {
    map.current?.setHeatmap(heatmap.status === "ready" ? heatmap.heatmap : null);
  }, [heatmap]);

  return (
    <div className={`app${analysis ? " has-results" : ""}`}>
      <aside className="panel">
        <header className="panel-head">
          <span className="brand-mark"><Icon name="truck" size={21} /></span>
          <div>
            <h1>Weather-Aware Truck Routing</h1>
            <p>Find the safest route for your load</p>
          </div>
        </header>

        <div className="panel-body">
          {analysis && trip && (
            <div className="trip-summary">
              <div>
                <b>{trip.origin.label} <Icon name="arrow" size={14} /> {trip.destination.label}</b>
                <small>{trip.load_lb.toLocaleString("en-US")} lb · every {trip.interval_miles} mi</small>
              </div>
              <button
                type="button"
                className="link edit-trip"
                aria-expanded={formOpen}
                onClick={() => setFormOpen((open) => !open)}
              >
                <Icon name="edit" size={15} /> {formOpen ? "Hide" : "Edit"}
              </button>
            </div>
          )}

          <div hidden={!formOpen}>
            <TripForm busy={busy} serverErrors={fieldErrors} onSubmit={submit} />
          </div>

          {error && (
            <div className="alert" role="alert">
              <p>{error}</p>
              {!Object.keys(fieldErrors).length && trip && (
                <button type="button" className="link" onClick={() => submit(trip)}>Try again</button>
              )}
            </div>
          )}

          {phase && <Progress phase={phase} />}

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

          {!busy && <RiskGuide />}
        </div>
      </aside>

      <main id="map-area" className="map-area" tabIndex={-1}>
        <MapView mapRef={map} onSelectRoute={selectRoute} />
        <ForecastPanel
          key={analysis?.analysis_id}
          state={heatmap}
          offset={offset}
          onHour={changeHour}
          onRetry={retryHeatmap}
        />
      </main>
    </div>
  );
}

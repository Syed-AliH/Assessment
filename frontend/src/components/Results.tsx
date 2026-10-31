import { memo } from "react";
import type { Analysis, Checkpoint, Recommendation, Risk, Route } from "../api/types";
import { formatDuration, formatMiles, formatOffset, formatTime } from "../lib/format";
import { RISK_COLORS, RISK_LABELS } from "../lib/risk";

const BANNER_TITLES: Record<Recommendation["status"], string> = {
  recommended: "Recommended route",
  no_safe_route: "No safe route",
  insufficient_data: "Not enough forecast data",
};

export function RiskPill({ risk }: { risk: Risk }) {
  return (
    <span className={`risk-pill risk-${risk}`}>
      <span className="risk-dot" style={{ background: RISK_COLORS[risk] }} />
      {RISK_LABELS[risk]}
    </span>
  );
}

function RecommendationBanner({ recommendation }: { recommendation: Recommendation }) {
  return (
    <section className={`banner banner-${recommendation.status}`} aria-live="polite">
      <h2>{BANNER_TITLES[recommendation.status]}</h2>
      <p>{recommendation.explanation}</p>
      {recommendation.warnings.map((warning) => (
        <p className="banner-warning" key={warning}>{warning}</p>
      ))}
    </section>
  );
}

function RiskBar({ route }: { route: Route }) {
  const { risk } = route;
  const segments: [Risk, number][] = [
    ["low", risk.low_miles],
    ["moderate", risk.moderate_miles],
    ["high", risk.high_miles],
    ["severe", risk.severe_miles],
    ["no_travel", risk.no_travel_miles],
    ["unknown", risk.unknown_miles],
  ];
  const present = segments.filter(([, miles]) => miles > 0);
  return (
    <>
      <div className="risk-bar" aria-hidden="true">
        {present.map(([level, miles]) => (
          <span key={level} style={{ flexGrow: miles, background: RISK_COLORS[level] }} />
        ))}
      </div>
      <p className="risk-text">
        {present.map(([level, miles]) => `${RISK_LABELS[level]} ${formatMiles(miles)}`).join(" · ")}
      </p>
    </>
  );
}

interface RouteCardProps {
  route: Route;
  badge: string | null;
  selected: boolean;
  offset: number;
  onSelect: (id: string) => void;
}

function RouteCard({ route, badge, selected, offset, onSelect }: RouteCardProps) {
  return (
    <button
      type="button"
      className={`route-card${selected ? " is-selected" : ""}`}
      aria-pressed={selected}
      onClick={() => onSelect(route.id)}
    >
      <span className="route-card-head">
        <strong>{route.label}</strong>
        {badge && <span className="badge">{badge}</span>}
      </span>
      <span className="route-card-stats">
        <strong>{formatDuration(route.travel_seconds)}</strong> · {formatMiles(route.length_miles)} · arrives {formatTime(route.arrival, offset)}
      </span>
      <RiskBar route={route} />
      <span className="route-card-foot">
        Average risk {route.risk.average_risk?.toFixed(2) ?? "unknown"} of 4
        {route.risk.coverage < 1 && ` · ${Math.round(route.risk.coverage * 100)}% forecast coverage`}
      </span>
    </button>
  );
}

function conditions(checkpoint: Checkpoint): string {
  if (checkpoint.risk === "unknown") return "No forecast";
  const parts = [`${Math.round(checkpoint.wind_mph ?? 0)} mph wind`];
  if (checkpoint.rain_in_hr) parts.push(`${checkpoint.rain_in_hr.toFixed(2)} in/hr rain`);
  if (checkpoint.snow_in_hr) parts.push(`${checkpoint.snow_in_hr.toFixed(2)} in/hr snow`);
  return parts.join(", ");
}

interface CheckpointTableProps {
  route: Route;
  offset: number;
  onFocus: (routeId: string, index: number) => void;
}

const CheckpointTable = memo(function CheckpointTable({ route, offset, onFocus }: CheckpointTableProps) {
  return (
    <section className="checkpoints">
      <h3>{route.label} checkpoints <span>times are {formatOffset(offset)}, the origin's zone</span></h3>
      <a className="skip-link" href="#map-area">Skip checkpoints, go to the map</a>
      <table>
        <thead>
          <tr><th scope="col">Mile</th><th scope="col">ETA</th><th scope="col">Risk</th><th scope="col">Forecast</th></tr>
        </thead>
        <tbody>
          {route.checkpoints.map((checkpoint) => (
            <tr key={checkpoint.index}>
              <td>
                <button
                  type="button"
                  className="link mile-link"
                  aria-label={`Show mile ${Math.round(checkpoint.miles)} on the map`}
                  onClick={() => onFocus(route.id, checkpoint.index)}
                >
                  {Math.round(checkpoint.miles)}
                </button>
              </td>
              <td>{formatTime(checkpoint.eta, offset)}</td>
              <td><RiskPill risk={checkpoint.risk} /></td>
              <td>
                {conditions(checkpoint)}
                {checkpoint.load_adjusted && <em> raised by load</em>}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
});

interface ResultsProps {
  analysis: Analysis;
  selectedId: string;
  onSelect: (id: string) => void;
  onFocusCheckpoint: (routeId: string, index: number) => void;
}

export function Results({ analysis, selectedId, onSelect, onFocusCheckpoint }: ResultsProps) {
  const { recommendation, routes, notices } = analysis;
  const offset = analysis.origin_utc_offset_minutes;
  const selected = routes.find((route) => route.id === selectedId) ?? routes[0];
  // Best first. The A, B, C names stay as they are, matching the map.
  const ordered = [...routes].sort(
    (a, b) =>
      recommendation.ranked_route_ids.indexOf(a.id) - recommendation.ranked_route_ids.indexOf(b.id),
  );

  return (
    <div className="results">
      <RecommendationBanner recommendation={recommendation} />
      {notices.length > 0 && (
        <ul className="notices">
          {notices.map((notice) => <li key={notice.code}>{notice.message}</li>)}
        </ul>
      )}
      <div className="route-cards">
        {ordered.map((route) => (
          <RouteCard
            key={route.id}
            route={route}
            badge={
              route.id === recommendation.route_id
                ? "Recommended"
                : route.id === recommendation.least_bad_route_id
                  ? "Least bad"
                  : null
            }
            selected={route.id === selected.id}
            offset={offset}
            onSelect={onSelect}
          />
        ))}
      </div>
      <CheckpointTable route={selected} offset={offset} onFocus={onFocusCheckpoint} />
    </div>
  );
}

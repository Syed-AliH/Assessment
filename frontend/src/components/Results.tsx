import { memo } from "react";
import type { Analysis, Checkpoint, Recommendation, Risk, Route } from "../api/types";
import { formatDuration, formatMiles, formatOffset, formatTime } from "../lib/format";
import { RISK_COLORS, RISK_LABELS } from "../lib/risk";
import { Icon } from "./Icon";

export function RiskPill({ risk }: { risk: Risk }) {
  return (
    <span className={`risk-pill risk-${risk}`}>
      <span className="risk-dot" style={{ background: RISK_COLORS[risk] }} />
      {RISK_LABELS[risk]}
    </span>
  );
}

function RecommendationBanner({ recommendation, routes }: { recommendation: Recommendation; routes: Route[] }) {
  const chosen = routes.find((route) => route.id === recommendation.route_id);
  const title =
    recommendation.status === "recommended" && chosen
      ? `Take ${chosen.label}`
      : recommendation.status === "no_safe_route"
        ? "No safe route"
        : "Not enough forecast data";
  // The heading already names the route, so the sentence need not repeat it.
  const reason = chosen
    ? recommendation.explanation.replace(`${chosen.label} is recommended: `, "")
    : recommendation.explanation;
  return (
    <section className={`banner banner-${recommendation.status}`}>
      <span className="banner-icon">
        <Icon name={recommendation.status === "recommended" ? "check" : "alert"} size={20} />
      </span>
      <div>
        <h2>{title}</h2>
        <p>{reason.charAt(0).toUpperCase() + reason.slice(1)}</p>
        {recommendation.warnings.map((warning) => (
          <p className="banner-warning" key={warning}>{warning}</p>
        ))}
      </div>
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
      <span className="risk-bar" aria-hidden="true">
        {present.map(([level, miles]) => (
          <span key={level} style={{ flexGrow: miles, background: RISK_COLORS[level] }} />
        ))}
      </span>
      <span className="risk-text">
        {present.map(([level, miles]) => (
          <span key={level}>
            <span className="risk-dot" style={{ background: RISK_COLORS[level] }} />
            {RISK_LABELS[level]} {formatMiles(miles)}
          </span>
        ))}
      </span>
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
        <span className="route-letter" aria-hidden="true">{route.label.slice(-1)}</span>
        <strong>{route.label}</strong>
        {badge && <span className="badge">{badge}</span>}
      </span>
      <span className="route-stats">
        <span><small>Drive time</small><b>{formatDuration(route.travel_seconds)}</b></span>
        <span><small>Distance</small><b>{formatMiles(route.length_miles)}</b></span>
        <span><small>Arrives</small><b>{formatTime(route.arrival, offset)}</b></span>
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
  if (checkpoint.load_adjusted) parts.push("raised by load");
  return parts.join(" · ");
}

interface CheckpointListProps {
  route: Route;
  offset: number;
  onFocus: (routeId: string, index: number) => void;
}

const CheckpointList = memo(function CheckpointList({ route, offset, onFocus }: CheckpointListProps) {
  return (
    <section className="checkpoints">
      <div className="section-head">
        <h3>{route.label} checkpoints</h3>
        <span>Times in {formatOffset(offset)}, the origin's zone</span>
      </div>
      <a className="skip-link" href="#map-area">Skip checkpoints, go to the map</a>
      <ol>
        {route.checkpoints.map((checkpoint) => (
          <li key={checkpoint.index}>
            <button type="button" className="checkpoint" onClick={() => onFocus(route.id, checkpoint.index)}>
              <span className="checkpoint-marker" style={{ background: RISK_COLORS[checkpoint.risk] }} />
              <span className="checkpoint-main">
                <b>Mile {Math.round(checkpoint.miles).toLocaleString("en-US")}</b>
                <small>{conditions(checkpoint)}</small>
              </span>
              <span className="checkpoint-side">
                <RiskPill risk={checkpoint.risk} />
                <small>{formatTime(checkpoint.eta, offset)}</small>
              </span>
            </button>
          </li>
        ))}
      </ol>
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
      <RecommendationBanner recommendation={recommendation} routes={routes} />
      {notices.length > 0 && (
        <ul className="notices">
          {notices.map((notice) => (
            <li key={notice.code}><Icon name="info" size={16} /><span>{notice.message}</span></li>
          ))}
        </ul>
      )}
      <div className="section-head"><h3>Compare routes</h3></div>
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
      <CheckpointList route={selected} offset={offset} onFocus={onFocusCheckpoint} />
    </div>
  );
}

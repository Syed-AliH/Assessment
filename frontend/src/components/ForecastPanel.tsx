import { useMemo, useState } from "react";
import type { Risk } from "../api/types";
import { formatOffset, formatTime } from "../lib/format";
import type { HeatmapState } from "../hooks/useTrip";
import { corridorSummary, RISK_COLORS, RISK_LABELS } from "../lib/risk";

const LEGEND: Risk[] = ["low", "moderate", "high", "severe", "no_travel", "unknown"];

interface Props {
  state: HeatmapState;
  offset: number;
  onHour: (hour: number) => void;
  onRetry: () => void;
}

/** Holds the hour itself, so dragging re-renders only this panel. */
export function ForecastPanel({ state, offset, onHour, onRetry }: Props) {
  const [hour, setHour] = useState(0);
  const summary = useMemo(
    () => (state.status === "ready" ? corridorSummary(state.heatmap, hour) : ""),
    [state, hour],
  );

  if (state.status === "idle") return null;

  return (
    <section className="forecast-panel" aria-label="Forecast heatmap">
      {state.status === "loading" && <p className="forecast-status">Loading the corridor forecast…</p>}
      {state.status === "error" && (
        <p className="forecast-status" role="alert">
          {state.message} <button type="button" className="link" onClick={onRetry}>Retry</button>
        </p>
      )}
      {state.status === "ready" && (
        <>
          <div className="forecast-head">
            <div>
              <label htmlFor="forecast-hour">Forecast after departure</label>
              <p className="forecast-summary">{summary}</p>
            </div>
            <output htmlFor="forecast-hour">
              <strong>+{hour} h</strong>{" "}
              {formatTime(new Date(Date.parse(state.heatmap.start) + hour * 3_600_000).toISOString(), offset)}{" "}
              <span>({formatOffset(offset)})</span>
            </output>
          </div>
          <input
            id="forecast-hour"
            type="range"
            min={0}
            max={state.heatmap.hours}
            step={1}
            value={hour}
            aria-valuetext={`${hour} hours after departure. ${summary}`}
            onChange={(event) => {
              const next = Number(event.target.value);
              setHour(next);
              onHour(next);
            }}
          />
          <div className="forecast-scale" aria-hidden="true">
            <span>0 h</span><span>24 h</span><span>48 h</span>
          </div>
          <ul className="legend">
            {LEGEND.map((risk) => (
              <li key={risk}>
                <span style={{ background: RISK_COLORS[risk] }} />
                {RISK_LABELS[risk]}
              </li>
            ))}
            <li><span className="legend-truck" />Truck at this hour</li>
          </ul>
        </>
      )}
    </section>
  );
}

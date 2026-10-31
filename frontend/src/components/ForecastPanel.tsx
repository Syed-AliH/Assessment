import { useState } from "react";
import type { Heatmap, Risk } from "../api/types";
import { formatOffset, formatTime } from "../lib/format";
import { RISK_COLORS, RISK_LABELS } from "../lib/risk";

const LEGEND: Risk[] = ["low", "moderate", "high", "severe", "no_travel", "unknown"];

export type HeatmapState =
  | { status: "idle" | "loading" }
  | { status: "error"; message: string }
  | { status: "ready"; heatmap: Heatmap };

interface Props {
  state: HeatmapState;
  offset: number;
  onHour: (hour: number) => void;
  onRetry: () => void;
}

/** Holds the hour itself, so dragging re-renders only this panel. */
export function ForecastPanel({ state, offset, onHour, onRetry }: Props) {
  const [hour, setHour] = useState(0);

  if (state.status === "idle") return null;

  return (
    <section className="forecast-panel" aria-label="Forecast heatmap">
      {state.status === "loading" && <p className="forecast-status">Loading corridor forecast. Long trips can take a minute.</p>}
      {state.status === "error" && (
        <p className="forecast-status" role="alert">
          {state.message} <button type="button" className="link" onClick={onRetry}>Retry</button>
        </p>
      )}
      {state.status === "ready" && (
        <>
          <div className="forecast-head">
            <label htmlFor="forecast-hour">Forecast after departure</label>
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
            aria-valuetext={`${hour} hours after departure`}
            onChange={(event) => {
              const next = Number(event.target.value);
              setHour(next);
              onHour(next);
            }}
          />
          <ul className="legend">
            {LEGEND.map((risk) => (
              <li key={risk}>
                <span style={{ background: RISK_COLORS[risk] }} />
                {RISK_LABELS[risk]}
              </li>
            ))}
          </ul>
        </>
      )}
    </section>
  );
}

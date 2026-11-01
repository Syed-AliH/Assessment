import { useEffect, useState, type FormEvent } from "react";
import type { Place, TripRequest } from "../api/types";
import type { FieldErrors } from "../hooks/useTrip";
import { toLocalInputValue } from "../lib/format";
import { Icon } from "./Icon";
import { PlaceInput } from "./PlaceInput";

const INTERVALS = [10, 25, 50] as const;
const MAX_LOAD_LB = 80_000;
const MAX_DEPARTURE_DAYS = 14;
const DAY_MS = 86_400_000;
const HEAVY_LOAD_NO_TRAVEL_LB = 30_000;
const HEAVY_LOAD_SEVERE_LB = 40_000;

interface Props {
  busy: boolean;
  serverErrors: FieldErrors;
  onSubmit: (trip: TripRequest) => void;
}

function focusFirstInvalid() {
  requestAnimationFrame(() => {
    document.querySelector<HTMLElement>('.trip-form [aria-invalid="true"]')?.focus();
  });
}

export function TripForm({ busy, serverErrors, onSubmit }: Props) {
  const [origin, setOrigin] = useState<Place | null>(null);
  const [destination, setDestination] = useState<Place | null>(null);
  const [leaveNow, setLeaveNow] = useState(true);
  const [departure, setDeparture] = useState(() => toLocalInputValue(new Date(Date.now() + 3_600_000)));
  const [load, setLoad] = useState("35000");
  const [interval, setInterval] = useState<TripRequest["interval_miles"]>(25);
  const [errors, setErrors] = useState<FieldErrors>({});
  const [swaps, setSwaps] = useState(0);

  const shown = { ...serverErrors, ...errors };

  useEffect(() => {
    if (Object.keys(serverErrors).length) focusFirstInvalid();
  }, [serverErrors]);

  function swap() {
    setOrigin(destination);
    setDestination(origin);
    setSwaps((count) => count + 1); // Remounts the inputs with the swapped text.
  }

  const weight = Number(load);
  const loadHint =
    weight > HEAVY_LOAD_SEVERE_LB
      ? "Over 40,000 lb: the strictest wind limits apply."
      : weight > HEAVY_LOAD_NO_TRAVEL_LB
        ? "Over 30,000 lb: stricter wind limits apply."
        : null;

  function validate(): FieldErrors {
    const found: FieldErrors = {};
    if (!origin) found.origin = "Choose a place from the list.";
    if (!destination) found.destination = "Choose a place from the list.";
    if (load.trim() === "" || !Number.isFinite(weight) || weight < 0 || weight > MAX_LOAD_LB) {
      found.load_lb = `Enter a load from 0 to ${MAX_LOAD_LB.toLocaleString("en-US")} lb.`;
    }
    if (!leaveNow && !departure) found.departure = "Choose a departure time.";
    return found;
  }

  function submit(event: FormEvent) {
    event.preventDefault();
    const found = validate();
    setErrors(found);
    if (Object.keys(found).length) {
      focusFirstInvalid();
      return;
    }
    onSubmit({
      origin: origin!,
      destination: destination!,
      departure: leaveNow ? null : `${departure}:00`,
      load_lb: Number(load),
      interval_miles: interval,
    });
  }

  const now = Date.now();

  return (
    <form className="trip-form" onSubmit={submit} noValidate>
      <div className="route-inputs">
        <PlaceInput key={`origin-${swaps}`} label="Origin" value={origin} onChange={setOrigin} error={shown.origin} />
        <PlaceInput key={`destination-${swaps}`} label="Destination" value={destination} onChange={setDestination} error={shown.destination} end />
        <button type="button" className="swap" aria-label="Swap origin and destination" title="Swap origin and destination" onClick={swap}>
          <Icon name="swap" />
        </button>
      </div>

      <fieldset className="field">
        <legend>Departure</legend>
        <div className="segmented">
          <label className={leaveNow ? "is-on" : ""}>
            <input type="radio" name="when" checked={leaveNow} onChange={() => setLeaveNow(true)} />
            Leave now
          </label>
          <label className={!leaveNow ? "is-on" : ""}>
            <input type="radio" name="when" checked={!leaveNow} onChange={() => setLeaveNow(false)} />
            Later
          </label>
        </div>
        {!leaveNow && (
          <>
            <input
              type="datetime-local"
              aria-label="Departure time, local to the origin"
              aria-invalid={Boolean(shown.departure)}
              value={departure}
              min={toLocalInputValue(new Date(now))}
              max={toLocalInputValue(new Date(now + MAX_DEPARTURE_DAYS * DAY_MS))}
              onChange={(event) => setDeparture(event.target.value)}
            />
            <p className="field-hint">Local time at the origin, up to {MAX_DEPARTURE_DAYS} days out.</p>
          </>
        )}
        {shown.departure && <p className="field-error">{shown.departure}</p>}
      </fieldset>

      <div className="field-row">
        <div className="field">
          <label htmlFor="load">Load weight (lb)</label>
          <div className="input-suffix"><input
            id="load"
            type="number"
            inputMode="numeric"
            min={0}
            max={MAX_LOAD_LB}
            step={500}
            aria-invalid={Boolean(shown.load_lb)}
            aria-describedby={shown.load_lb ? "load-error" : undefined}
            value={load}
            onChange={(event) => setLoad(event.target.value)}
          /><span aria-hidden="true">lb</span></div>
          {shown.load_lb && <p id="load-error" className="field-error">{shown.load_lb}</p>}
        </div>

        <fieldset className="field">
          <legend>Check weather every</legend>
          <div className="segmented">
            {INTERVALS.map((miles) => (
              <label key={miles} className={interval === miles ? "is-on" : ""}>
                <input
                  type="radio"
                  name="interval"
                  checked={interval === miles}
                  onChange={() => setInterval(miles)}
                />
                {miles} mi
              </label>
            ))}
          </div>
        </fieldset>
      </div>

      {loadHint && <p className="field-hint">{loadHint}</p>}

      <button className="primary" type="submit" disabled={busy}>
        {busy ? "Checking routes…" : <>Compare routes <Icon name="arrow" /></>}
      </button>
    </form>
  );
}

import { useEffect, useId, useRef, useState } from "react";
import { ApiError, searchPlaces } from "../api/client";
import type { Place } from "../api/types";

const DEBOUNCE_MS = 250;
const MIN_QUERY_LENGTH = 3;

interface Props {
  label: string;
  value: Place | null;
  onChange: (place: Place | null) => void;
  error?: string;
}

export function PlaceInput({ label, value, onChange, error }: Props) {
  const id = useId();
  const [text, setText] = useState(value?.label ?? "");
  const [options, setOptions] = useState<Place[]>([]);
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(-1);
  const [status, setStatus] = useState<"idle" | "searching" | "empty" | "failed">("idle");
  const chosenText = useRef(value?.label ?? "");

  useEffect(() => {
    const query = text.trim();
    if (query.length < MIN_QUERY_LENGTH || query === chosenText.current) {
      setOptions([]);
      setStatus("idle");
      return;
    }
    const controller = new AbortController();
    setStatus("searching");
    const timer = setTimeout(async () => {
      try {
        const places = await searchPlaces(query, controller.signal);
        setOptions(places);
        setActive(-1);
        setStatus(places.length ? "idle" : "empty");
        setOpen(true);
      } catch (failure) {
        if (failure instanceof ApiError) {
          setStatus("failed");
          setOpen(true);
        }
      }
    }, DEBOUNCE_MS);
    return () => {
      clearTimeout(timer);
      controller.abort();
    };
  }, [text]);

  function choose(place: Place) {
    chosenText.current = place.label;
    setText(place.label);
    setOptions([]);
    setOpen(false);
    onChange(place);
  }

  function onKeyDown(event: React.KeyboardEvent) {
    if (event.key === "Escape") {
      setOpen(false);
    } else if (open && options.length && event.key === "ArrowDown") {
      event.preventDefault();
      setActive((current) => (current + 1) % options.length);
    } else if (open && options.length && event.key === "ArrowUp") {
      event.preventDefault();
      setActive((current) => (current <= 0 ? options.length : current) - 1);
    } else if (event.key === "Enter" && open && options.length) {
      event.preventDefault();
      choose(options[Math.max(active, 0)]);
    }
  }

  const showList = open && (options.length > 0 || status === "empty" || status === "failed");

  return (
    <div className="field place-field">
      <label htmlFor={id}>{label}</label>
      <input
        id={id}
        role="combobox"
        aria-expanded={showList}
        aria-controls={`${id}-list`}
        aria-autocomplete="list"
        aria-activedescendant={active >= 0 ? `${id}-${active}` : undefined}
        aria-invalid={Boolean(error)}
        aria-describedby={error ? `${id}-error` : undefined}
        autoComplete="off"
        placeholder="City or address"
        value={text}
        onChange={(event) => {
          setText(event.target.value);
          if (value) onChange(null);
        }}
        onKeyDown={onKeyDown}
        onFocus={() => setOpen(true)}
        onBlur={() => setOpen(false)}
      />
      {showList && (
        <ul id={`${id}-list`} role="listbox" className="place-options">
          {options.map((place, index) => (
            <li
              key={`${place.label}-${place.lat}-${place.lon}`}
              id={`${id}-${index}`}
              role="option"
              aria-selected={index === active}
              className={index === active ? "is-active" : undefined}
              // Fires before the input's blur closes the list.
              onMouseDown={(event) => {
                event.preventDefault();
                choose(place);
              }}
            >
              {place.label}
            </li>
          ))}
          {status === "empty" && <li className="place-message">No matches in the US or Canada</li>}
          {status === "failed" && <li className="place-message">Place search is unavailable right now</li>}
        </ul>
      )}
      {error && <p id={`${id}-error`} className="field-error">{error}</p>}
    </div>
  );
}

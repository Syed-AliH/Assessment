import { useEffect, useRef, type RefObject } from "react";
import "maplibre-gl/dist/maplibre-gl.css";
import { TripMap } from "./TripMap";

interface Props {
  mapRef: RefObject<TripMap | null>;
  onSelectRoute: (id: string) => void;
}

/** Hosts the map. TripMap is driven directly so that React never re-renders it. */
export function MapView({ mapRef, onSelectRoute }: Props) {
  const container = useRef<HTMLDivElement>(null);
  const select = useRef(onSelectRoute);
  select.current = onSelectRoute;

  useEffect(() => {
    const map = new TripMap(container.current!, (id) => select.current(id));
    mapRef.current = map;
    return () => {
      map.destroy();
      mapRef.current = null;
    };
  }, [mapRef]);

  return <div ref={container} className="map" role="region" aria-label="Route map" />;
}

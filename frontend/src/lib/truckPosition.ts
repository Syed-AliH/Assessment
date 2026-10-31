import type { Checkpoint } from "../api/types";

export interface TruckPosition {
  lat: number;
  lon: number;
  status: "before" | "moving" | "arrived";
}

/** Where the truck is at a moment, straight-lined between checkpoints. */
export function truckPositionAt(checkpoints: Checkpoint[], moment: number): TruckPosition | null {
  if (!checkpoints.length) return null;
  const times = checkpoints.map((checkpoint) => Date.parse(checkpoint.eta));
  const first = checkpoints[0];
  const last = checkpoints[checkpoints.length - 1];
  if (moment < times[0]) return { lat: first.lat, lon: first.lon, status: "before" };
  if (moment >= times[times.length - 1]) return { lat: last.lat, lon: last.lon, status: "arrived" };

  let low = 0;
  let high = times.length - 1;
  while (high - low > 1) {
    const middle = (low + high) >> 1;
    if (times[middle] <= moment) low = middle;
    else high = middle;
  }
  const span = times[high] - times[low];
  const t = span > 0 ? (moment - times[low]) / span : 0;
  return {
    lat: checkpoints[low].lat + (checkpoints[high].lat - checkpoints[low].lat) * t,
    lon: checkpoints[low].lon + (checkpoints[high].lon - checkpoints[low].lon) * t,
    status: "moving",
  };
}

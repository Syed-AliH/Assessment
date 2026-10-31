// Mirrors the JSON built in backend/trips/services/{analyze,heatmap}.py.

export type Risk = "low" | "moderate" | "high" | "severe" | "no_travel" | "unknown";

export interface Place {
  label: string;
  lat: number;
  lon: number;
}

export interface TripRequest {
  origin: Place;
  destination: Place;
  departure: string | null; // origin-local, no offset. null means now.
  load_lb: number;
  interval_miles: 10 | 25 | 50;
}

export interface Checkpoint {
  index: number;
  miles: number;
  lat: number;
  lon: number;
  eta: string;
  represented_miles: number;
  risk: Risk;
  cause: "wind" | "rain" | "snow" | null;
  load_adjusted: boolean;
  wind_mph: number | null;
  gust_mph: number | null;
  rain_in_hr: number | null;
  snow_in_hr: number | null;
}

export interface RouteRisk {
  no_travel_miles: number;
  severe_miles: number;
  high_miles: number;
  moderate_miles: number;
  low_miles: number;
  unknown_miles: number;
  average_risk: number | null;
  coverage: number;
}

export interface Route {
  id: string;
  label: string;
  length_miles: number;
  travel_seconds: number;
  traffic_delay_seconds: number;
  arrival: string;
  geometry: [number, number][]; // [lon, lat]
  risk: RouteRisk;
  checkpoints: Checkpoint[];
}

export interface Recommendation {
  status: "recommended" | "no_safe_route" | "insufficient_data";
  route_id: string | null;
  least_bad_route_id: string | null;
  ranked_route_ids: string[];
  deciding_factor: string | null;
  explanation: string;
  warnings: string[];
}

export interface Notice {
  code: string;
  message: string;
}

export interface Analysis {
  analysis_id: string;
  departure: string;
  origin_utc_offset_minutes: number;
  load_lb: number;
  interval_miles: number;
  routes: Route[];
  recommendation: Recommendation;
  notices: Notice[];
}

export interface Heatmap {
  start: string;
  hours: number;
  step: number;
  cells: [number, number][]; // [lat, lon] of the cell centre
  levels: string[]; // one digit per hour: 0-4 risk level, 5 unknown
}

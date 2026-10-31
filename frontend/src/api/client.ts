import type { Analysis, ForecastResult, Heatmap, Place, TripPlan, TripRequest } from "./types";

export class ApiError extends Error {
  constructor(
    public code: string,
    message: string,
    public fields?: Record<string, unknown>,
  ) {
    super(message);
  }
}

async function request<T>(url: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(url, init);
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") throw error;
    throw new ApiError("network", "Could not reach the server. Check your connection and try again.");
  }
  const body = await response.json().catch(() => null);
  if (!response.ok) {
    const failure = body?.error;
    throw new ApiError(
      failure?.code ?? "request_failed",
      failure?.message ?? "Something went wrong. Try again.",
      failure?.fields,
    );
  }
  return body as T;
}

export async function searchPlaces(query: string, signal: AbortSignal): Promise<Place[]> {
  const data = await request<{ results: Place[] }>(
    `/api/geocode?q=${encodeURIComponent(query)}`,
    { signal },
  );
  return data.results;
}

function post<T>(url: string, body: unknown, signal: AbortSignal): Promise<T> {
  return request<T>(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
    signal,
  });
}

export function planTrip(trip: TripRequest, signal: AbortSignal): Promise<TripPlan> {
  return post<TripPlan>("/api/trips/plan", trip, signal);
}

export function assessTrip(analysisId: string, forecast: ForecastResult, signal: AbortSignal): Promise<Analysis> {
  return post<Analysis>(`/api/trips/${analysisId}/assess`, forecast, signal);
}

export function buildHeatmap(analysisId: string, locations: unknown[], signal: AbortSignal): Promise<Heatmap> {
  return post<Heatmap>(`/api/trips/${analysisId}/heatmap`, { locations }, signal);
}

import type { Analysis, Heatmap, Place, TripRequest } from "./types";

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

export function analyzeTrip(trip: TripRequest, signal: AbortSignal): Promise<Analysis> {
  return request<Analysis>("/api/trips/analyze", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(trip),
    signal,
  });
}

export function fetchHeatmap(analysisId: string, signal: AbortSignal): Promise<Heatmap> {
  return request<Heatmap>(`/api/trips/${analysisId}/heatmap`, { signal });
}

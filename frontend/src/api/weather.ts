import type { ForecastRequest, ForecastResult } from "./types";

const CHUNK_SIZE = 100;
const WORKERS = 4;
const RETRIES = 2;
const BACKOFF_MS = 1500;

class RateLimit extends Error {}

function wait(ms: number, signal: AbortSignal): Promise<void> {
  return new Promise((resolve, reject) => {
    const timer = setTimeout(resolve, ms);
    signal.addEventListener("abort", () => {
      clearTimeout(timer);
      reject(new DOMException("Aborted", "AbortError"));
    }, { once: true });
  });
}

async function fetchChunk(
  request: ForecastRequest,
  points: [number, number][],
  signal: AbortSignal,
): Promise<unknown[]> {
  const query = new URLSearchParams({
    ...request.params,
    latitude: points.map(([lat]) => lat).join(","),
    longitude: points.map(([, lon]) => lon).join(","),
  });
  for (let attempt = 0; ; attempt += 1) {
    try {
      const response = await fetch(`${request.url}?${query}`, { signal });
      if (response.status === 429) {
        // Retrying only spends more quota, and the reason says when it resets.
        const body = await response.json().catch(() => null);
        throw new RateLimit(body?.reason ?? "");
      }
      if (!response.ok) throw new Error(`Weather service returned ${response.status}`);
      const data = await response.json();
      // A single location comes back as an object, several as a list.
      const locations: { hourly?: unknown }[] = Array.isArray(data) ? data : [data];
      if (locations.length !== points.length) throw new Error("Wrong number of locations");
      return locations.map((location) => ({ hourly: location.hourly }));
    } catch (error) {
      const aborted = error instanceof DOMException && error.name === "AbortError";
      if (aborted || error instanceof RateLimit || attempt >= RETRIES) throw error;
      await wait(BACKOFF_MS * (attempt + 1), signal);
    }
  }
}

/** Download forecasts for points, in order. Points that fail come back as null. */
export async function fetchForecasts(
  request: ForecastRequest,
  points: [number, number][],
  signal: AbortSignal,
): Promise<ForecastResult> {
  const chunks: [number, number][][] = [];
  for (let i = 0; i < points.length; i += CHUNK_SIZE) chunks.push(points.slice(i, i + CHUNK_SIZE));

  const locations: unknown[] = new Array(points.length).fill(null);
  let next = 0;
  let succeeded = chunks.length === 0;
  let limit: RateLimit | null = null;

  async function worker() {
    while (next < chunks.length) {
      const index = next;
      next += 1;
      try {
        const results = await fetchChunk(request, chunks[index], signal);
        results.forEach((location, offset) => {
          locations[index * CHUNK_SIZE + offset] = location;
        });
        succeeded = true;
      } catch (error) {
        if (error instanceof DOMException && error.name === "AbortError") throw error;
        if (error instanceof RateLimit) limit = error;
      }
    }
  }

  await Promise.all(Array.from({ length: WORKERS }, worker));
  if (succeeded) return { locations };
  const failure = limit as RateLimit | null;
  return {
    locations: [],
    failure: failure ? "rate_limited" : "unavailable",
    reason: failure?.message.slice(0, 200) ?? "",
  };
}

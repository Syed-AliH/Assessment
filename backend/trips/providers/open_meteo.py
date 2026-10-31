"""Open-Meteo hourly forecasts.

Only the variables the risk rules need are requested, in fixed units, with
conversions in one place. A location with bad data is dropped, so callers see
it as missing rather than calm.
"""
import threading
import time
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone

import httpx

from ..domain.forecast_time import HourlySeries
from ..domain.geo import LatLon
from .base import ProviderError, RateLimited, UpstreamUnavailable

FREE_URL = "https://api.open-meteo.com/v1/forecast"
PAID_URL = "https://customer-api.open-meteo.com/v1/forecast"
HOURLY = "wind_speed_10m,wind_gusts_10m,rain,showers,snowfall"
MAX_FORECAST_DAYS = 16
MM_PER_INCH = 25.4
CM_PER_INCH = 2.54

CHUNK_SIZE = 100
WORKERS = 4
RETRIES = 2
BACKOFF_SECONDS = 1.5
# The published limit is 600 a minute. How multi-location calls count is not
# documented, so each location is budgeted as one call.
LOCATIONS_PER_MINUTE = 500
# Long enough to span a full window. A slow answer beats silent gaps in the
# forecast, and only the largest trips ever wait.
MAX_BUDGET_WAIT_SECONDS = 75.0


class MinuteBudget:
    """Sliding-window limiter, shared by the threads of one process."""

    def __init__(self, per_minute: int, window: float = 60.0):
        self._per_minute = per_minute
        self._window = window
        self._spent: deque[tuple[float, int]] = deque()
        self._lock = threading.Lock()

    def _try_spend(self, amount: int) -> float:
        """Spend now and return 0, or return how long to wait."""
        now = time.monotonic()
        with self._lock:
            while self._spent and now - self._spent[0][0] >= self._window:
                self._spent.popleft()
            used = sum(count for _, count in self._spent)
            if used + amount <= self._per_minute or not self._spent:
                self._spent.append((now, amount))
                return 0.0
            return self._window - (now - self._spent[0][0])

    def acquire(self, amount: int, max_wait: float = MAX_BUDGET_WAIT_SECONDS) -> None:
        deadline = time.monotonic() + max_wait
        while True:
            wait = self._try_spend(amount)
            if wait == 0.0:
                return
            if time.monotonic() + wait > deadline:
                raise RateLimited("Weather request budget used up for this minute")
            time.sleep(wait)


_budget = MinuteBudget(LOCATIONS_PER_MINUTE)


def _sum_or_none(a: float | None, b: float | None) -> float | None:
    return None if a is None or b is None else a + b


def _scaled(values: list[float | None], divisor: float) -> list[float | None]:
    return [None if value is None else value / divisor for value in values]


def parse_location(raw: dict) -> HourlySeries | None:
    try:
        hourly = raw["hourly"]
        times = hourly["time"]
        wind = hourly["wind_speed_10m"]
        gust = hourly["wind_gusts_10m"]
        rain = hourly["rain"]
        showers = hourly["showers"]
        snow = hourly["snowfall"]
    except (KeyError, TypeError):
        return None
    if not times or any(len(column) != len(times) for column in (wind, gust, rain, showers, snow)):
        return None
    return HourlySeries(
        times=times,
        wind_mph=wind,
        gust_mph=gust,
        rain_in=_scaled([_sum_or_none(a, b) for a, b in zip(rain, showers)], MM_PER_INCH),
        snow_in=_scaled(snow, CM_PER_INCH),
    )


def clamp_range(start: date, end: date, today: date) -> tuple[date, date] | None:
    """Trim to the forecast window. None if nothing is left."""
    last = today + timedelta(days=MAX_FORECAST_DAYS - 1)
    start, end = max(start, today), min(end, last)
    return (start, end) if start <= end else None


class OpenMeteoClient:
    """Implements WeatherProvider."""

    def __init__(self, api_key: str = "", timeout: float = 20.0, budget: MinuteBudget = _budget):
        self._key = api_key
        self._url = PAID_URL if api_key else FREE_URL
        self._timeout = timeout
        self._budget = budget

    def _fetch_chunk(
        self, client: httpx.Client, chunk: list[LatLon], start: date, end: date
    ) -> dict[LatLon, HourlySeries]:
        params = {
            "latitude": ",".join(f"{lat:g}" for lat, _ in chunk),
            "longitude": ",".join(f"{lon:g}" for _, lon in chunk),
            "hourly": HOURLY,
            "wind_speed_unit": "mph",
            "timeformat": "unixtime",
            "timezone": "GMT",
            "start_date": start.isoformat(),
            "end_date": end.isoformat(),
        }
        if self._key:
            params["apikey"] = self._key

        self._budget.acquire(len(chunk))
        for attempt in range(RETRIES + 1):
            try:
                response = client.get(self._url, params=params)
            except httpx.HTTPError as error:
                failure: ProviderError = UpstreamUnavailable(
                    f"Could not reach Open-Meteo: {type(error).__name__}"
                )
            else:
                if response.status_code == 200:
                    return self._parse(response, chunk)
                if response.status_code == 429:
                    failure = RateLimited("Open-Meteo rate limit reached")
                elif response.status_code >= 500:
                    failure = UpstreamUnavailable(f"Open-Meteo returned {response.status_code}")
                else:
                    raise UpstreamUnavailable(f"Open-Meteo rejected the request: {response.text[:200]}")
            if attempt < RETRIES:
                time.sleep(BACKOFF_SECONDS * (attempt + 1))
        raise failure

    @staticmethod
    def _parse(response: httpx.Response, chunk: list[LatLon]) -> dict[LatLon, HourlySeries]:
        try:
            data = response.json()
        except ValueError:
            raise UpstreamUnavailable("Open-Meteo returned an unreadable response") from None
        # A single location comes back as an object, several as a list.
        locations = data if isinstance(data, list) else [data]
        if len(locations) != len(chunk):
            raise UpstreamUnavailable("Open-Meteo returned the wrong number of locations")
        parsed = ((point, parse_location(raw)) for point, raw in zip(chunk, locations))
        return {point: series for point, series in parsed if series is not None}

    def forecast(
        self, points: list[LatLon], start: date, end: date
    ) -> dict[LatLon, HourlySeries]:
        today = datetime.now(timezone.utc).date()
        window = clamp_range(start, end, today)
        if not points or window is None:
            return {}
        chunks = [points[i : i + CHUNK_SIZE] for i in range(0, len(points), CHUNK_SIZE)]
        result: dict[LatLon, HourlySeries] = {}
        errors = []
        with httpx.Client(timeout=self._timeout) as client:
            with ThreadPoolExecutor(max_workers=WORKERS) as pool:
                futures = [
                    pool.submit(self._fetch_chunk, client, chunk, *window) for chunk in chunks
                ]
                for future in futures:
                    try:
                        result.update(future.result())
                    except ProviderError as error:
                        errors.append(error)
        # One bad chunk still leaves usable data. Its points read as missing.
        if errors and not result:
            raise errors[0]
        return result

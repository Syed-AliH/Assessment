# Weather-Aware Truck Routing

A React and Django app that helps a truck driver choose the safest route. It compares up to three truck routes against the forecast for the time the truck reaches each checkpoint, then recommends one and says why.

## How it works

1. **Routes.** TomTom truck routing, using gross weight, departure time and traffic. If it returns fewer than three distinct routes, the app adds via-point detours. It never pads with near-duplicates, and says so when fewer than three exist.
2. **Checkpoints.** Every 10, 25 or 50 miles, plus both ends. ETAs interpolate between TomTom's per-instruction timings, so city and highway speeds are respected.
3. **Weather.** Open-Meteo's hourly forecast, read at each checkpoint's ETA.
4. **Risk.** The worst of wind, rain and snow after the load rules, in `backend/trips/domain/risk.py`.
5. **Recommendation.** Ranked in `backend/trips/domain/ranking.py`, with an explanation naming the criterion that decided it.
6. **Heatmap.** Risk on a grid around the routes for each hour from 0 to 48. All 49 hours load once, so the slider changes one paint property and makes no network calls.

```
backend/trips/
  domain/      Pure logic: risk, ranking, sampling, forecast timing, corridor grid
  providers/   TomTom and Open-Meteo adapters behind vendor-neutral interfaces
  services/    Orchestration and caching
frontend/src/
  api/         Typed client and the JSON contract
  components/  Form, results, forecast slider
  map/         MapLibre layers, driven outside React so that it never re-renders
```

### API

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/geocode?q=` | Place search (US and Canada) |
| POST | `/api/trips/analyze` | Routes, checkpoints, risk, recommendation, `analysis_id` |
| GET | `/api/trips/{analysis_id}/heatmap` | 49 hours of risk per grid cell |

Failures always have the shape `{"error": {"code", "message", "fields?"}}`.

## Rule decisions

The brief leaves these open. Each one is covered by tests.

| Question | Decision |
|---|---|
| No Travel is not in the ranking list | It ranks first. A route with any No Travel miles is never recommended. If every route has some, the app says there is no safe route and names the least bad. |
| Bands share edges (rain 0.25 is Moderate and High) | The lower bound is inclusive, so the shared value takes the worse class. The top of Severe stays inclusive because No Travel is strictly greater than. |
| Wind bands skip decimals (34.5 mph) | Ranges are continuous: `[25,35) [35,45) [45,55) ≥55`. Nothing is rounded. |
| Several conditions at once | Worst one wins, and it is named. |
| Load rules | `>30,000` and `>40,000` are strict, and they apply to wind only. 45–54 mph at or under 30,000 lb stays Severe. |
| Sustained wind or gusts | Sustained `wind_speed_10m` drives risk. Gusts are displayed only. |
| 10 / 25 / 50 miles | User-selectable, default 25. |
| Risk miles | Each checkpoint owns the stretch between the midpoints to its neighbours, so class miles add up to route length. |
| Hourly data | Open-Meteo rain and snow are sums for the hour ending at the timestamp, so 14:20 reads the 15:00 value. Wind is instantaneous and is interpolated. |
| Ranking noise | Miles compare in whole sampling intervals and average risk to 2 decimals, so a sampling artefact cannot beat a much faster route. Non-zero miles never tie with zero. |
| Average risk | Mile-weighted: Low 0, Moderate 1, High 2, Severe 3, No Travel 4. |
| Missing forecast | Unknown, never Low. Left out of the average and shown with coverage. A route under 50% coverage cannot be recommended. |
| Load vs vehicle weight | Risk rules use load. TomTom needs gross weight, so `TRUCK_TARE_LB` (default 33,000, an assumption) is added. |
| Slider start | Hour 0 is the departure time, labelled with the clock time. |
| Departure range | Up to 14 days out: the 16-day forecast less the 48-hour slider. |
| Time zones | Departure is local to the origin, and all times display in the origin's zone. |

## Known limits

- ETAs assume continuous driving with no rest stops. The app says so on trips over 11 hours, because hours-of-service rules would shift both arrival times and the weather met.
- Freezing rain, visibility and official weather alerts are not modelled, since the brief does not rate them.
- Hourly forecasts smooth out short bursts. A single-cell convective forecast can look alarming for one hour and is low-confidence by nature.
- The free Open-Meteo API is for non-commercial use and allows 600 calls a minute and 10,000 a day. The app budgets one call per location, so very long trips at 10-mile sampling can take a couple of minutes on a cold cache. It waits rather than dropping data. Set `OPEN_METEO_API_KEY` for commercial use.

## Running locally

Needs Python 3.10+, Node 22 and a free key from [developer.tomtom.com](https://developer.tomtom.com).

```sh
cd backend
python -m venv .venv
.venv/Scripts/activate          # macOS/Linux: source .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env            # add TOMTOM_API_KEY
python manage.py runserver

cd ../frontend
npm ci
npm run dev                     # http://localhost:5173
```

## Tests

```sh
cd backend && python -m pytest
cd frontend && npm test
```

### End-to-end tests

Playwright drives the built app. To run without a TomTom key, point the backend at the test-only OSRM provider. That uses live weather and real road geometry, but car routing.

```sh
cd frontend && npm run build && npx playwright install chromium
cd ../backend
DJANGO_DEBUG=true ROUTING_PROVIDER=tests.support.osrm_provider.OsrmRouting \
  GEOCODER=tests.support.osrm_provider.FixedGeocoder python manage.py runserver --noreload
cd ../frontend && npm run e2e
```

Add `E2E_GPU=1` for hardware rendering (Windows). The default software renderer overstates slider timings several times over.

## Deploying

The Dockerfile builds one image: Django with gunicorn serves both the API and the built React app, so keys stay server-side and no CORS is needed. `render.yaml` describes a Render service. Set `TOMTOM_API_KEY` there. Elsewhere, also set `DJANGO_SECRET_KEY` and `DJANGO_ALLOWED_HOSTS`. It runs one process with threads so that the weather limiter sees every request.

Third-party services: [TomTom](https://developer.tomtom.com), [Open-Meteo](https://open-meteo.com), [OpenFreeMap](https://openfreemap.org) tiles, [MapLibre GL](https://maplibre.org).

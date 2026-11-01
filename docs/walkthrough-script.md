# Loom walkthrough script (about 8 minutes)

Open the site first so the server is awake, and look for a stormy corridor on the day. A real one makes the risk logic far easier to show than a calm day.

## 1. The problem (30 s)
A driver needs the safest route, not just the fastest. The risk depends on the weather where the truck will be when it gets there, and on how heavy the load is.

## 2. Run a trip (2 min)
- Enter Dallas to Houston, 35,000 lb, leave now, every 25 miles.
- Point out the recommendation sentence: it names the criterion that decided it.
- Open "How risk is scored" to show the rules behind the result.
- Click through the route cards. The map, checkpoints and truck marker follow.
- Click a checkpoint row to show the ETA and the forecast for that moment.

## 3. Load changes the answer (1 min)
- Rerun a windy trip with 30,000 lb, then 30,001 lb.
- Explain the 45–54 mph rule: Severe becomes No Travel just over the line.

## 4. Heatmap (1 min)
- Drag the slider from 0 to 48. Say that it makes no network calls: all 49 hours load once, and each step only repaints a small canvas.
- Show the truck icon moving with the slider, so the driver sees the weather and the truck position together.
- Read the summary line above the slider, which gives the heatmap in words.
- Explain why it isn't MapLibre's heatmap layer: that sums point density, which would show risk that does not exist. This one paints real risk per cell into a canvas, and the GPU blends the cells.

## 5. Logic decisions worth defending (2 min)
Open `backend/trips/domain/ranking.py` and `risk.py`.
- No Travel is not in the brief's ranking list, so a literal build could recommend a route with No Travel miles. It ranks first here.
- Shared band edges take the worse class.
- Missing weather is Unknown, never Low.
- Rain is a sum for the preceding hour, so 14:20 reads the 15:00 value.
- Risk miles are bucketed to the sampling interval, so sampling noise cannot beat a much faster route.

## 6. Architecture (1 min)
Pure domain code, providers behind interfaces, services for orchestration. Explain the plan, browser weather, assess flow: each visitor spends their own Open-Meteo quota, and the server still makes every risk decision. Show the OSRM test provider as proof that a vendor can be swapped without touching the logic.

## 7. Limits (30 s)
ETAs assume continuous driving, and the app says so on long trips. Long trips share forecasts between nearby checkpoints to stay within the free quota, and the app says that too.

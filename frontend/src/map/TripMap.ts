import type { FeatureCollection } from "geojson";
import * as maplibregl from "maplibre-gl";
import workerUrl from "maplibre-gl/dist/maplibre-gl-worker.mjs?worker&url";
import type { Analysis, Checkpoint, Heatmap, Route } from "../api/types";
import { formatDuration, formatMiles, formatOffset, formatTime } from "../lib/format";
import { RISK_BY_CODE, RISK_COLORS, RISK_LABELS } from "../lib/risk";
import type { TruckPosition } from "../lib/truckPosition";

// MapLibre 6 keeps its worker in a separate file, which has to be bundled and registered.
maplibregl.setWorkerUrl(workerUrl);

const STYLE_URL = "https://tiles.openfreemap.org/styles/positron";
const US_CENTER: [number, number] = [-97, 39];
const SELECTED_ROUTE_COLOR = "#14344f";
const OTHER_ROUTE_COLOR = "#7b8a99";

// Low stays faint so that the dangerous cells stand out.
const HEAT_FILL: Record<string, string> = {
  low: "rgba(88, 181, 138, 0.16)",
  moderate: "rgba(242, 194, 48, 0.5)",
  high: "rgba(238, 134, 34, 0.6)",
  severe: "rgba(212, 47, 42, 0.68)",
  no_travel: "rgba(74, 16, 66, 0.78)",
  unknown: "rgba(154, 164, 175, 0.3)",
};

const EMPTY: FeatureCollection = { type: "FeatureCollection", features: [] };

function heatColor(hour: number): maplibregl.ExpressionSpecification {
  const stops = RISK_BY_CODE.flatMap((risk, code) => [code, HEAT_FILL[risk]]);
  return ["match", ["get", `h${hour}`], ...stops, "rgba(0,0,0,0)"] as unknown as maplibregl.ExpressionSpecification;
}

function heatFeatures(heatmap: Heatmap): FeatureCollection {
  const half = heatmap.step / 2;
  return {
    type: "FeatureCollection",
    features: heatmap.cells.map(([lat, lon], index) => {
      const properties: Record<string, number> = {};
      const codes = heatmap.levels[index];
      for (let hour = 0; hour <= heatmap.hours; hour += 1) {
        properties[`h${hour}`] = codes.charCodeAt(hour) - 48;
      }
      return {
        type: "Feature",
        properties,
        geometry: {
          type: "Polygon",
          coordinates: [[
            [lon - half, lat - half],
            [lon + half, lat - half],
            [lon + half, lat + half],
            [lon - half, lat + half],
            [lon - half, lat - half],
          ]],
        },
      };
    }),
  };
}

function checkpointPopup(checkpoint: Checkpoint, route: Route, offset: number): HTMLElement {
  const root = document.createElement("div");
  root.className = "popup";
  const add = (className: string, text: string) => {
    const line = document.createElement("div");
    line.className = className;
    line.textContent = text;
    root.append(line);
  };
  add("popup-title", `${route.label}, mile ${Math.round(checkpoint.miles)}`);
  add("popup-risk", RISK_LABELS[checkpoint.risk]);
  add("", `ETA ${formatTime(checkpoint.eta, offset)} (${formatOffset(offset)})`);
  if (checkpoint.risk === "unknown") {
    add("", "No forecast available");
  } else {
    add("", `Wind ${checkpoint.wind_mph} mph, gusts ${checkpoint.gust_mph} mph`);
    add("", `Rain ${checkpoint.rain_in_hr} in/hr, snow ${checkpoint.snow_in_hr} in/hr`);
    if (checkpoint.load_adjusted) add("", "Raised by the load weight rules");
  }
  return root;
}

export class TripMap {
  private map: maplibregl.Map;
  private loaded = false;
  private analysis: Analysis | null = null;
  private selectedId: string | null = null;
  private heatmap: Heatmap | null = null;
  private hour = 0;
  private hourFrame = 0;
  private labels: maplibregl.Marker[] = [];
  private truck: maplibregl.Marker;
  private popup = new maplibregl.Popup({ closeButton: true, maxWidth: "260px" });

  constructor(container: HTMLElement, private onSelectRoute: (id: string) => void) {
    this.map = new maplibregl.Map({
      container,
      style: STYLE_URL,
      center: US_CENTER,
      zoom: 3.4,
      attributionControl: { compact: true },
    });
    this.map.addControl(new maplibregl.NavigationControl({ showCompass: false }), "top-right");

    const truckElement = document.createElement("div");
    truckElement.className = "truck-marker";
    truckElement.setAttribute("aria-hidden", "true");
    this.truck = new maplibregl.Marker({ element: truckElement });

    this.map.on("load", () => {
      this.addLayers();
      this.loaded = true;
      this.draw();
      this.drawHeatmap();
    });
  }

  private addLayers(): void {
    const map = this.map;
    const firstLabel = map.getStyle().layers.find((layer) => layer.type === "symbol")?.id;

    map.addSource("heat", { type: "geojson", data: EMPTY, buffer: 0, tolerance: 0 });
    map.addSource("routes", { type: "geojson", data: EMPTY });
    map.addSource("checkpoints", { type: "geojson", data: EMPTY });

    map.addLayer(
      {
        id: "heat",
        type: "fill",
        source: "heat",
        paint: { "fill-color": heatColor(0), "fill-antialias": false },
      },
      firstLabel,
    );
    map.addLayer({
      id: "routes-other",
      type: "line",
      source: "routes",
      layout: { "line-cap": "round", "line-join": "round" },
      paint: { "line-color": OTHER_ROUTE_COLOR, "line-width": 3.5, "line-opacity": 0.85 },
    });
    map.addLayer({
      id: "route-selected-casing",
      type: "line",
      source: "routes",
      layout: { "line-cap": "round", "line-join": "round" },
      paint: { "line-color": "#ffffff", "line-width": 8 },
    });
    map.addLayer({
      id: "route-selected",
      type: "line",
      source: "routes",
      layout: { "line-cap": "round", "line-join": "round" },
      paint: { "line-color": SELECTED_ROUTE_COLOR, "line-width": 5 },
    });
    map.addLayer({
      id: "routes-hit",
      type: "line",
      source: "routes",
      paint: { "line-color": "#000000", "line-width": 18, "line-opacity": 0 },
    });
    map.addLayer({
      id: "checkpoints-other",
      type: "circle",
      source: "checkpoints",
      layout: { "circle-sort-key": ["get", "rank"] },
      paint: {
        "circle-radius": ["interpolate", ["linear"], ["zoom"], 3, 1.5, 8, 5],
        "circle-color": ["get", "color"],
        "circle-stroke-color": "#ffffff",
        "circle-stroke-width": ["interpolate", ["linear"], ["zoom"], 3, 0, 7, 1],
      },
    });
    map.addLayer({
      id: "checkpoints-selected",
      type: "circle",
      source: "checkpoints",
      layout: { "circle-sort-key": ["get", "rank"] },
      paint: {
        "circle-radius": ["interpolate", ["linear"], ["zoom"], 3, 2.5, 8, 8],
        "circle-color": ["get", "color"],
        "circle-stroke-color": "#ffffff",
        "circle-stroke-width": ["interpolate", ["linear"], ["zoom"], 3, 0.5, 7, 1.5],
      },
    });

    map.on("click", "routes-hit", (event) => {
      const clickedCheckpoint = map.queryRenderedFeatures(event.point, {
        layers: ["checkpoints-selected", "checkpoints-other"],
      }).length;
      const id = event.features?.[0]?.properties?.id;
      if (id && !clickedCheckpoint) this.onSelectRoute(id);
    });
    for (const layer of ["checkpoints-selected", "checkpoints-other"]) {
      map.on("click", layer, (event) => {
        const properties = event.features?.[0]?.properties;
        if (properties) this.openCheckpoint(properties.route, properties.index);
      });
      map.on("mouseenter", layer, () => (map.getCanvas().style.cursor = "pointer"));
      map.on("mouseleave", layer, () => (map.getCanvas().style.cursor = ""));
    }
    map.on("mouseenter", "routes-hit", () => (map.getCanvas().style.cursor = "pointer"));
    map.on("mouseleave", "routes-hit", () => (map.getCanvas().style.cursor = ""));
  }

  setAnalysis(analysis: Analysis | null, selectedId: string | null): void {
    this.analysis = analysis;
    this.selectedId = selectedId;
    this.popup.remove();
    this.draw();
    if (analysis) this.fit(analysis.routes);
  }

  selectRoute(id: string): void {
    this.selectedId = id;
    this.popup.remove();
    this.applySelection();
    this.styleLabels();
  }

  private draw(): void {
    if (!this.loaded) return;
    const routes = this.analysis?.routes ?? [];
    (this.map.getSource("routes") as maplibregl.GeoJSONSource).setData({
      type: "FeatureCollection",
      features: routes.map((route) => ({
        type: "Feature",
        properties: { id: route.id },
        geometry: { type: "LineString", coordinates: route.geometry },
      })),
    });
    (this.map.getSource("checkpoints") as maplibregl.GeoJSONSource).setData({
      type: "FeatureCollection",
      features: routes.flatMap((route) =>
        route.checkpoints.map((checkpoint) => ({
          type: "Feature" as const,
          properties: {
            route: route.id,
            index: checkpoint.index,
            color: RISK_COLORS[checkpoint.risk],
            // Danger paints on top where points overlap, and Unknown stays visible.
            rank: RISK_BY_CODE.indexOf(checkpoint.risk),
          },
          geometry: { type: "Point" as const, coordinates: [checkpoint.lon, checkpoint.lat] },
        })),
      ),
    });
    this.applySelection();
    this.drawLabels(routes);
  }

  private applySelection(): void {
    if (!this.loaded) return;
    const id = this.selectedId ?? "";
    const isSelected = ["==", ["get", "id"], id] as maplibregl.FilterSpecification;
    const notSelected = ["!=", ["get", "id"], id] as maplibregl.FilterSpecification;
    this.map.setFilter("routes-other", notSelected);
    this.map.setFilter("route-selected-casing", isSelected);
    this.map.setFilter("route-selected", isSelected);
    this.map.setFilter("checkpoints-selected", ["==", ["get", "route"], id]);
    this.map.setFilter("checkpoints-other", ["!=", ["get", "route"], id]);
  }

  private drawLabels(routes: Route[]): void {
    this.labels.forEach((label) => label.remove());
    this.labels = routes.map((route, index) => {
      // Spread along the trip, so that labels on a shared highway do not stack.
      const fraction = (index + 1) / (routes.length + 1);
      const [lon, lat] = route.geometry[Math.floor(route.geometry.length * fraction)];
      const element = document.createElement("button");
      element.type = "button";
      element.className = "route-label";
      element.dataset.route = route.id;
      const title = document.createElement("strong");
      title.textContent = route.label;
      const detail = document.createElement("span");
      detail.textContent = `${formatDuration(route.travel_seconds)} · ${formatMiles(route.length_miles)}`;
      const risk = document.createElement("span");
      const { no_travel_miles: noTravel, severe_miles: severe, high_miles: high } = route.risk;
      risk.textContent = noTravel > 0
        ? `${Math.round(noTravel)} No Travel mi`
        : `${Math.round(severe)} Severe · ${Math.round(high)} High mi`;
      element.append(title, detail, risk);
      element.addEventListener("click", (event) => {
        event.stopPropagation();
        this.onSelectRoute(route.id);
      });
      return new maplibregl.Marker({ element, anchor: "bottom", offset: [0, -8] })
        .setLngLat([lon, lat])
        .addTo(this.map);
    });
    this.styleLabels();
  }

  private styleLabels(): void {
    for (const label of this.labels) {
      const element = label.getElement();
      element.classList.toggle("is-selected", element.dataset.route === this.selectedId);
    }
  }

  private fit(routes: Route[]): void {
    const bounds = new maplibregl.LngLatBounds();
    routes.forEach((route) => route.geometry.forEach((point) => bounds.extend(point)));
    const compact = this.map.getContainer().clientWidth < 600;
    this.map.fitBounds(bounds, {
      padding: compact
        ? { top: 90, bottom: 110, left: 30, right: 30 }
        : { top: 90, bottom: 130, left: 70, right: 70 },
      duration: 500,
    });
  }

  openCheckpoint(routeId: string, index: number): void {
    const route = this.analysis?.routes.find((candidate) => candidate.id === routeId);
    const checkpoint = route?.checkpoints[index];
    if (!route || !checkpoint || !this.analysis) return;
    this.popup
      .setLngLat([checkpoint.lon, checkpoint.lat])
      .setDOMContent(checkpointPopup(checkpoint, route, this.analysis.origin_utc_offset_minutes))
      .addTo(this.map);
  }

  focusCheckpoint(routeId: string, index: number): void {
    const checkpoint = this.analysis?.routes.find((r) => r.id === routeId)?.checkpoints[index];
    if (!checkpoint) return;
    this.map.easeTo({ center: [checkpoint.lon, checkpoint.lat], duration: 400 });
    this.openCheckpoint(routeId, index);
  }

  setHeatmap(heatmap: Heatmap | null): void {
    this.heatmap = heatmap;
    this.drawHeatmap();
  }

  private drawHeatmap(): void {
    if (!this.loaded) return;
    const data = this.heatmap ? heatFeatures(this.heatmap) : EMPTY;
    (this.map.getSource("heat") as maplibregl.GeoJSONSource).setData(data);
    this.map.setPaintProperty("heat", "fill-color", heatColor(this.hour));
  }

  /** Paint only: no data moves, and rapid slider input collapses to one frame. */
  setHour(hour: number): void {
    this.hour = hour;
    if (this.hourFrame || !this.loaded) return;
    this.hourFrame = requestAnimationFrame(() => {
      this.hourFrame = 0;
      const started = performance.now();
      this.map.setPaintProperty("heat", "fill-color", heatColor(this.hour));
      performance.measure("heat-set", { start: started, end: performance.now() });
      this.map.once("render", () => {
        performance.measure("heat-update", { start: started, end: performance.now() });
      });
    });
  }

  setTruck(position: TruckPosition | null): void {
    if (position) this.truck.setLngLat([position.lon, position.lat]).addTo(this.map);
    else this.truck.remove();
  }

  resize(): void {
    this.map.resize();
  }

  destroy(): void {
    cancelAnimationFrame(this.hourFrame);
    this.map.remove();
  }
}

import type { FeatureCollection } from "geojson";
import * as maplibregl from "maplibre-gl";
import workerUrl from "maplibre-gl/dist/maplibre-gl-worker.mjs?worker&url";
import type { Analysis, Checkpoint, Heatmap, Route } from "../api/types";
import { formatDuration, formatMiles, formatOffset, formatTime } from "../lib/format";
import { RISK_BY_CODE, RISK_COLORS, RISK_LABELS } from "../lib/risk";
import type { TruckPosition } from "../lib/truckPosition";
import { buildRasterGrid, paintHour, type RasterGrid } from "./heatRaster";

// MapLibre 6 keeps its worker in a separate file, which has to be bundled and registered.
maplibregl.setWorkerUrl(workerUrl);

const STYLE_URL = "https://tiles.openfreemap.org/styles/positron";
const US_CENTER: [number, number] = [-97, 39];
const SELECTED_ROUTE_COLOR = "#1d4ed8";
const STACKED_WIDTH = 860;
const PANEL_CLEARANCE = 470;
const TRUCK_ICON =
  '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M1 5h13v11H1zM14 9h4l4 4v3h-8zM6 19a2 2 0 1 0 0-4 2 2 0 0 0 0 4zM18 19a2 2 0 1 0 0-4 2 2 0 0 0 0 4z"/></svg>';
const OTHER_ROUTE_COLOR = "#7b8a99";

const HEAT_LAYER = "heat";
const EMPTY: FeatureCollection = { type: "FeatureCollection", features: [] };

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
    if (checkpoint.cause) add("", `Risk set by ${checkpoint.cause}`);
    if (checkpoint.load_adjusted) add("", "Raised by the load weight rules");
  }
  return root;
}

/** Calm checkpoints stay small, so that risky ones stand out on a long trip. */
function checkpointRadius(
  calmFar: number,
  riskyFar: number,
  calmNear: number,
  riskyNear: number,
): maplibregl.ExpressionSpecification {
  const size = (calm: number, risky: number) => ["case", ["==", ["get", "rank"], 0], calm, risky];
  return [
    "interpolate", ["linear"], ["zoom"],
    3, size(calmFar, riskyFar),
    8, size(calmNear, riskyNear),
  ] as unknown as maplibregl.ExpressionSpecification;
}

export class TripMap {
  private map: maplibregl.Map;
  private loaded = false;
  private analysis: Analysis | null = null;
  private selectedId: string | null = null;
  private heatmap: Heatmap | null = null;
  private heatGrid: RasterGrid | null = null;
  private heatCanvas = document.createElement("canvas");
  private heatImage: ImageData | null = null;
  private firstLabelLayer: string | undefined;
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
    truckElement.innerHTML = TRUCK_ICON;
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
    this.firstLabelLayer = map.getStyle().layers.find((layer) => layer.type === "symbol")?.id;

    map.addSource("routes", { type: "geojson", data: EMPTY });
    map.addSource("checkpoints", { type: "geojson", data: EMPTY });

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
        "circle-radius": checkpointRadius(1.5, 3, 5, 7),
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
        "circle-radius": checkpointRadius(2.5, 5, 8, 10),
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
    this.map.resize();
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
    const compact = this.map.getContainer().clientWidth < STACKED_WIDTH;
    this.map.fitBounds(bounds, {
      padding: compact
        ? { top: 50, bottom: 30, left: 30, right: 30 }
        : { top: 90, bottom: 210, left: PANEL_CLEARANCE, right: 70 },
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

  private removeHeatLayer(): void {
    if (this.map.getLayer(HEAT_LAYER)) this.map.removeLayer(HEAT_LAYER);
    if (this.map.getSource(HEAT_LAYER)) this.map.removeSource(HEAT_LAYER);
  }

  private drawHeatmap(): void {
    if (!this.loaded) return;
    this.removeHeatLayer();
    this.heatGrid = null;
    if (!this.heatmap?.cells.length) return;

    const grid = buildRasterGrid(this.heatmap);
    this.heatGrid = grid;
    this.heatCanvas.width = grid.width;
    this.heatCanvas.height = grid.height;
    this.heatImage = new ImageData(grid.width, grid.height);
    this.paintHeat();
    this.map.addSource(HEAT_LAYER, {
      type: "canvas",
      canvas: this.heatCanvas,
      animate: false,
      coordinates: [
        [grid.west, grid.north],
        [grid.east, grid.north],
        [grid.east, grid.south],
        [grid.west, grid.south],
      ],
    });
    this.map.addLayer(
      {
        id: HEAT_LAYER,
        type: "raster",
        source: HEAT_LAYER,
        // The GPU blends neighbouring cells, which gives a smooth surface for free.
        paint: { "raster-resampling": "linear", "raster-fade-duration": 0 },
      },
      this.firstLabelLayer,
    );
  }

  private paintHeat(): void {
    if (!this.heatGrid || !this.heatmap || !this.heatImage) return;
    paintHour(this.heatGrid, this.heatmap.levels, this.hour, this.heatImage.data);
    this.heatCanvas.getContext("2d")?.putImageData(this.heatImage, 0, 0);
  }

  /** Repaints a few KB of pixels, and rapid slider input collapses to one frame. */
  setHour(hour: number): void {
    this.hour = hour;
    if (this.hourFrame || !this.loaded) return;
    this.hourFrame = requestAnimationFrame(() => {
      this.hourFrame = 0;
      const started = performance.now();
      this.paintHeat();
      const source = this.map.getSource(HEAT_LAYER) as maplibregl.CanvasSource | undefined;
      // A paused canvas source only uploads when playing, so play for one prepare.
      source?.play();
      source?.pause();
      this.map.triggerRepaint();
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

  destroy(): void {
    cancelAnimationFrame(this.hourFrame);
    this.map.remove();
  }
}

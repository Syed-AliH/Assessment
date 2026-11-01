import type { Heatmap } from "../api/types";

// Red, green, blue, alpha per risk code. Low stays faint so that danger stands out.
const HEAT_RGBA: [number, number, number, number][] = [
  [88, 181, 138, 44],
  [242, 194, 48, 140],
  [238, 134, 34, 165],
  [212, 47, 42, 185],
  [74, 16, 66, 210],
  [154, 164, 175, 80],
];
const NO_CELL = -1;

function mercatorY(lat: number): number {
  return Math.log(Math.tan(Math.PI / 4 + (lat * Math.PI) / 360));
}

function latitudeOf(y: number): number {
  return ((2 * Math.atan(Math.exp(y)) - Math.PI / 2) * 180) / Math.PI;
}

export interface RasterGrid {
  width: number;
  height: number;
  north: number;
  south: number;
  west: number;
  east: number;
  /** Heatmap cell index for each pixel, or -1 where there is no cell. */
  pixels: Int32Array;
}

/**
 * Lay grid cells out as pixels, with an empty margin so the surface fades out.
 *
 * MapLibre stretches an image linearly in Mercator space, so pixel rows are
 * spaced evenly in Mercator and each looks up its latitude. Spacing them evenly
 * in latitude would misplace weather by a whole cell on a long trip.
 */
export function buildRasterGrid(heatmap: Heatmap): RasterGrid {
  const { step, cells } = heatmap;
  const rows = cells.map(([lat]) => Math.floor(lat / step));
  const columns = cells.map(([, lon]) => Math.floor(lon / step));
  const minRow = Math.min(...rows) - 1;
  const maxRow = Math.max(...rows) + 1;
  const minColumn = Math.min(...columns) - 1;
  const maxColumn = Math.max(...columns) + 1;

  const south = minRow * step;
  const north = (maxRow + 1) * step;
  const width = maxColumn - minColumn + 1;
  const rowCount = maxRow - minRow + 1;
  // Oversampled, so that no row of cells falls between two pixel rows.
  const height = rowCount * 2;

  const cellAt = new Map(cells.map((_, index) => [`${rows[index]}:${columns[index]}`, index]));
  const pixels = new Int32Array(width * height).fill(NO_CELL);
  const top = mercatorY(north);
  const bottom = mercatorY(south);
  for (let y = 0; y < height; y += 1) {
    const lat = latitudeOf(top + ((y + 0.5) / height) * (bottom - top));
    const row = Math.floor(lat / step);
    for (let x = 0; x < width; x += 1) {
      pixels[y * width + x] = cellAt.get(`${row}:${minColumn + x}`) ?? NO_CELL;
    }
  }
  return {
    width,
    height,
    north,
    south,
    west: minColumn * step,
    east: (maxColumn + 1) * step,
    pixels,
  };
}

/** Write one hour into RGBA pixels. Allocates nothing, as it runs per slider step. */
export function paintHour(
  grid: RasterGrid,
  levels: string[],
  hour: number,
  rgba: Uint8ClampedArray,
): void {
  const { pixels } = grid;
  for (let index = 0; index < pixels.length; index += 1) {
    const cell = pixels[index];
    const offset = index * 4;
    if (cell === NO_CELL) {
      rgba[offset + 3] = 0;
      continue;
    }
    const color = HEAT_RGBA[levels[cell].charCodeAt(hour) - 48];
    rgba[offset] = color[0];
    rgba[offset + 1] = color[1];
    rgba[offset + 2] = color[2];
    rgba[offset + 3] = color[3];
  }
}

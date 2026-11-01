import { describe, expect, it } from "vitest";
import { buildRasterGrid, paintHour } from "../map/heatRaster";

function heatmap(cells: [number, number][], levels: string[], step = 0.5) {
  return { start: "", hours: 1, step, cells, levels };
}

describe("buildRasterGrid", () => {
  it("adds an empty margin so the surface fades out", () => {
    const grid = buildRasterGrid(heatmap([[30.25, -97.25]], ["00"]));
    expect(grid.west).toBe(-98);
    expect(grid.east).toBe(-96.5);
    expect(grid.south).toBe(29.5);
    expect(grid.north).toBe(31);
    expect(grid.pixels[0]).toBe(-1);
    expect([...grid.pixels]).toContain(0);
  });

  it("gives every cell pixels on a long north to south trip", () => {
    const cells: [number, number][] = [];
    for (let lat = 25.25; lat < 49; lat += 0.5) cells.push([lat, -100.25]);
    const grid = buildRasterGrid(heatmap(cells, cells.map(() => "00")));
    const seen = new Set(grid.pixels);
    cells.forEach((_, index) => expect(seen.has(index)).toBe(true));
  });

  it("places latitude by Mercator position", () => {
    const cells: [number, number][] = [[25.25, -100.25], [48.75, -100.25]];
    const grid = buildRasterGrid(heatmap(cells, ["00", "00"]));
    const column = 1;
    const rowOf = (cell: number) => {
      for (let y = 0; y < grid.height; y += 1) {
        if (grid.pixels[y * grid.width + column] === cell) return y;
      }
      return -1;
    };
    expect(rowOf(1)).toBeLessThan(rowOf(0));
    expect(rowOf(1)).toBeLessThan(4);
    expect(grid.height - rowOf(0)).toBeLessThan(5);
  });
});

describe("paintHour", () => {
  it("reads the requested hour and keeps gaps transparent", () => {
    const data = heatmap([[30.25, -97.25]], ["03"]);
    const grid = buildRasterGrid(data);
    const rgba = new Uint8ClampedArray(grid.pixels.length * 4);
    paintHour(grid, data.levels, 1, rgba);
    const pixel = grid.pixels.indexOf(0) * 4;
    expect(rgba[pixel]).toBe(212);
    expect(rgba[pixel + 3]).toBeGreaterThan(150);
    expect(rgba[3]).toBe(0);
  });
});

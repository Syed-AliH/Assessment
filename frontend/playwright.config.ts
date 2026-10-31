import { defineConfig } from "@playwright/test";

// Runs against a backend on :8000 serving the built app.
// See "End-to-end tests" in the README.
export default defineConfig({
  testDir: "./e2e",
  timeout: 240_000,
  expect: { timeout: 60_000 },
  workers: 1,
  use: {
    baseURL: process.env.E2E_BASE_URL ?? "http://127.0.0.1:8000",
    viewport: { width: 1440, height: 900 },
    launchOptions: {
      args: process.env.E2E_GPU
        ? ["--use-angle=d3d11", "--enable-gpu-rasterization", "--ignore-gpu-blocklist"]
        : ["--use-gl=angle", "--use-angle=swiftshader", "--enable-unsafe-swiftshader"],
    },
  },
});

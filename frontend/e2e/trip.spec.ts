import { expect, test, type Page } from "@playwright/test";

const SHOTS = process.env.E2E_SHOTS ?? "test-results";

async function choosePlace(page: Page, label: string, query: string, option: string) {
  await page.getByRole("combobox", { name: label }).fill(query);
  await page.getByRole("option", { name: option, exact: true }).click();
}

async function runTrip(page: Page, from: [string, string], to: [string, string]) {
  await page.goto("/");
  await choosePlace(page, "Origin", ...from);
  await choosePlace(page, "Destination", ...to);
  await page.getByRole("button", { name: "Compare routes" }).click();
  await expect(page.locator(".banner")).toBeVisible();
  // A long trip on a cold cache waits for weather quota before the heatmap arrives.
  await expect(page.locator("#forecast-hour")).toBeVisible({ timeout: 150_000 });
}

test("short trip: routes, recommendation, heatmap, slider", async ({ page }) => {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await runTrip(page, ["Dallas", "Dallas, TX"], ["Houston", "Houston, TX"]);

  expect(await page.locator(".route-card").count()).toBeGreaterThan(0);
  await expect(page.locator(".route-card").first().locator(".badge")).toBeVisible();
  await expect(page.getByRole("region", { name: "Trip results" })).toBeFocused();
  await expect(page.locator(".forecast-summary")).not.toBeEmpty();
  expect(await page.locator(".checkpoints li").count()).toBeGreaterThan(5);
  await page.waitForTimeout(1500);
  await page.screenshot({ path: `${SHOTS}/short-trip.png` });

  const slider = page.locator("#forecast-hour");
  await slider.fill("24");
  await expect(page.locator(".forecast-head output")).toContainText("+24 h");
  expect(errors).toEqual([]);
});

test("slider never touches the network and stays fast", async ({ page }) => {
  await runTrip(page, ["Los Angeles", "Los Angeles, CA"], ["New York", "New York, NY"]);
  await page.waitForTimeout(1500);
  await page.screenshot({ path: `${SHOTS}/long-trip.png` });

  let apiCalls = 0;
  page.on("request", (request) => {
    if (request.url().includes("/api/")) apiCalls += 1;
  });
  await page.evaluate(() => performance.clearMeasures("heat-update"));
  for (let hour = 0; hour <= 48; hour += 1) {
    await page.locator("#forecast-hour").fill(String(hour));
    await page.waitForTimeout(20);
  }
  await page.waitForTimeout(500);

  const durations = await page.evaluate(() =>
    performance.getEntriesByName("heat-update").map((entry) => entry.duration),
  );
  durations.sort((a, b) => a - b);
  console.log(
    `heat-update n=${durations.length} ` +
      `median=${durations[durations.length >> 1]?.toFixed(1)}ms ` +
      `p95=${durations[Math.floor(durations.length * 0.95)]?.toFixed(1)}ms`,
  );
  expect(apiCalls).toBe(0);
  expect(durations.length).toBeGreaterThan(10);
});

test("invalid input is caught before any request", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("button", { name: "Compare routes" }).click();
  await expect(page.getByText("Choose a place from the list.")).toHaveCount(2);
  await expect(page.getByRole("combobox", { name: "Origin" })).toBeFocused();
  await page.getByLabel("Load weight (lb)").fill("90000");
  await page.getByRole("button", { name: "Compare routes" }).click();
  await expect(page.getByText("Enter a load from 0 to 80,000 lb.")).toBeVisible();
});

test("phone layout has no horizontal scroll", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/");
  await page.screenshot({ path: `${SHOTS}/phone-start.png` });
  const form = await page.locator(".trip-form").boundingBox();
  expect(form!.y).toBeLessThan(140);
  await runTrip(page, ["Dallas", "Dallas, TX"], ["Houston", "Houston, TX"]);
  await page.waitForTimeout(1000);
  await page.screenshot({ path: `${SHOTS}/phone.png` });
  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
  );
  expect(overflow).toBeLessThanOrEqual(0);
});

function cannedAnalysis(status: string, risk: string) {
  const eta = new Date(Date.now() + 3_600_000).toISOString();
  const checkpoint = {
    index: 0, miles: 0, lat: 32.8, lon: -96.8, eta, represented_miles: 100, risk,
    cause: risk === "no_travel" ? "wind" : null, load_adjusted: risk === "no_travel",
    wind_mph: risk === "unknown" ? null : 50, gust_mph: risk === "unknown" ? null : 60,
    rain_in_hr: risk === "unknown" ? null : 0, snow_in_hr: risk === "unknown" ? null : 0,
  };
  return {
    analysis_id: "canned",
    departure: eta,
    origin_utc_offset_minutes: -300,
    load_lb: 35000,
    interval_miles: 25,
    routes: [{
      id: "a", label: "Route A", length_miles: 100, travel_seconds: 7200,
      traffic_delay_seconds: 0, arrival: eta,
      geometry: [[-96.8, 32.8], [-95.4, 29.8]],
      risk: {
        no_travel_miles: risk === "no_travel" ? 100 : 0, severe_miles: 0, high_miles: 0,
        moderate_miles: 0, low_miles: 0, unknown_miles: risk === "unknown" ? 100 : 0,
        average_risk: risk === "unknown" ? null : 4, coverage: risk === "unknown" ? 0 : 1,
      },
      checkpoints: [checkpoint],
    }],
    recommendation: {
      status,
      route_id: null,
      least_bad_route_id: status === "no_safe_route" ? "a" : null,
      ranked_route_ids: ["a"],
      deciding_factor: null,
      explanation: status === "no_safe_route"
        ? "No safe route for this departure: no route avoids No Travel weather."
        : "There is not enough forecast data along these routes to recommend one.",
      warnings: [],
    },
    notices: [],
  };
}

async function submitWith(page: Page, status: number, body: unknown) {
  await page.route("**/api/trips/analyze", (route) => route.fulfill({ status, json: body }));
  await page.route("**/api/trips/canned/heatmap", (route) =>
    route.fulfill({ status: 503, json: { error: { code: "upstream_unavailable", message: "Heatmap unavailable." } } }),
  );
  await page.goto("/");
  await choosePlace(page, "Origin", "Dallas", "Dallas, TX");
  await choosePlace(page, "Destination", "Houston", "Houston, TX");
  await page.getByRole("button", { name: "Compare routes" }).click();
}

test("no safe route: nothing is badged recommended", async ({ page }) => {
  await submitWith(page, 200, cannedAnalysis("no_safe_route", "no_travel"));
  await expect(page.getByRole("heading", { name: "No safe route" })).toBeVisible();
  await expect(page.locator(".badge")).toHaveText("Least bad");
  await expect(page.getByText("Heatmap unavailable.")).toBeVisible();
  await expect(page.getByRole("button", { name: "Retry" })).toBeVisible();
  await page.waitForTimeout(1000);
  await page.screenshot({ path: `${SHOTS}/no-safe-route.png` });
});

test("missing forecast reads as Unknown, not Low", async ({ page }) => {
  await submitWith(page, 200, cannedAnalysis("insufficient_data", "unknown"));
  await expect(page.getByRole("heading", { name: "Not enough forecast data" })).toBeVisible();
  await expect(page.locator(".checkpoints .risk-pill")).toHaveText("Unknown");
  await expect(page.locator(".checkpoints")).not.toContainText("Low");
});

test("server field errors reappear on the form", async ({ page }) => {
  await submitWith(page, 400, {
    error: { code: "validation_error", message: "Check the highlighted fields.", fields: { load_lb: ["Too heavy."] } },
  });
  await expect(page.getByRole("alert")).toContainText("Check the highlighted fields.");
  await expect(page.getByText("Too heavy.")).toBeVisible();
  await expect(page.getByLabel("Load weight (lb)")).toBeFocused();
});

test("upstream outage shows a clear error", async ({ page }) => {
  await submitWith(page, 503, {
    error: { code: "upstream_unavailable", message: "A data service is unavailable right now. Try again shortly." },
  });
  await expect(page.getByRole("alert")).toContainText("unavailable right now");
  await expect(page.getByRole("button", { name: "Try again" })).toBeVisible();
});

test("swap exchanges origin and destination", async ({ page }) => {
  await page.goto("/");
  await choosePlace(page, "Origin", "Dallas", "Dallas, TX");
  await choosePlace(page, "Destination", "Houston", "Houston, TX");
  await page.getByRole("button", { name: "Swap origin and destination" }).click();
  await expect(page.getByRole("combobox", { name: "Origin" })).toHaveValue("Houston, TX");
  await expect(page.getByRole("combobox", { name: "Destination" })).toHaveValue("Dallas, TX");
  await page.getByRole("button", { name: "Compare routes" }).click();
  await expect(page.locator(".trip-summary")).toContainText("Houston, TX");
  await expect(page.locator(".banner")).toBeVisible();
  await page.waitForTimeout(2500);
  await page.screenshot({ path: `${SHOTS}/final.png` });
});

import { test, expect, type Page } from "@playwright/test";
const configured = (
  JSON.parse(process.env.STACK_APPS ?? "[]") as { name: string; url: string }[]
).find((app) => app.name === "twin");
const url = process.env.TWIN_URL ?? configured?.url ?? "";
test.skip(!url, "No Twin browser target configured");
const run = {
  id: "run-a",
  epoch: "epoch-a",
  state: "running",
  granted: 15,
  requested: 16,
  committed: 14,
  speed: 5,
  scenario: {
    start_at: "2026-01-05T08:00:00+10:30",
    time_zone: "Australia/Adelaide",
  },
};
const source = (name: string, snapshot: object) => ({
  name,
  connected: true,
  stale: false,
  status: { run },
  snapshot,
  cursor: "1",
  observed_at: "2026-10-24T00:00:00Z",
  last_success_at: "2026-10-24T00:00:00Z",
  error: null,
  website_url: null,
});
async function open(
  page: Page,
  sources: object[],
  events: object[] = [],
  controls: object[] = [],
  scopes = ["status:read"],
  heartbeats: { role: string; healthy: boolean }[] = [],
) {
  await page.route("**/api/status", (route) =>
    route.fulfill({
      json: {
        identity: { username: "reader", scopes },
        heartbeats: [],
      },
    }),
  );
  await page.route("**/api/twin", (route) =>
    route.fulfill({
      json: {
        revision: 1,
        mode: "live",
        sources,
        events,
        aligned: null,
        controls,
        heartbeats,
      },
    }),
  );
  await page.goto(url);
  await page.getByLabel("Username", { exact: true }).fill("reader");
  await page.getByLabel("Password", { exact: true }).fill("test");
  await page.getByRole("button", { name: "Sign in", exact: true }).click();
}
test("Twin handles zero sources without invented stock or controls", async ({
  page,
}) => {
  await open(page, []);
  await expect(
    page.getByRole("heading", { name: "No sources configured" }),
  ).toBeVisible();
  await expect(
    page.getByText("Not an atomic federation snapshot."),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: /^(Hold|Resume|Finalize|Reset run)$/ }),
  ).toHaveCount(0);
});
test("Twin renders selectable facility, quantities and correlated event history", async ({
  page,
}) => {
  await open(
    page,
    [
      source("manufacturing", {
        config: { lines: [{ code: "LINE-1", capacity: 2 }] },
        orders: [
          {
            id: "batch-1",
            line: "LINE-1",
            quantity: 4,
            output_quantity: 3,
            scrap_quantity: 1,
            correlation_id: "corr-1",
            status: "completed",
          },
        ],
      }),
      source("storage", {
        locations: [
          { code: "RAW-A", capacity: 500 },
          { code: "FINISHED-A", capacity: 500 },
          { code: "DISPATCH", capacity: 250 },
        ],
        inventory: [
          {
            sku: "PRODUCT",
            location: "FINISHED-A",
            on_hand: 12,
            reserved: 4,
            available: 8,
          },
        ],
        transfers: [],
      }),
      source("logistics", {
        vehicles: [
          { code: "TRUCK-1", location: "WAREHOUSE", capacity: 20 },
          { code: "TRUCK-2", location: "DISPATCH", capacity: 12 },
        ],
        transfers: [
          {
            id: "transfer-1",
            vehicle: "TRUCK-1",
            status: "in_transit",
            departed_at: 10,
            planned_eta: 20,
            quantity: 4,
            correlation_id: "corr-1",
          },
        ],
      }),
      source("shipping", {
        orders: [
          {
            id: "order-1",
            status: "in_transit",
            lines: [{ sku: "PRODUCT", quantity: 4, received: 4 }],
            correlation_id: "corr-1",
          },
        ],
        shipments: [
          { id: "shipment-1", order_id: "order-1", status: "in_transit" },
        ],
      }),
    ],
    [
      {
        id: "event-1",
        source: "manufacturing",
        run_id: "run-a",
        epoch: "epoch-a",
        correlation_id: "corr-1",
        simulation_time: 12,
        payload: { action: "complete" },
      },
    ],
  );
  await page
    .getByRole("button", { name: "Select production cell LINE-1" })
    .click();
  await expect(
    page.getByRole("heading", { name: "LINE-1", exact: true }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Inspect batch-1" }).click();
  await expect(page.getByText("corr-1", { exact: true }).first()).toBeVisible();
  await expect(page.getByText("complete", { exact: true })).toBeVisible();
  await expect(page.getByText("scrap_quantity", { exact: true })).toBeVisible();
  await expect(
    page.getByText("Australia/Adelaide · 5× speed").first(),
  ).toBeVisible();
  await expect(
    page.getByText("No shared timeline", { exact: true }),
  ).toBeVisible();
  await page.screenshot({
    path: "/artifacts/twin-facility-desktop.png",
    fullPage: true,
  });
  await page.setViewportSize({ width: 390, height: 844 });
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth + 1,
    ),
  ).toBe(true);
  await page
    .getByRole("button", { name: "Select production cell LINE-1" })
    .focus();
  await page.keyboard.press("Enter");
  await expect(
    page.getByRole("heading", { name: "LINE-1", exact: true }),
  ).toBeVisible();
  await page.screenshot({
    path: "/artifacts/twin-facility-mobile.png",
    fullPage: true,
  });
});
test("Twin labels estimated travel and preserves confirmed business state on stale hold", async ({
  page,
}) => {
  const logistics = {
    ...source("logistics", {
      vehicles: [{ code: "TRUCK-1", location: "WAREHOUSE", capacity: 20 }],
      transfers: [
        {
          id: "transfer-1",
          vehicle: "TRUCK-1",
          origin: "WAREHOUSE",
          destination: "DISPATCH",
          quantity: 8,
          status: "in_transit",
          departed_at: 10,
          planned_eta: 20,
        },
      ],
    }),
    stale: true,
    status: { run: { ...run, state: "held", granted: 25 } },
  };
  await open(page, [logistics]);
  await expect(page.getByText("Estimated position · frozen")).toBeVisible();
  await page.getByRole("button", { name: "Select vehicle TRUCK-1" }).click();
  await expect(
    page.getByText("in_transit", { exact: true }).first(),
  ).toBeVisible();
  await expect(page.getByText("Stale", { exact: true }).first()).toBeVisible();
  await expect(page.getByText("Delivered", { exact: true })).toHaveCount(0);
});

test("Twin exposes only configured controls and waits for explicit acknowledgement", async ({
  page,
}) => {
  let body: unknown;
  let key: string | undefined;
  await page.route("**/api/twin/controls/clock/pause", async (route) => {
    body = route.request().postDataJSON();
    key = route.request().headers()["idempotency-key"];
    await route.fulfill({
      status: 202,
      json: {
        scope: "federation",
        action: "pause",
        acknowledged: false,
        message: "Global acknowledgement is pending.",
      },
    });
  });
  await open(
    page,
    [source("logistics", {})],
    [],
    [
      {
        name: "clock",
        label: "Federation clock",
        scope: "federation",
        source: null,
        actions: ["pause"],
      },
    ],
    ["status:read", "runs:control"],
  );
  await page
    .getByRole("button", { name: "Request global pause", exact: true })
    .click();
  await expect(page.getByRole("status")).toHaveText(
    "Awaiting acknowledgement: Global acknowledgement is pending.",
  );
  expect(body).toEqual({});
  expect(key).toMatch(/^[a-f0-9-]{36}$/);
  await expect(
    page.getByText("Federation paused", { exact: true }),
  ).toHaveCount(0);
});
test("Twin hides unsafe website links and unavailable stock", async ({
  page,
}) => {
  await open(page, [
    {
      ...source("storage", {}),
      connected: false,
      snapshot: null,
      website_url: "https://user:password@example.com",
    },
  ]);
  await expect(page.getByText("Snapshot unavailable")).toBeVisible();
  await expect(
    page.getByRole("link", { name: "Open Storage website" }),
  ).toHaveCount(0);
  await expect(page.getByText("Disconnected", { exact: true })).toBeVisible();
});

test("Twin freezes a confirmed position on local hold and removes absent sources", async ({
  page,
}) => {
  const logistics = source("logistics", {
    vehicles: [{ code: "TRUCK-1", location: "WAREHOUSE" }],
    transfers: [
      {
        id: "transfer-1",
        vehicle: "TRUCK-1",
        status: "in_transit",
        departed_at: 10,
        planned_eta: 20,
      },
    ],
  });
  const sources = [logistics];
  await open(page, sources);
  const vehicle = page.getByRole("button", { name: "Select vehicle TRUCK-1" });
  await expect(vehicle).toBeVisible();
  const position = await vehicle.getAttribute("data-position");
  expect(position).not.toBeNull();
  logistics.status = { run: { ...run, state: "held", granted: 19 } };
  await expect(page.getByText("Estimated position · frozen")).toBeVisible();
  expect(await vehicle.getAttribute("data-position")).toBe(position);
  sources.splice(0);
  await expect(
    page.getByRole("heading", { name: "No sources configured" }),
  ).toBeVisible();
  await expect(vehicle).toHaveCount(0);
});

test("Twin excludes archived epoch events from current history", async ({
  page,
}) => {
  await open(
    page,
    [source("manufacturing", { config: { lines: [] }, orders: [] })],
    [
      {
        id: "old-event",
        source: "manufacturing",
        run_id: "run-a",
        epoch: "old-epoch",
        simulation_time: 9,
        payload: { action: "Archived completion" },
      },
    ],
  );
  await page
    .getByRole("button", { name: "Business activity", exact: true })
    .click();
  await expect(
    page.getByText("No matching events in the current run and epoch."),
  ).toBeVisible();
  await expect(
    page.getByText("Archived completion", { exact: true }),
  ).toHaveCount(0);
});

test("Twin retries uncertain controls with the original key and run fence", async ({
  page,
}) => {
  const requests: { key: string; body: unknown }[] = [];
  await page.route("**/api/twin/controls/local/hold", async (route) => {
    requests.push({
      key: route.request().headers()["idempotency-key"],
      body: route.request().postDataJSON(),
    });
    await route.fulfill(
      requests.length === 1
        ? { status: 502, json: { detail: "Owner outcome unknown" } }
        : {
            json: {
              scope: "local",
              action: "hold",
              acknowledged: requests.length === 3,
              message:
                requests.length === 3
                  ? "Local hold acknowledged."
                  : "Owner acknowledgement pending.",
            },
          },
    );
  });
  await open(
    page,
    [source("logistics", {})],
    [],
    [
      {
        name: "local",
        label: "Logistics",
        scope: "local",
        source: "logistics",
        actions: ["hold", "resume"],
      },
    ],
    ["status:read", "runs:control"],
  );
  await page.getByRole("button", { name: "Local hold", exact: true }).click();
  await expect(page.getByRole("status")).toContainText("outcome is unknown");
  await expect(
    page.getByRole("button", { name: "Local resume", exact: true }),
  ).toBeDisabled();
  await page
    .getByRole("button", { name: "Retry pending control", exact: true })
    .click();
  await expect(page.getByRole("status")).toHaveText(
    "Awaiting acknowledgement: Owner acknowledgement pending.",
  );
  await page
    .getByRole("button", { name: "Retry pending control", exact: true })
    .click();
  await expect(page.getByRole("status")).toHaveText(
    "Acknowledged: Local hold acknowledged.",
  );
  expect(requests).toHaveLength(3);
  expect(new Set(requests.map((r) => r.key)).size).toBe(1);
  for (const request of requests)
    expect(request.body).toEqual({ run_id: "run-a", epoch: "epoch-a" });
  await expect(
    page.getByRole("button", { name: "Retry pending control", exact: true }),
  ).toHaveCount(0);
});

test("Twin marks overdue transport as awaiting arrival confirmation", async ({
  page,
}) => {
  await open(page, [
    {
      ...source("logistics", {
        vehicles: [{ code: "TRUCK-1" }],
        transfers: [
          {
            id: "transfer-1",
            vehicle: "TRUCK-1",
            status: "in_transit",
            departed_at: 10,
            planned_eta: 20,
          },
        ],
      }),
      status: { run: { ...run, granted: 25 } },
    },
  ]);
  await expect(
    page.getByText("Awaiting arrival confirmation", { exact: true }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Select vehicle TRUCK-1" }).click();
  await expect(
    page.getByText("in_transit", { exact: true }).first(),
  ).toBeVisible();
  await expect(page.getByText("Delivered", { exact: true })).toHaveCount(0);
});

test("Twin refreshes infrastructure health and hides healthy claims after connection loss", async ({
  page,
}) => {
  const heartbeats = [{ role: "projection", healthy: true }];
  const health = {
    heartbeats: [
      { role: "worker", healthy: true },
      { role: "controller", healthy: true },
    ],
    pending_jobs: 2,
    dead_letters: 0,
    broker: null,
  };
  await open(
    page,
    [{ ...source("logistics", {}), health }],
    [],
    [],
    ["status:read"],
    heartbeats,
  );
  await page
    .getByRole("button", { name: "Infrastructure", exact: true })
    .click();
  await expect(
    page.getByText("projection · Healthy", { exact: true }),
  ).toBeVisible();
  await expect(
    page.getByText("worker · Healthy", { exact: true }),
  ).toBeVisible();
  await expect(
    page.getByText("controller · Healthy", { exact: true }),
  ).toBeVisible();
  await expect(
    page.getByText("Broker health unavailable", { exact: true }),
  ).toBeVisible();
  await expect(
    page.getByText("Readiness unavailable", { exact: true }),
  ).toBeVisible();
  heartbeats[0].healthy = false;
  health.heartbeats[0].healthy = false;
  health.pending_jobs = 12;
  health.dead_letters = 3;
  await expect(
    page.getByText("projection · Unavailable", { exact: true }),
  ).toBeVisible();
  await expect(
    page.getByText("worker · Unavailable", { exact: true }),
  ).toBeVisible();
  const panel = page.locator(".source-panel");
  await expect(
    panel.getByText("Pending jobs: 12", { exact: true }),
  ).toBeVisible();
  await expect(
    panel.getByText("Dead letters: 3", { exact: true }),
  ).toBeVisible();
  heartbeats[0].healthy = true;
  await expect(
    page.getByText("projection · Healthy", { exact: true }),
  ).toBeVisible();
  await page.route("**/api/twin", (route) => route.abort());
  await expect(page.getByRole("alert")).toContainText("Twin connection lost");
  await expect(
    page.getByText("projection · Unavailable", { exact: true }),
  ).toBeVisible();
  await expect(
    page.getByText("controller · Unavailable", { exact: true }),
  ).toBeVisible();
  await expect(page.getByText(/ · Healthy$/)).toHaveCount(0);
});

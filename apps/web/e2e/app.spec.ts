import { test, expect } from "@playwright/test";
import { readFileSync } from "node:fs";
const apps = ["manufacturing", "storage", "logistics", "shipping", "twin"];
const titles = [
  "Manufacturing",
  "Storage",
  "Logistics",
  "Shipping",
  "Digital twin",
];
for (const [index, app] of apps.entries()) {
  test(`${app} has its own login and live application`, async ({ page }) => {
    const secret = JSON.parse(
      readFileSync(
        new URL(
          `../../../deploy/generated/${app}.secrets.json`,
          import.meta.url,
        ),
        "utf8",
      ),
    ).application;
    await page.goto(`http://127.0.0.1:${8181 + index}`);
    await expect(page.getByRole("link", { name: titles[index] })).toBeVisible();
    await page.getByLabel("Username", { exact: true }).fill(app + "-operator");
    await page.getByLabel("Password", { exact: true }).fill(secret);
    await page.getByRole("button", { name: "Sign in", exact: true }).click();
    await expect(
      page.getByRole("heading", {
        name: app === "twin" ? "Connected sources" : "Sample activity",
        exact: true,
      }),
    ).toBeVisible();
    await expect(page.getByRole("alert")).toHaveCount(0);
    if (app === "twin") {
      await expect(
        page.getByRole("heading", { name: "Storage", exact: true }),
      ).toBeVisible();
    } else {
      await page.getByRole("button", { name: "Operator", exact: true }).click();
      await page.getByRole("button", { name: "Hold", exact: true }).click();
      await expect(
        page.getByRole("button", { name: "Resume", exact: true }),
      ).toBeVisible();
      await page.getByRole("button", { name: "Resume", exact: true }).click();
      await page
        .getByRole("button", { name: "Sample activity", exact: true })
        .click();
      await page.getByLabel("Quantity", { exact: true }).fill("4");
      await page
        .getByRole("button", { name: "Schedule operation", exact: true })
        .click();
      await expect(
        page
          .getByRole("cell", { name: "Employee sample", exact: false })
          .first(),
      ).toBeVisible();
    }
    await page.screenshot({
      path: `../../.superpowers/simu-1/${app}-desktop.png`,
      fullPage: true,
    });
    await page.setViewportSize({ width: 390, height: 844 });
    await expect(
      page.getByRole("heading", {
        name: app === "twin" ? "Connected sources" : "Sample activity",
        exact: true,
      }),
    ).toBeVisible();
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= window.innerWidth,
      ),
    ).toBeTruthy();
    await page.screenshot({
      path: `../../.superpowers/simu-1/${app}-mobile.png`,
      fullPage: true,
    });
    await page.getByRole("button", { name: "Sign out", exact: true }).click();
    await expect(
      page.getByRole("heading", { name: "Sign in", exact: true }),
    ).toBeVisible();
  });
}

import { defineConfig } from "@playwright/test";
export default defineConfig({
  testDir: "./e2e",
  workers: 1,
  timeout: 45000,
  use: { viewport: { width: 1440, height: 1000 } },
  reporter: "list",
  outputDir: "../../.superpowers/simu-1/browser-results",
});

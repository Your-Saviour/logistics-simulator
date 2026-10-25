import { defineConfig } from '@playwright/test';
const origin = new URL(process.env.SHIPPING_URL ?? 'http://shipping-api:8000').origin;
export default defineConfig({
  testDir: '.', testMatch: 'shipping.spec.ts', workers: 1, timeout: 120000,
  expect: { timeout: 30000 },
  use: { actionTimeout: 30000, browserName: 'chromium', launchOptions: { args: ['--use-angle=swiftshader', '--enable-unsafe-swiftshader','--disable-gpu-compositing', `--unsafely-treat-insecure-origin-as-secure=${origin}`] }, trace: 'retain-on-failure' },
  reporter: 'list', outputDir: '/artifacts/shipping-results'
});

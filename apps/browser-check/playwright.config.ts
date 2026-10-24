import { defineConfig } from '@playwright/test';
const origins = [...new Set((JSON.parse(process.env.STACK_APPS ?? '[]') as {url:string}[]).map(app=>new URL(app.url).origin))];
// Private Docker origins stand in for the HTTPS ingress used in deployment.
// Browser UUID generation requires a secure context, including in these tests.
export default defineConfig({testDir:'.',testMatch:'stacks.spec.ts',workers:1,timeout:45000,
  use:{browserName:'chromium',launchOptions:{executablePath:'/usr/bin/chromium',args:origins.length?[`--unsafely-treat-insecure-origin-as-secure=${origins.join(',')}`]:[]},trace:'retain-on-failure'},reporter:'list',outputDir:'/artifacts/results'});

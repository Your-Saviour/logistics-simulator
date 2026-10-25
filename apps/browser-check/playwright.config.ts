import { defineConfig } from '@playwright/test';
const origins = [...new Set((JSON.parse(process.env.STACK_APPS ?? '[]') as {url:string}[]).map(app=>new URL(app.url).origin))];
const backend=process.env.HANDLING_RENDERER==='mesa'
  ? ['--use-cmd-decoder=passthrough','--use-gl=angle','--use-angle=gl-egl','--ignore-gpu-blocklist']
  : ['--use-angle=swiftshader','--enable-unsafe-swiftshader'];
// Private Docker origins stand in for the HTTPS ingress used in deployment.
// Browser UUID generation requires a secure context, including in these tests.
export default defineConfig({testDir:'.',testMatch:['stacks.spec.ts','twin.spec.ts','runtime.spec.ts','handling-scene.spec.ts','handling-inspector.spec.ts','handling-performance.spec.ts'],workers:1,timeout:45000,
  use:{browserName:'chromium',launchOptions:{args:[...backend,'--disable-gpu-compositing',...(origins.length?[`--unsafely-treat-insecure-origin-as-secure=${origins.join(',')}`]:[])]},trace:'retain-on-failure'},reporter:'list',outputDir:'/artifacts/results'});

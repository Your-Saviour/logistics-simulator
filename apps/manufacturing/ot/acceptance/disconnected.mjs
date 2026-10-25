import { createRequire } from 'node:module';
const { chromium, expect } = createRequire('/checks/package.json')('@playwright/test');
const browser = await chromium.launch({ headless: true });
try {
    const page = await browser.newPage({ viewport: { width: 1440, height: 1160 } });
    await page.goto('http://fuxa:1881', { waitUntil: 'domcontentloaded' });
    await expect(page.locator('#ot-connection')).toHaveText('Stale / disconnected', { timeout: 30000 });
    for (const id of ['start', 'stop', 'reset', 'conveyor_jam', 'sensor_failure', 'guard_open', 'power_loss']) await expect(page.locator('#ot-' + id)).toBeDisabled();
    await page.screenshot({ path: '/artifacts/fuxa-disconnected.png', fullPage: true });
    console.log('PASS: disconnected physical telemetry disables FUXA controls');
} finally { await browser.close(); }

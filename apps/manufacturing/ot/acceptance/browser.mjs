import { createRequire } from 'node:module';
const { chromium, expect } = createRequire('/checks/package.json')('@playwright/test');
const browser = await chromium.launch({ headless: true });
const page = await browser.newPage({ viewport: { width: 1440, height: 1160 } });
const errors = [];
page.on('pageerror', error => errors.push(error.message));
try {
    const response = await fetch('http://fuxa:1881/api/project');
    const project = await response.json();
    console.log('FUXA project:', project.hmi?.views?.map(view => view.id), 'start:', project.hmi?.layout?.start);
    await page.goto('http://fuxa:1881', { waitUntil: 'domcontentloaded' });
    await page.locator('#ot-connection').waitFor({ state: 'visible', timeout: 30000 });
    await expect(page.locator('#ot-connection')).toHaveText('Connected', { timeout: 30000 });
    await page.screenshot({ path: '/artifacts/fuxa-cell.png', fullPage: true });
    console.log((await page.locator('body').innerText()).slice(0, 1800));
    console.log('Browser errors:', errors);
    await expect(page.locator('#ot-start')).toHaveText('Start');
} catch (error) {
    console.log('Browser errors:', errors);
    console.log((await page.locator('body').innerText()).slice(0, 1800));
    await page.screenshot({ path: '/artifacts/fuxa-error.png', fullPage: true });
    throw error;
} finally {
    await browser.close();
}

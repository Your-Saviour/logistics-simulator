import { test, expect } from '@playwright/test';
type App = { name: string; url: string; username: string; password: string; employee: string; employeePassword: string };
const apps = JSON.parse(process.env.STACK_APPS ?? '[]') as App[];
for (const app of apps) {
  test(`${app.name}: independent login, real status and mobile width`, async ({ page }) => {
    await page.goto(app.url);
    await page.getByLabel('Username', {exact: true}).fill(app.username);
    await page.getByLabel('Password', {exact: true}).fill(app.password);
    await page.getByRole('button', {name: /^(sign|log) in$/i}).click();
    await expect(page.getByRole('button', {name: /^(sign|log) out$/i})).toBeVisible();
    if(app.name!=='twin') await expect(page.getByRole('button',{name:/finaliz/i})).toBeVisible();
    await page.screenshot({path:`/artifacts/${app.name}-desktop.png`, fullPage:true});
    await page.setViewportSize({width:390,height:844});
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1)).toBe(true);
    await page.screenshot({path:`/artifacts/${app.name}-mobile.png`, fullPage:true});
    await page.getByRole('button', {name:/^(sign|log) out$/i}).click();
    await page.getByLabel('Username', {exact:true}).fill(app.employee);
    await page.getByLabel('Password', {exact:true}).fill(app.employeePassword);
    await page.getByRole('button', {name:/^(sign|log) in$/i}).click();
    await expect(page.getByRole('button', {name:/^(sign|log) out$/i})).toBeVisible();
    await expect(page.getByRole('button', {name:/hold|resume|finaliz|reset|new run|audit/i})).toHaveCount(0);
  });
}
test('container browser targets supplied',()=>expect(apps.length).toBeGreaterThan(0));

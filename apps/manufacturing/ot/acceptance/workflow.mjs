import { createRequire } from 'node:module';
const { chromium, expect } = createRequire('/checks/package.json')('@playwright/test');
const password = process.env.MANUFACTURING_PASSWORD;
const basic = user => 'Basic ' + Buffer.from(user + ':' + password).toString('base64');
const api = async (path, body, user = 'operator', key = crypto.randomUUID()) => {
    const response = await fetch('http://manufacturing-api:8000' + path, { method: body ? 'POST' : 'GET', headers: { Authorization: basic(user), 'Content-Type': 'application/json', 'Idempotency-Key': key }, body: body ? JSON.stringify(body) : undefined });
    const result = await response.json();
    if (!response.ok) throw new Error(path + ' returned ' + response.status + ': ' + JSON.stringify(result));
    return result;
};
const poll = async (action, description, timeout = 90000) => {
    const deadline = Date.now() + timeout;
    while (Date.now() < deadline) { const result = await action(); if (result) return result; await new Promise(resolve => setTimeout(resolve, 100)); }
    throw new Error('Timed out: ' + description);
};
const scope = async () => { const run = (await api('/api/status')).run; return { run_id: run.id, epoch: run.epoch }; };
const control = async (action, extra = {}) => api('/api/control/' + action, { ...await scope(), ...extra });
const command = async body => { const run = (await api('/api/status')).run; return api('/api/production/commands', { run_id: run.id, epoch: run.epoch, due_at: Math.max(run.requested, run.granted) + 5, ...body }, 'employee'); };
const order = async id => (await api('/api/production')).orders.find(item => item.id === id);
const equipment = async () => (await api('/api/ot')).cell;
const browser = await chromium.launch({ headless: true });
const page = await browser.newPage({ viewport: { width: 1440, height: 1160 } });
const errors = [];
page.on('pageerror', error => errors.push(error.message));
try {
    await page.goto('http://fuxa:1881', { waitUntil: 'domcontentloaded' });
    await expect(page.locator('#ot-connection')).toHaveText('Connected', { timeout: 30000 });
    await control('speed', { speed: 1 });
    for (const [sku, quantity] of [['HOUSING', 20], ['IMPELLER', 20], ['SEAL', 40]]) await command({ action: 'supply', sku, quantity, units: [{ id: crypto.randomUUID(), quantity }] });
    const correlation = crypto.randomUUID();
    const created = await command({ action: 'create', product: 'PUMP', line: 'ASSEMBLY-1', quantity: 20, correlation_id: correlation });
    const id = created.id;
    await poll(async () => !!await order(id), 'work order creation');
    await command({ action: 'release', reference: id });
    await poll(async () => (await order(id)).status === 'running', 'batch dispatch');
    await expect(page.locator('#ot-work_order')).toHaveText(id, { timeout: 15000 });
    await expect(page.locator('#ot-start')).toBeEnabled();
    await page.locator('#ot-start').click();
    await expect(page.locator('#ot-stop')).toBeDisabled();
    await poll(async () => (await equipment()).telemetry.cell.enabled, 'FUXA Start reaches the equipment');
    const actorReceipt = await poll(async () => (await api('/api/ot')).commands.find(item => item.actor === 'fuxa' && item.body.action === 'start' && item.status === 'completed'), 'attributed HMI acknowledgement');
    console.log('FUXA Start acknowledged by Manufacturing:', actorReceipt.id);
    for (const fault of ['conveyor_jam', 'sensor_failure', 'guard_open', 'power_loss']) {
        await expect(page.locator('#ot-' + fault)).toBeEnabled({ timeout: 15000 });
        await page.locator('#ot-' + fault).click();
        const tripped = await poll(async () => { const cell = await equipment(); return cell.telemetry.cell.faults.includes(fault) && cell.telemetry.actuators.fault ? cell : null; }, 'fault interlock ' + fault);
        const position = tripped.telemetry.cell.position, progress = tripped.telemetry.cell.progress_seconds;
        const paused = await poll(async () => { const cell = await equipment(); return cell.settled >= tripped.settled + 2 ? cell : null; }, 'paused steps settle during ' + fault);
        if (paused.telemetry.cell.position !== position || paused.telemetry.cell.progress_seconds !== progress || paused.telemetry.actuators.conveyor || paused.telemetry.actuators.cycle) throw new Error('Fault did not inhibit actual equipment: ' + fault);
        if (fault === 'guard_open') { await expect(page.locator('#ot-fault-reason')).toContainText('guard_open'); await page.screenshot({ path: '/artifacts/fuxa-guard-open.png', fullPage: true }); }
        await expect(page.locator('#ot-' + fault)).toBeEnabled();
        await page.locator('#ot-' + fault).click();
        await poll(async () => !(await equipment()).telemetry.cell.faults.includes(fault), 'restore ' + fault);
        await expect(page.locator('#ot-reset')).toBeEnabled();
        await page.locator('#ot-reset').click();
        await poll(async () => !(await equipment()).telemetry.cell.latched, 'acknowledge ' + fault);
        await expect(page.locator('#ot-start')).toBeEnabled();
        await page.locator('#ot-start').click();
        await poll(async () => (await equipment()).telemetry.cell.enabled, 'resume after ' + fault);
        console.log('PASS: FUXA fault, paused simulation steps, restore, acknowledge and Start:', fault);
    }
    await control('speed', { speed: 60 });
    const completed = await poll(async () => { const current = await order(id); return current.status === 'completed' ? current : null; }, 'PLC-driven HMI batch completion');
    if (completed.output_quantity !== 19 || completed.scrap_quantity !== 1) throw new Error('Batch accounting mismatch');
    const production = await api('/api/production');
    const events = production.events.filter(item => item.order_id === id);
    if (events.length !== 1 || events[0].envelope.correlation_id !== correlation || !production.materials.every(item => item.quantity === 0)) throw new Error('Exactly-once material/event correlation failed');
    await expect(page.locator('#ot-good_quantity')).toHaveText('19');
    await expect(page.locator('#ot-scrap_quantity')).toHaveText('1');
    await page.screenshot({ path: '/artifacts/fuxa-completed.png', fullPage: true });
    await control('hold');
    const first = await equipment();
    const settled = await poll(async () => { const cell = await equipment(); return cell.observed_at !== first.observed_at ? cell : null; }, 'held observation');
    const observed = await poll(async () => { const cell = await equipment(); return cell.observed_at !== settled.observed_at ? cell : null; }, 'second held observation');
    if (observed.settled !== settled.settled) throw new Error('Hold admitted a new equipment step');
    await control('resume');
    await poll(async () => (await equipment()).settled > observed.settled, 'resume grants progression');
    for (const speed of [1, 5, 20, 60]) {
        await control('speed', { speed });
        const before = (await equipment()).settled;
        await poll(async () => (await equipment()).settled > before, 'acknowledged progression at speed ' + speed);
    }
    console.log('PASS: FUXA operator loop, four faults, correlated 19 good / 1 scrap, hold/resume and accelerated stepping');
    if (errors.length) throw new Error('Browser errors: ' + errors.join('; '));
} catch (error) {
    console.log('Browser errors:', errors);
    console.log((await page.locator('body').innerText()).slice(0, 2000));
    await page.screenshot({ path: '/artifacts/fuxa-workflow-error.png', fullPage: true });
    throw error;
} finally { await browser.close(); }

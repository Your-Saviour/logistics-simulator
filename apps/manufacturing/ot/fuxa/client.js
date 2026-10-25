// FUXA CLIENT script. Native tag API is the only connection to operator authority.
if (window.simu54Timer) clearInterval(window.simu54Timer);
let frame = null;
let refreshing = false;
const text = (id, value) => { const node = document.getElementById('ot-' + id); if (node) node.textContent = String(value ?? '--'); };
const pending = () => { try { return JSON.parse(sessionStorage.getItem('simu54.pending')); } catch (_) { return null; } };
const newCommandId = () => {
    const bytes = crypto.getRandomValues(new Uint8Array(16));
    bytes[6] = (bytes[6] & 15) | 64; bytes[8] = (bytes[8] & 63) | 128;
    const hex = Array.from(bytes, byte => byte.toString(16).padStart(2, '0')).join('');
    return [hex.slice(0, 8), hex.slice(8, 12), hex.slice(12, 16), hex.slice(16, 20), hex.slice(20)].join('-');
};
const send = async (action, fault) => {
    if (!frame || !frame.connected || Date.now() - frame.heartbeat_ms > 3000) { text('command-status', 'Disconnected. Commands are unavailable.'); return; }
    if (pending()) { text('command-status', 'An uncertain command is retained. Retry it or discard the local retry before another command. Discard does not cancel an accepted command.'); return; }
    const command = { command_id: newCommandId(), run_id: frame.run_id, epoch: frame.epoch, action };
    if (fault) { command.fault = fault; command.active = !frame[fault]; }
    sessionStorage.setItem('simu54.pending', JSON.stringify(command));
    ['start', 'stop', 'reset', 'conveyor_jam', 'sensor_failure', 'guard_open', 'power_loss'].forEach(id => { const node = document.getElementById('ot-' + id); if (node) node.disabled = true; });
    $setTag('command', JSON.stringify(command));
    text('command-status', 'Command pending: ' + command.command_id);
};
const bind = (id, callback) => { const node = document.getElementById('ot-' + id); if (node && !node.dataset.simu54Bound) { node.dataset.simu54Bound = 'true'; node.addEventListener('click', callback); } };
const setup = () => {
    bind('start', () => send('start')); bind('stop', () => send('stop')); bind('reset', () => send('reset'));
    ['conveyor_jam', 'sensor_failure', 'guard_open', 'power_loss'].forEach(fault => bind(fault, () => send('fault', fault)));
    bind('retry', () => { const saved = pending(); if (saved) $setTag('command', JSON.stringify(saved)); });
    bind('discard', () => { sessionStorage.removeItem('simu54.pending'); text('command-status', 'Local retry discarded. This does not cancel a command already accepted by Manufacturing.'); });
    const discard = document.getElementById('ot-discard'); if (discard) discard.disabled = !pending();
};
const refresh = async () => {
    if (refreshing) return;
    refreshing = true;
    try {
        setup();
        const raw = $getTag('frame');
        if (raw) frame = JSON.parse(raw);
        if (!frame) return;
        const live = !!frame.connected && Date.now() - frame.heartbeat_ms < 3000;
        text('connection', live ? 'Connected' : 'Stale / disconnected');
        text('state', live ? frame.cell_state : 'Equipment state is unknown');
        ['work_order', 'simulation_time', 'good_quantity', 'scrap_quantity'].forEach(key => text(key, frame[key]));
        text('progress', frame.progress_seconds + ' / ' + frame.duration_seconds);
        text('conveyor', frame.conveyor ? 'RUNNING' : 'STOPPED');
        text('clamped', frame.clamped ? 'CLOSED' : 'OPEN');
        text('cycle', frame.cycle ? 'ACTIVE' : 'IDLE');
        text('safety', 'Guard: ' + (frame.guard_closed ? 'closed' : 'OPEN') + ' / Power: ' + (frame.power_available ? 'available' : 'OFF'));
        text('fault-reason', live ? frame.fault_reason : 'Telemetry is stale. Restore the gateway / PLC connection before operating the cell.');
        text('scope', 'Run: ' + frame.run_id + ' / Epoch: ' + frame.epoch);
        const carrier = document.getElementById('ot-carrier');
        if (carrier) { carrier.setAttribute('transform', 'translate(' + (Math.min(4, Math.max(0, Number(frame.position))) * 145) + ',0)'); carrier.style.opacity = live ? '1' : '.25'; }
        [['present-lamp', frame.part_present], ['positioned-lamp', frame.positioned], ['clamp-shape', frame.clamped]].forEach(([id, on]) => { const node = document.getElementById('ot-' + id); if (node) node.setAttribute('fill', live && on ? '#ffb800' : '#34372d'); });
        const cycle = document.getElementById('ot-cycle-shape'); if (cycle) cycle.setAttribute('stroke', live && frame.cycle ? '#ffb800' : '#34372d');
        const saved = pending();
        if (saved) {
            const receipt = (frame.receipts || []).find(item => item.idempotency_key === 'fuxa:' + saved.command_id);
            if (receipt && receipt.status !== 'pending') { sessionStorage.removeItem('simu54.pending'); text('command-status', 'Command ' + receipt.status + (receipt.reason ? ': ' + receipt.reason : '') + ' / ' + saved.command_id); }
            else if (saved.run_id !== frame.run_id || saved.epoch !== frame.epoch) text('command-status', 'Run changed. The retained command is fenced; discard its local retry before issuing a new command.');
            else text('command-status', 'Awaiting command acknowledgement: ' + saved.command_id + '. Retry uses the same identity.');
        } else if (frame.last_command_id) {
            text('command-status', 'Last command ' + frame.last_command_status + (frame.last_command_reason ? ': ' + frame.last_command_reason : '') + ' / ' + frame.last_command_id);
        } else {
            text('command-status', 'No pending command. Release a work order in Manufacturing, then Start the dispatched carrier.');
        }
        ['start', 'stop', 'reset', 'conveyor_jam', 'sensor_failure', 'guard_open', 'power_loss'].forEach(id => { const node = document.getElementById('ot-' + id); if (node) node.disabled = !live || !!pending(); });
        const retry = document.getElementById('ot-retry'); if (retry) retry.disabled = !live || !pending();
        const start = document.getElementById('ot-start'); if (start) start.disabled = !live || !!pending() || frame.work_order === 'Idle';
        const labels = { conveyor_jam: ['Inject conveyor jam', 'Clear conveyor jam'], sensor_failure: ['Fail position sensor', 'Restore position sensor'], guard_open: ['Open guard', 'Close guard'], power_loss: ['Remove power', 'Restore power'] };
        Object.entries(labels).forEach(([id, labels]) => text(id, labels[frame[id] ? 1 : 0]));
        bind('start', () => send('start')); bind('stop', () => send('stop')); bind('reset', () => send('reset'));
        Object.keys(labels).forEach(fault => bind(fault, () => send('fault', fault)));
        bind('retry', () => { const saved = pending(); if (saved) $setTag('command', JSON.stringify(saved)); });
        bind('discard', () => { sessionStorage.removeItem('simu54.pending'); text('command-status', 'Local retry discarded. This does not cancel a command already accepted by Manufacturing.'); });
    } catch (_) {
        text('connection', 'Stale / disconnected');
        text('state', 'Telemetry unavailable');
    } finally { refreshing = false; }
};
window.simu54Timer = setInterval(refresh, 500);
await refresh();

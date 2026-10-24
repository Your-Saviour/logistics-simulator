"""Acceptance against PHP, SQL and native HELICS; all business writes use HTTP/wire."""
import argparse
import json
import os
from pathlib import Path
import time
from uuid import uuid4

import httpx
import psycopg
from psycopg.rows import dict_row

CONTROL = Path('/control')


def wait(fetch, condition, label, timeout=150):
    deadline = time.monotonic() + timeout
    last = None
    while time.monotonic() < deadline:
        try:
            last = fetch()
            if condition(last):
                return last
        except (httpx.HTTPError, FileNotFoundError, json.JSONDecodeError):
            pass
        time.sleep(.1)
    raise AssertionError(f'Timed out waiting for {label}: {last}')


def peer():
    return json.loads((CONTROL / 'peer-state.json').read_text())


def rows(sql, params=()):
    with psycopg.connect(os.environ['DATABASE_URL'], row_factory=dict_row) as db:
        return db.execute(sql, params).fetchall()


def main(phase):
    with httpx.Client(base_url='http://shipping-api:8000', auth=(os.environ['APP_USERNAME'], os.environ['APP_PASSWORD']), timeout=10) as client:
        def get(path):
            response = client.get(path)
            response.raise_for_status()
            return response.json()
        def status():
            return get('/api/status')
        def snapshot():
            return get('/api/shipping')
        def order():
            return snapshot()['orders'][0]
        def command(action, reference):
            current = status()
            body = {'run_id': current['run']['id'], 'epoch': current['run']['epoch'],
                    'due_at': max(current['run']['granted'], current['run']['requested']) + 5,
                    'action': action, 'reference': reference}
            key = 'native-' + action + '-' + str(uuid4())
            response = client.post('/api/shipping/commands', json=body, headers={'Idempotency-Key': key})
            assert response.status_code == 200, response.text
            return response.json()
        def adapter_command(operation, epoch=None):
            session = rows('SELECT session_id FROM shipping_adapter_sessions WHERE run_id=%s', (os.environ['FEDERATION_RUN_ID'],))[0]['session_id']
            return httpx.post('http://shipping-adapter:8010/v1/commands',
                              headers={'Authorization': 'Bearer ' + os.environ['HELICS_ADAPTER_TOKEN']},
                              json={'version': '1.0', 'request_id': str(uuid4()), 'run_id': os.environ['FEDERATION_RUN_ID'],
                                    'epoch': epoch or os.environ['FEDERATION_EPOCH'], 'session_id': str(session),
                                    'operation': operation, 'payload': {}}, timeout=10)

        if phase == 'lifecycle':
            initial = wait(status, lambda s: s['run']['mode'] == 'helics' and any(j['due_at'] == 20 for j in s['jobs']), 'future native customer order accepted')
            original = wait(peer, lambda s: s.get('granted') == 1, 'controlled peer native grant one')
            event_id = original['order_event_id']
            assert initial['run']['granted'] < 20 and snapshot()['orders'] == []
            assert len(rows('SELECT id FROM jobs WHERE idempotency_key=%s', ('boundary:' + event_id,))) == 1
            assert rows('SELECT status FROM jobs WHERE idempotency_key=%s', ('boundary:' + event_id,))[0]['status'] != 'completed'
            # The adapter rejects a stale epoch without creating a native operation.
            stale = adapter_command('initialize', str(uuid4()))
            assert stale.status_code == 409, stale.text
            (CONTROL / 'future.release').touch()
            created = wait(snapshot, lambda s: len(s['orders']) == 1, 'grant twenty creates customer order')['orders'][0]
            assert created['customer'] == 'NATIVE-CUSTOMER' and created['status'] == 'new'
            assert created['correlation_id'] == original['order_correlation_id']
            assert len(created['lines']) == 2 and not created['autonomous']
            assert next(h for h in created['history'] if h['event'] == 'created')['simulation_time'] >= 20
            command('fulfil', created['id'])
            ready = wait(order, lambda o: o['status'] == 'ready', 'typed shortage/replenishment/physical receipt lifecycle')
            events = [h['event'] for h in ready['history']]
            assert 'shortage' in events and 'production_stock_received' in events
            assert all(line['received'] == line['quantity'] and line['reservation_id'] and line['transfer_id'] for line in ready['lines'])
            assert len([i for i in ready['intents'] if i['kind'] == 'reserve']) == 3
            assert len([i for i in ready['intents'] if i['kind'] == 'produce']) == 1
            assert all(i['state'] == 'completed' for i in ready['intents'])
            assert len(rows('SELECT event_id FROM shipping_incoming_events WHERE event_id=%s', (event_id,))) == 1
            assert len(rows('SELECT id FROM shipping_commands c JOIN jobs j USING(id) WHERE j.idempotency_key=%s', ('boundary:' + event_id,))) == 1
            command('pack', created['id'])
            wait(order, lambda o: o['status'] == 'packed', 'employee packing')
            command('dispatch', created['id'])
            travelling = wait(order, lambda o: o['status'] == 'in_transit', 'typed carrier departure per line')
            eta = wait(peer, lambda s: len(s['planned_etas']) == 2, 'two line carrier plans')['planned_etas']
            wait(status, lambda s: s['run']['granted'] > max(eta) + 3, 'grant passes planned ETA')
            still_travelling = order()
            assert still_travelling['status'] == 'in_transit' and still_travelling['shipment']['status'] == 'in_transit'
            assert still_travelling['shipment']['confirmation_id'] is None
            assert len([i for i in still_travelling['intents'] if i['kind'] == 'deliver' and i['state'] == 'pending']) == 2
            (CONTROL / 'delivery.release').touch()
            partial = wait(order, lambda o: len([i for i in o['intents'] if i['kind'] == 'deliver' and i['state'] == 'completed']) == 1, 'first line destination receipt')
            assert partial['status'] == 'in_transit' and partial['shipment']['status'] == 'in_transit'
            assert partial['shipment']['confirmation_id'] is None
            (CONTROL / 'delivery.final').touch()
            delivered = wait(order, lambda o: o['status'] == 'delivered', 'explicit destination receipts for every line')
            assert delivered['shipment']['status'] == 'delivered' and delivered['shipment']['confirmation_id']
            assert all(i['state'] == 'completed' for i in delivered['intents'])
            assert len([h for h in delivered['history'] if h['event'] == 'delivered']) == 2
            state = wait(peer, lambda s: len(s['received']) == 10, 'all typed shipping intent outputs')
            assert set(x['type'] for x in state['received']) == {'storage.request.v1', 'manufacturing.demand.v1', 'storage.pick.v1', 'storage.transfer.v1', 'logistics.request.v1'}
            assert not rows("SELECT id FROM shipping_commands WHERE outcome='rejected'")
            current = status()
            assert current['run']['state'] == 'running' and current['run']['committed'] <= current['run']['granted'] <= current['run']['requested']
            assert current['providers'] == dict.fromkeys(('orders', 'goods', 'carrier'), 'helics') and current['effects'] == 0
            # Save only nonsecret evidence for the second verifier process.
            (CONTROL / 'verified.json').write_text(json.dumps({'run_id': current['run']['id'], 'epoch': current['run']['epoch'],
                                                             'order_id': delivered['id'], 'shipment_id': delivered['shipment']['id'],
                                                             'intent_count': len(delivered['intents']), 'history_count': len(delivered['history'])}))
            print('PASS native future input waits grant; durable native duplicate creates one order; stale adapter epoch rejected', flush=True)
            print('PASS typed multiline shortage → physical replenishment → reserve all → pick → transfer → receipt → pack → perline departure/destination receipt', flush=True)
            print('PASS planned ETA alone never confirms delivery; both destination receipts required; no synthetic effects', flush=True)
            (CONTROL / 'inject-owner').touch()
            stalled = wait(status, lambda s: s['run']['state'] == 'stalled', 'unauthorized native source endpoint fences controller')
            rogue = wait(peer, lambda s: bool(s.get('rogue_event_id')), 'unauthorized native event captured')['rogue_event_id']
            assert 'Boundary owner/routing mismatch' in stalled['run']['error'], stalled['run']
            assert not rows('SELECT event_id FROM shipping_incoming_events WHERE event_id=%s', (rogue,))
            assert len(snapshot()['orders']) == 1 and order()['status'] == 'delivered'
            print('PASS valid customer envelope from unauthorized actual native endpoint rejected without a second order', flush=True)
        elif phase == 'restart':
            saved = json.loads((CONTROL / 'verified.json').read_text())
            headers = {'Authorization': 'Bearer ' + os.environ['HELICS_ADAPTER_TOKEN']}
            health = wait(lambda: httpx.get('http://shipping-adapter:8010/v1/health', headers=headers, timeout=5).json(),
                          lambda h: h.get('state') == 'stalled', 'adapter restart fences native epoch', timeout=30)
            response = adapter_command('initialize')
            assert response.status_code == 409, response.text
            current = status()
            assert current['run']['state'] == 'stalled'
            assert (current['run']['id'], current['run']['epoch']) == (saved['run_id'], saved['epoch'])
            assert order()['id'] == saved['order_id'] and order()['status'] == 'delivered'
            assert order()['shipment']['id'] == saved['shipment_id'] and len(order()['intents']) == saved['intent_count']
            assert current['effects'] == 0
            print('PASS same-journal adapter restart remains stalled, initialize rejected, run/epoch and delivered shipment retained', flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('phase', choices=['lifecycle', 'restart'])
    main(parser.parse_args().phase)

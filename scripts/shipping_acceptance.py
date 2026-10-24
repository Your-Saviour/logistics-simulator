"""Shipping V1 acceptance against real, disposable production roles."""
import argparse
import json
import os
import time
from uuid import uuid4

import httpx
from simulator.handling_contracts import validate_snapshot, validate_movement


def wait(client, path, predicate, timeout=90):
    deadline = time.monotonic() + timeout
    last = None
    while time.monotonic() < deadline:
        try:
            response = client.get(path)
            response.raise_for_status()
            last = response.json()
            if predicate(last):
                return last
        except httpx.HTTPError as exc:
            last = str(exc)
        time.sleep(.2)
    raise AssertionError(f'Timed out waiting for {path}: {last}')


def verify(phase=None):
    if 'APP_USERNAME' in os.environ:
        operator = (os.environ['APP_USERNAME'], os.environ['APP_PASSWORD'])
        identity = next(account for account in json.loads(os.environ['APP_IDENTITIES']) if account['role'] == 'employee')
        employee = (identity['username'], identity['password'])
    else:
        operator = (os.environ['SHIPPING_USERNAME'], os.environ['SHIPPING_PASSWORD'])
        employee = ('employee', os.environ['SHIPPING_EMPLOYEE_PASSWORD'])
    with httpx.Client(base_url='http://shipping-api:8000', auth=operator, timeout=10) as client:
        wait(client, '/api/status' if phase == 'queue' else '/api/health/ready', lambda x: True)
        if phase == 'recovered':
            snapshot = wait(client, '/api/shipping', lambda s: any(o['customer'] == 'Restart durable order' for o in s['orders']))
            assert len([o for o in snapshot['orders'] if o['customer'] == 'Restart durable order']) == 1
            print('shipping V1: pending production command survives worker restart exactly once', flush=True)
            return
        if phase != 'queue':
            run = client.get('/api/status').json()['run']
            client.post('/api/control/reset', json={'confirm_run_id': run['id']}).raise_for_status()
            client.post('/api/control/speed', json={'speed': 20}).raise_for_status()
        def submit(action, expected='completed', key=None, **fields):
            run = client.get('/api/status').json()['run']
            body = {'run_id': run['id'], 'epoch': run['epoch'], 'due_at': max(run['granted'], run['requested']) + 25, 'action': action, **fields}
            headers = {'Idempotency-Key': key or uuid4().hex}
            response = client.post('/api/shipping/commands', json=body, headers=headers, auth=employee)
            assert response.status_code == 200, response.text
            command = response.json()
            replay = client.post('/api/shipping/commands', json=body, headers=headers, auth=employee)
            assert replay.status_code == 200 and replay.json()['id'] == command['id'], replay.text
            changed = {**body, 'due_at': body['due_at'] + 1}
            assert client.post('/api/shipping/commands', json=changed, headers=headers, auth=employee).status_code == 409
            if expected is not None:
                snap = wait(client, '/api/shipping', lambda s: any(c['id'] == command['id'] and c['outcome'] != 'pending' for c in s['commands']))
                outcome = next(c for c in snap['commands'] if c['id'] == command['id'])
                assert outcome['outcome'] == expected, outcome
            return command['id']
        if phase == 'queue':
            submit('create', expected=None, key='acceptance:restart', customer='Restart durable order', destination='CUSTOMER-A', lines=[{'sku': 'PRODUCT', 'quantity': 1}])
            assert not any(o['customer'] == 'Restart durable order' for o in client.get('/api/shipping').json()['orders'])
            print('shipping V1: command queued durably while worker stopped', flush=True)
            return
        assert httpx.get('http://shipping-api:8000/api/shipping').status_code == 401
        assert client.post('/api/control/hold', json={}, auth=employee).status_code == 403
        order_id = submit('create', customer='HTTP multiline order', destination='CUSTOMER-A', lines=[{'sku': 'PRODUCT', 'quantity': 4}, {'sku': 'COMPONENT', 'quantity': 3}])
        submit('pack', expected='rejected', reference=order_id)
        submit('dispatch', expected='rejected', reference=order_id)
        submit('fulfil', reference=order_id)
        order = wait(client, '/api/shipping/orders/' + order_id, lambda o: o['status'] == 'ready')
        assert len(order['lines']) == 2 and all(l['received'] == l['quantity'] for l in order['lines'])
        assert any(h['event'] == 'shortage' for h in order['history'])
        assert any(h['event'] == 'produced' for h in order['history'])
        snapshot=client.get('/api/shipping').json()
        handling=snapshot['handling']
        validate_snapshot(handling['units'],snapshot['run_id'],snapshot['epoch'])
        for movement in handling['movements']:
            validate_movement(movement,snapshot['run_id'],snapshot['epoch'])
        units={unit['id']:unit for unit in handling['units']}
        selected=[]
        for line in order['lines']:
            selected.extend(line['unit_ids'])
            assert line['unit_ids'] and sum(units[key]['contents'][0]['quantity'] for key in line['unit_ids'])==line['quantity']
            assert all(units[key]['state']=='reserved' and units[key]['position'] for key in line['unit_ids'])
        assert len(selected)==len(set(selected))
        submit('pack', reference=order_id)
        submit('cancel', expected='rejected', reference=order_id)
        submit('dispatch', reference=order_id)
        order = wait(client, '/api/shipping/orders/' + order_id, lambda o: o['status'] == 'delivered')
        assert order['shipment']['confirmation_id'] and order['shipment']['journey_id']
        snapshot=client.get('/api/shipping').json()
        validate_snapshot(snapshot['handling']['units'],snapshot['run_id'],snapshot['epoch'])
        units={unit['id']:unit for unit in snapshot['handling']['units']}
        assert all(units[key]['state']=='dispatched' and units[key]['position'] is None for key in selected)
        assert all(i['state'] == 'completed' for i in order['intents'])
        line_ids = {line['id'] for line in order['lines']}
        for kind, result in [('dispatch', 'departed'), ('deliver', 'delivered')]:
            legs = [intent for intent in order['intents'] if intent['kind'] == kind]
            assert len(legs) == len(line_ids) and {leg['line_id'] for leg in legs} == line_ids
            assert all(leg['response']['result'] == result for leg in legs)
        assert order['shipment']['confirmation_id'] in {i['fact_id'] for i in order['intents'] if i['kind'] == 'deliver'}
        events = [h['event'] for h in order['history']]
        assert events.index('departed') < events.index('delivered')
        cancelled = submit('create', customer='Cancel before fulfilment', destination='CUSTOMER-A', lines=[{'sku': 'PRODUCT', 'quantity': 1}])
        submit('cancel', reference=cancelled)
        assert client.get('/api/shipping/orders/' + cancelled).json()['status'] == 'cancelled'
        assert client.post('/api/shipping/commands', json={}, auth=employee).status_code == 422
        print('shipping V1: real HTTP employee auth, multiline shortage/replenishment/receipt, rejection, cancellation, replay/conflict and confirmed delivery passed', flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--phase', choices=['queue', 'recovered'])
    verify(parser.parse_args().phase)

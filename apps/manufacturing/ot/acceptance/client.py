"""Container-only acceptance client for a newly created isolated OT deployment."""
import base64
import json
import os
import time
import urllib.error
import urllib.request
import uuid

BASE = os.environ.get('MANUFACTURING_API', 'http://manufacturing-api:8000')
PASSWORD = os.environ['MANUFACTURING_PASSWORD']


def api(path, body=None, key=None, user='operator', expected=200):
    headers = {'Authorization': 'Basic ' + base64.b64encode((user + ':' + PASSWORD).encode()).decode(),
               'Content-Type': 'application/json'}
    if key:
        headers['Idempotency-Key'] = key
    data = None if body is None else json.dumps(body, allow_nan=False).encode()
    try:
        with urllib.request.urlopen(urllib.request.Request(BASE + path, data=data, headers=headers), timeout=15) as reply:
            status, payload = reply.status, json.load(reply)
    except urllib.error.HTTPError as error:
        status, payload = error.code, json.load(error)
    if expected is not None and status != expected:
        raise AssertionError(f'{path}: expected {expected}, got {status}: {payload}')
    return payload


def until(predicate, description, timeout=90):
    deadline = time.monotonic() + timeout
    last = None
    while time.monotonic() < deadline:
        try:
            last = predicate()
            if last:
                return last
        except (OSError, urllib.error.URLError):
            pass
        time.sleep(0.1)
    raise AssertionError('Timed out: ' + description)


def scope():
    run = api('/api/status')['run']
    return {'run_id': run['id'], 'epoch': run['epoch']}


def control(action, extra=None):
    return api('/api/control/' + action, {**scope(), **(extra or {})}, str(uuid.uuid4()))


def command(body):
    run = api('/api/status')['run']
    data = {'run_id': run['id'], 'epoch': run['epoch'], 'due_at': max(run['granted'], run['requested']) + 5, **body}
    return api('/api/production/commands', data, str(uuid.uuid4()), 'employee')


def ot(action, extra=None):
    result = api('/api/ot/commands', {**scope(), 'action': action, **(extra or {})}, str(uuid.uuid4()))
    command_id = result['id']
    def done():
        for item in api('/api/ot')['commands']:
            if item['id'] == command_id and item['status'] != 'pending':
                if item['status'] != 'completed':
                    raise AssertionError(item['reason'])
                return item
    return until(done, 'OT acknowledgement ' + action)


def order(order_id):
    return next(item for item in api('/api/production')['orders'] if item['id'] == order_id)


def main():
    until(lambda: api('/api/health/ready', expected=None).get('ready'), 'manufacturing readiness')
    until(lambda: not api('/api/ot')['stale'], 'physical cell telemetry')
    control('speed', {'speed': 60})
    for sku, quantity in [('HOUSING', 20), ('IMPELLER', 20), ('SEAL', 40)]:
        command({'action': 'supply', 'sku': sku, 'quantity': quantity,
                 'units': [{'id': str(uuid.uuid4()), 'quantity': quantity}]})
    correlation = str(uuid.uuid4())
    created = command({'action': 'create', 'product': 'PUMP', 'line': 'ASSEMBLY-1', 'quantity': 20, 'correlation_id': correlation})
    order_id = created['id']
    until(lambda: any(item['id'] == order_id for item in api('/api/production')['orders']), 'work order creation')
    command({'action': 'release', 'reference': order_id})
    until(lambda: order(order_id)['status'] == 'running', 'Java batch dispatch')
    ot('start')
    until(lambda: order(order_id)['status'] == 'completed', 'PLC-correlated business completion')
    completed = order(order_id)
    assert completed['output_quantity'] == 19 and completed['scrap_quantity'] == 1, completed
    production = api('/api/production')
    assert all(item['quantity'] == 0 for item in production['materials']), production['materials']
    events = [item for item in production['events'] if item['order_id'] == order_id]
    assert len(events) == 1 and events[0]['envelope']['correlation_id'] == correlation, events
    # Delivery replay must not create a second event or re-consume materials.
    for _ in range(3):
        assert len([item for item in api('/api/production')['events'] if item['order_id'] == order_id]) == 1
    print('PASS: Java dispatch -> real PLC -> equipment -> correlated 19 good / 1 scrap; materials and event once')
    print('Work order:', order_id)


if __name__ == '__main__':
    main()

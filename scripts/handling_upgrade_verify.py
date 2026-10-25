"""Exercise native migrators against pre-handling-unit departmental databases."""
import hashlib
import json
import os
import sys
import time
from pathlib import Path
from uuid import uuid4

import httpx
import psycopg

ROOT = Path('/repo')
MIGRATIONS = {
    'storage': ('apps/storage/backend/migrations', 9, 'warehouse'),
    'manufacturing': ('apps/manufacturing/backend/src/main/resources/migrations', 9, 'production'),
    'shipping': ('apps/shipping/migrations', 10, 'shipping'),
    'logistics': ('apps/logistics/backend/migrations', 8, 'transport'),
}


def convert(databases, identities, record):
    for app, domain in (('storage', 'warehouse'), ('manufacturing', 'production')):
        identity = identities[app]
        with httpx.Client(base_url=f'http://{app}-api:8000', auth=(identity['username'], identity['password']), timeout=10) as client, psycopg.connect(databases[app], autocommit=True) as db:
            client.post('/api/control/resume', json={}).raise_for_status()

            def submit(quantity):
                key = 'upgrade-conversion-' + str(uuid4())
                manifest = [{'id': str(uuid4()), 'quantity': 4, 'position': 'storage.raw.r01.b01.l01' if app == 'storage' else 'manufacturing.cell01.input01'},
                            {'id': str(uuid4()), 'quantity': quantity - 4, 'position': 'storage.raw.r01.b02.l01' if app == 'storage' else 'manufacturing.cell01.input02'}]
                for attempt in range(20):
                    current = client.get('/api/status').json()['run']
                    body = {'run_id': record[app]['run_id'], 'epoch': record[app]['epoch'], 'due_at': max(current['granted'], current['requested']) + 2,
                            'action': 'convert', 'sku': 'UPGRADE-COMPONENT', 'quantity': quantity, 'units': manifest}
                    if app == 'storage':
                        body.update(location='UPGRADE-RAW', correlation_id=str(uuid4()))
                    response = client.post(f'/api/{domain}/commands', json=body, headers={'Idempotency-Key': key})
                    if response.status_code != 409 or 'Schedule' not in response.text:
                        break
                response.raise_for_status()
                command = response.json()['id']
                deadline = time.monotonic() + 60
                while True:
                    status = db.execute(f'SELECT status FROM {domain}_commands WHERE id=%s', (command,)).fetchone()[0]
                    if status != 'pending':
                        return command, key, body, status
                    assert time.monotonic() < deadline, (app, command, 'conversion timed out')
                    time.sleep(.1)

            failed, _, _, status = submit(9)
            assert status == 'rejected', (app, failed, status)
            assert db.execute(f'SELECT count(*) FROM {domain}_handling_units').fetchone()[0] == 0, app
            command, key, body, status = submit(10)
            assert status == 'completed', (app, command, status)
            repeated = client.post(f'/api/{domain}/commands', json=body, headers={'Idempotency-Key': key})
            repeated.raise_for_status()
            assert repeated.json()['id'] == command, app
            changed = {**body, 'units': [{**unit, 'id': str(uuid4())} for unit in body['units']]}
            assert client.post(f'/api/{domain}/commands', json=changed, headers={'Idempotency-Key': key}).status_code == 409, app
            client.post('/api/control/hold', json={}).raise_for_status()
            record[app]['conversion'] = {'id': command, 'units': body['units'], 'invalid_quantity_rejected': True, 'retry_same_identity': True, 'mutated_retry_rejected': True}
            print(app, 'conversion PASS', flush=True)


def main():
    phase = sys.argv[1]
    databases = json.loads(os.environ['UPGRADE_DATABASES'])
    identities = json.loads(os.environ['UPGRADE_IDENTITIES'])
    evidence = Path('/evidence/upgrade.json')
    record = {} if phase == 'seed' else json.loads(evidence.read_text())
    if phase == 'convert':
        convert(databases, identities, record)
        evidence.write_text(json.dumps(record, indent=2))
        return
    for app, (directory, first, prefix) in MIGRATIONS.items():
        files = sorted((ROOT / directory).glob('*.sql'))
        with psycopg.connect(databases[app]) as db:
            if phase == 'seed':
                db.execute('CREATE TABLE schema_migrations(name text PRIMARY KEY,checksum text NOT NULL,applied_at timestamptz NOT NULL DEFAULT clock_timestamp())')
                applied = {}
                for path in files:
                    if int(path.name[:3]) >= first:
                        continue
                    raw = path.read_bytes()
                    checksum = hashlib.sha256(raw).hexdigest()
                    db.execute(raw.decode())
                    db.execute('INSERT INTO schema_migrations(name,checksum) VALUES (%s,%s)', (path.name, checksum))
                    applied[path.name] = checksum
                run, epoch = str(uuid4()), str(uuid4())
                db.execute("INSERT INTO runs(id,epoch,mode,state) VALUES (%s,%s,'standalone','held')", (run, epoch))
                if app == 'storage':
                    config = {'locations': [{'code': 'UPGRADE-RAW', 'capacity': 100}], 'catalog': [{'sku': 'UPGRADE-COMPONENT', 'kind': 'raw'}]}
                    db.execute('INSERT INTO warehouse_config VALUES (%s,%s::jsonb)', (run, json.dumps(config)))
                    db.execute("INSERT INTO warehouse_locations VALUES (%s,'UPGRADE-RAW',100)", (run,))
                    db.execute("INSERT INTO warehouse_catalog VALUES (%s,'UPGRADE-COMPONENT','raw')", (run,))
                    db.execute("INSERT INTO warehouse_stock VALUES (%s,'UPGRADE-COMPONENT','UPGRADE-RAW',10,0)", (run,))
                elif app == 'manufacturing':
                    db.execute("INSERT INTO production_materials VALUES (%s,'UPGRADE-COMPONENT',10)", (run,))
                record[app] = {'run_id': run, 'epoch': epoch, 'old_checksums': applied}
                if app in ('shipping', 'logistics'):
                    legacy, correlation = str(uuid4()), str(uuid4())
                    db.execute("INSERT INTO jobs(id,run_id,epoch,idempotency_key,due_at,payload,status) VALUES (%s,%s,%s,'upgrade-history',0,'{}','completed')", (legacy, run, epoch))
                    record[app].update(legacy_record_id=legacy, legacy_correlation_id=correlation)
                    if app == 'shipping':
                        line = str(uuid4())
                        db.execute("INSERT INTO shipping_orders(id,run_id,customer,destination,correlation_id,status) VALUES (%s,%s,'UPGRADE-CUSTOMER','CUSTOMER-A',%s,'delivered')", (legacy, run, correlation))
                        db.execute("INSERT INTO shipping_lines(id,order_id,sku,quantity,reserved,received) VALUES (%s,%s,'UPGRADE-PRODUCT',10,10,10)", (line, legacy))
                        record[app]['legacy_line_id'] = line
                    else:
                        db.execute("INSERT INTO transport_commands(id,run_id,command,status) VALUES (%s,%s,'{}','completed')", (legacy, run))
                        db.execute("INSERT INTO transport_transfers(id,run_id,epoch,correlation_id,route,origin,destination,journey_seconds,sku,quantity,status,custody) VALUES (%s,%s,%s,%s,'UPGRADE-ROUTE','WAREHOUSE','CUSTOMER',10,'UPGRADE-PRODUCT',10,'received','destination')", (legacy, run, epoch, correlation))
            else:
                identity = identities[app]
                deadline = time.monotonic() + 90
                while True:
                    try:
                        response = httpx.get(f'http://{app}-api:8000/api/status', auth=(identity['username'], identity['password']), timeout=5)
                        response.raise_for_status()
                        break
                    except httpx.HTTPError:
                        if time.monotonic() >= deadline:
                            raise
                        time.sleep(.5)
                applied = dict(db.execute('SELECT name,checksum FROM schema_migrations').fetchall())
                assert applied == {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in files}, (app, applied)
                assert all(applied[name] == checksum for name, checksum in record[app]['old_checksums'].items()), app
                run, epoch = record[app]['run_id'], record[app]['epoch']
                assert db.execute('SELECT epoch::text,state FROM runs WHERE id=%s', (run,)).fetchone() == (epoch, 'held'), app
                conversion = record[app].get('conversion')
                if conversion:
                    units = db.execute(f'SELECT id::text,quantity,position FROM {prefix}_handling_units ORDER BY id').fetchall()
                    assert units == sorted((unit['id'], unit['quantity'], unit['position']) for unit in conversion['units']), (app, units)
                    assert db.execute(f'SELECT count(*) FROM {prefix}_unit_movements').fetchone()[0] == 0, app
                    if app == 'storage':
                        assert db.execute('SELECT DISTINCT conversion_id::text FROM warehouse_handling_units').fetchall() == [(conversion['id'],)]
                    else:
                        assert db.execute('SELECT DISTINCT command_id::text FROM production_handling_units').fetchall() == [(conversion['id'],)]
                    assert db.execute(f"SELECT count(*) FROM {prefix}_handling_units WHERE run_id<>%s OR epoch<>%s OR barcode<>'HU-'||upper(replace(id::text,'-',''))", (run, epoch)).fetchone()[0] == 0, app
                else:
                    assert db.execute(f'SELECT count(*) FROM {prefix}_handling_units').fetchone()[0] == 0, app
                if app == 'storage':
                    assert db.execute("SELECT on_hand,reserved FROM warehouse_stock WHERE run_id=%s AND sku='UPGRADE-COMPONENT'", (run,)).fetchone() == (10, 0)
                elif app == 'manufacturing':
                    assert db.execute("SELECT quantity FROM production_materials WHERE run_id=%s AND sku='UPGRADE-COMPONENT'", (run,)).fetchone() == (10,)
                elif app == 'shipping':
                    legacy = record[app]['legacy_record_id']
                    assert db.execute('SELECT correlation_id::text,status FROM shipping_orders WHERE id=%s', (legacy,)).fetchone() == (record[app]['legacy_correlation_id'], 'delivered')
                    assert db.execute('SELECT id::text,quantity,reserved,received FROM shipping_lines WHERE order_id=%s', (legacy,)).fetchone() == (record[app]['legacy_line_id'], 10, 10, 10)
                elif app == 'logistics':
                    assert db.execute('SELECT correlation_id::text,quantity,status,custody,unit_ids FROM transport_transfers WHERE id=%s', (record[app]['legacy_record_id'],)).fetchone() == (record[app]['legacy_correlation_id'], 10, 'received', 'destination', [])
                record[app][phase] = 'passed: checksums, scope, quantities and explicit unit identities preserved' if conversion else 'passed: native migration, old checksums/scope/legacy quantities preserved, no invented units'
                print(app, phase, 'PASS', flush=True)
    evidence.write_text(json.dumps(record, indent=2))


if __name__ == '__main__':
    main()

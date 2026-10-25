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


def main():
    phase = sys.argv[1]
    databases = json.loads(os.environ['UPGRADE_DATABASES'])
    identities = json.loads(os.environ['UPGRADE_IDENTITIES'])
    evidence = Path('/evidence/upgrade.json')
    record = {} if phase == 'seed' else json.loads(evidence.read_text())
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
                    db.execute("INSERT INTO warehouse_locations VALUES (%s,'UPGRADE-RAW',100)", (run,))
                    db.execute("INSERT INTO warehouse_catalog VALUES (%s,'UPGRADE-COMPONENT','raw')", (run,))
                    db.execute("INSERT INTO warehouse_stock VALUES (%s,'UPGRADE-COMPONENT','UPGRADE-RAW',10,0)", (run,))
                elif app == 'manufacturing':
                    db.execute("INSERT INTO production_materials VALUES (%s,'UPGRADE-COMPONENT',10)", (run,))
                record[app] = {'run_id': run, 'epoch': epoch, 'old_checksums': applied}
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
                assert db.execute(f'SELECT count(*) FROM {prefix}_handling_units').fetchone()[0] == 0, app
                if app == 'storage':
                    assert db.execute("SELECT on_hand,reserved FROM warehouse_stock WHERE run_id=%s AND sku='UPGRADE-COMPONENT'", (run,)).fetchone() == (10, 0)
                elif app == 'manufacturing':
                    assert db.execute("SELECT quantity FROM production_materials WHERE run_id=%s AND sku='UPGRADE-COMPONENT'", (run,)).fetchone() == (10,)
                record[app][phase] = 'passed: native migration, old checksums/scope/legacy quantities preserved, no invented units'
                print(app, phase, 'PASS', flush=True)
    evidence.write_text(json.dumps(record, indent=2))


if __name__ == '__main__':
    main()

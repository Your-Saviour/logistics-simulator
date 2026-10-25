"""Real native custody fixture plus operational fleet evidence.

Runs only in the disposable verifier container. No fabricated movement/proofs are
posted to Fleet. SQL remains acceptance-only observation of native-owned state.
"""
import json
import os
from pathlib import Path
import threading
import time
from uuid import uuid4

import httpx
import handling_factory_verify as native
from fleet_factory_evidence import sample_frame
from fleet.navigation import Navigation, intersects
from twin.fleet_projection import validate_fleet

APPS = ('storage', 'manufacturing', 'shipping', 'logistics')
EVIDENCE = Path('/evidence/fleet-evidence.json')


def write(path, value):
    path.write_text(json.dumps(value, indent=2, default=str))
    path.chmod(0o600)


def main():
    record = {'status': 'running', 'scope': 'native two-cycle custody plus fleet physical gates, contention and held process restart',
              'twin_present': os.getenv('FLEET_FACTORY_WITH_TWIN') == '1',
              'layout_acceptance': 'requires independently validated fixed navigation/catalog; this harness never changes geometry',
              'samples': 0, 'max_assigned': 0, 'traffic_waits': [], 'categories': [], 'steps': []}
    identities = json.loads(os.environ['FACTORY_IDENTITIES'])
    clients = {name: httpx.Client(base_url=f'http://{name}-api:8000', auth=(identity['username'], identity['password']), timeout=10)
               for name, identity in identities.items()}
    fleet = httpx.Client(base_url=os.environ['FLEET_URL'], headers={'Authorization': 'Bearer ' + os.environ['FLEET_TOKEN']}, timeout=5)
    topology = json.loads(Path('/app/contracts/fleet/v1/navigation.json').read_text())
    navigation = Navigation(topology)
    stop, errors = threading.Event(), []
    samples, by_job = [], {}
    record['reservation_archives'] = {}
    last_revision, restart_done = -1, False
    old_wait = native.wait
    native.wait = lambda fetch, predicate, label, timeout=360: old_wait(fetch, predicate, label, timeout=timeout)

    def snapshot():
        response = fleet.get('/v1/snapshot'); response.raise_for_status(); return response.json()

    def get(app, path):
        response = clients[app].get('/api/' + path); response.raise_for_status(); return response.json()

    def control(app, action):
        run = get(app, 'status')['run']
        response = clients[app].post('/api/control/' + action, json={'run_id': run['id'], 'epoch': run['epoch']},
                                     headers={'Idempotency-Key': uuid4().hex})
        response.raise_for_status()

    def signature(value):
        return {'robots': sorted((robot['id'], robot['pose'], robot.get('carried_unit_id'), robot.get('fork_height'), robot.get('fork_offset')) for robot in value['robots']),
                'reservations': sorted((item['resource'], item['job_id']) for item in value['reservations']),
                'jobs': sorted((job['id'], job['state'], job.get('carried')) for job in value['jobs'])}

    def restart(value):
        nonlocal restart_done
        for app in APPS:
            control(app, 'hold')
        held = native.wait(snapshot, lambda frame: frame['run']['state'] == 'held', 'fleet holds when native sources hold', timeout=30)
        physical = signature(held)
        time.sleep(.4)
        assert signature(snapshot()) == physical, 'Holding native scopes advanced robot/load/reservation state'
        write(Path('/evidence/fleet-restart.request'), {'generation': held['run']['generation'], 'physical': physical})
        ack = Path('/evidence/fleet-restart.ack')
        native.wait(ack.exists, bool, 'host restarts fleet process while physical state is held', timeout=180)
        recovered = native.wait(snapshot, lambda frame: frame['run']['generation'] > held['run']['generation'], 'new worker fences old generation', timeout=30)
        assert signature(recovered) == physical, 'Restart changed held pose, load, phase or physical reservations'
        record['restart'] = {'process': json.loads(ack.read_text()), 'generation_before': held['run']['generation'],
                             'generation_after': recovered['run']['generation'], 'physical': physical}
        restart_done = True
        for app in APPS:
            control(app, 'resume')
        record['steps'].append('loaded fleet process restarted under four native holds without physical state loss')
        write(EVIDENCE, record)

    def observe():
        nonlocal last_revision
        last_clock, clock_seen, debug_seen = None, time.monotonic(), 0
        while not stop.is_set():
            try:
                value = snapshot()
                validate_fleet(value)
                run = value['run']
                if run['committed'] != last_clock:
                    last_clock, clock_seen = run['committed'], time.monotonic()
                if run['state'] == 'running' and time.monotonic() - max(clock_seen, debug_seen) >= 30:
                    debug_seen = time.monotonic()
                    try:
                        response = httpx.get('http://factory-helics-broker:43542/fleet-factory-broker/root/global_time_debugging', timeout=3)
                        response.raise_for_status()
                        write(EVIDENCE.parent / 'broker-time-debug.json',
                              {'committed': last_clock, 'wall_stalled_seconds': debug_seen - clock_seen,
                               'native': response.json()})
                    except (httpx.HTTPError, ValueError) as error:
                        record['broker_debug_error'] = str(error)
                assert run['id'] == os.environ['FLEET_RUN_ID'] and run['epoch'] == os.environ['FLEET_EPOCH'], 'Fleet scope changed'
                assert run['sources'] == json.loads(os.environ['FLEET_SCOPE']), 'Fleet/native scope mapping differs'
                assert run['revision'] >= last_revision, 'Fleet revision regressed'
                last_revision = run['revision']
                resources = [item['resource'] for item in value['reservations']]
                assert len(resources) == len(set(resources)), 'Physical resource granted twice'
                active = [job for job in value['jobs'] if job['robot_id'] and job['state'] != 'completed']
                assert len(active) == len({job['robot_id'] for job in active}), 'Robot has competing live jobs'
                assert len(active) == len({job['unit_id'] for job in active}), 'Whole unit has competing robot assignments'
                for index, robot in enumerate(value['robots']):
                    for other in value['robots'][index + 1:]:
                        assert not intersects(navigation._rectangle(tuple(robot['pose'])), navigation._rectangle(tuple(other['pose']))), 'Reported robot envelopes overlap'
                record['samples'] += 1
                record['max_assigned'] = max(record['max_assigned'], len(active))
                for job in value['jobs']:
                    old_route = by_job.get(job['id'], {}).get('route')
                    by_job[job['id']] = {**job, 'route': job.get('route') or old_route}
                    if job.get('waiting_reason') == 'traffic' and job['id'] not in record['traffic_waits']:
                        record['traffic_waits'].append(job['id'])
                if len(samples) < 5000:
                    sample, claims = sample_frame(value)
                    digest = sample['reservation_digest']
                    if digest not in record['reservation_archives']:
                        filename = f'reservations-{digest}.json'
                        write(EVIDENCE.parent / filename, claims)
                        record['reservation_archives'][digest] = filename
                    samples.append(sample)
                if not restart_done and any(robot.get('carried_unit_id') for robot in value['robots']):
                    restart(value)
            except httpx.HTTPError:
                pass  # Startup/dependency freshness is exercised by the native wait.
            except Exception as error:
                errors.append(str(error)); stop.set(); return
            stop.wait(.1)

    def commands(app, bodies):
        run = get(app, 'status')['run']
        due = max(run['granted'], run['requested']) + max(3,2*float(os.getenv('FACTORY_HANDOFF_QUANTUM','1')))
        ids = []
        for body in bodies:
            response = clients[app].post('/api/warehouse/commands', json={**body, 'run_id': run['id'], 'epoch': run['epoch'], 'due_at': due},
                                         headers={'Idempotency-Key': uuid4().hex})
            response.raise_for_status(); ids.append(response.json()['id'])
        def settled():
            assert not errors, errors
            return [row for row in get(app, 'warehouse')['commands'] if row['id'] in ids]
        rows = native.wait(settled, lambda result: len(result) == len(ids) and all(row['status'] != 'pending' for row in result), 'native simultaneous shelf commands', timeout=360)
        assert all(row['status'] == 'completed' for row in rows), rows
        return ids

    monitor = threading.Thread(target=observe, daemon=True)
    monitor.start()
    started = time.monotonic()
    try:
        # Keep the existing real custody, recipe, five handoff legs and fifteen
        # dropped publication checks, with all departments opted into Fleet.
        native.main()
        assert not errors, errors
        # Additional untouched whole units after the conserved order cycles:
        # two distinct shelf elevations share one exclusive floor service zone.
        units = [str(uuid4()), str(uuid4())]
        receipt = commands('storage', [{'action': 'expect', 'sku': 'COMPONENT', 'location': 'RAW-A', 'quantity': 2,
            'correlation_id': str(uuid4()), 'units': [{'id': unit, 'quantity': 1} for unit in units]}])[0]
        commands('storage', [{'action': 'receive', 'reference': receipt}])
        concurrent = commands('storage', [{'action': 'putaway', 'unit_id': unit, 'destination': f'storage.raw.r01.b01.l{level:02}'}
                                          for level, unit in enumerate(units, 1)])
        record['simultaneous_same_bay_commands'] = concurrent
        native.wait(snapshot, lambda value: all(job['state'] == 'completed' for job in value['jobs']), 'all loaded legs and empty parking returns complete', timeout=360)
        assert not errors, errors
        assert restart_done, 'No loaded fleet process restart was observed'
        assert record['traffic_waits'], 'No actual conflicting route wait was observed'
        complete = snapshot()
        pair_jobs = {job['id'] for job in complete['jobs'] if job['request']['unit_id'] in units}
        assert pair_jobs.intersection(record['traffic_waits']), 'Simultaneous same-bay requests produced no observed exclusive-service wait'
        requests = [job['request'] for job in complete['jobs']]
        categories = {
            'inbound_unload': any(r['origin'].startswith('logistics.inbound.truck') and r['destination'].startswith('logistics.inbound.dock') for r in requests),
            'shelf_putaway_retrieval': any('.r01.' in r['destination'] for r in requests) and any('.r01.' in r['origin'] for r in requests),
            'manufacturing_transfer': any(r['origin'].startswith('manufacturing.') or r['destination'].startswith('manufacturing.') for r in requests),
            'outbound_load': any(r['destination'].startswith('logistics.outbound.truck') for r in requests),
        }
        assert all(categories.values()), categories
        record['categories'] = categories
        if record['twin_present']:
            identity = json.loads(os.environ['FLEET_FACTORY_TWIN_IDENTITY'])
            with httpx.Client(base_url='http://twin-api:8000', auth=(identity['username'], identity['password']), timeout=5) as twin:
                def twin_frame():
                    response = twin.get('/api/twin'); response.raise_for_status(); return response.json()
                observed = native.wait(twin_frame, lambda frame: bool(frame.get('fleet')) and frame['fleet'].get('stale') is False and bool(frame['fleet'].get('snapshot')), 'optional Twin reports fleet without controlling it', timeout=30)
                record['twin'] = observed.get('fleet')
        record.update(status='passed', elapsed_wall_seconds=time.monotonic() - started, final_snapshot=complete)
    except Exception as error:
        record.update(status='failed', error=str(error), monitor_errors=errors, elapsed_wall_seconds=time.monotonic() - started)
        try:
            record['last_snapshot'] = snapshot()
        except Exception as dependency_error:
            record['snapshot_error'] = str(dependency_error)
        record['native_snapshots'] = {}
        for app, path in [('storage', 'warehouse'), ('manufacturing', 'production'),
                          ('shipping', 'shipping'), ('logistics', 'transport')]:
            try:
                record['native_snapshots'][app] = get(app, path)
            except Exception as dependency_error:
                record['native_snapshots'][app] = {'snapshot_error': str(dependency_error)}
        raise
    finally:
        stop.set(); monitor.join(timeout=200)
        record['physical_samples'] = samples
        record['jobs'] = list(by_job.values())
        write(EVIDENCE, record)
        legacy = Path('/evidence/evidence.json')
        if legacy.exists():
            legacy.chmod(0o600)
        for client in clients.values():
            client.close()
        fleet.close()


if __name__ == '__main__':
    os.umask(0o077)
    main()

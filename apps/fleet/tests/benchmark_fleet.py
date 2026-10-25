"""Measured scheduler workload with synthetic departmental clients, never native acceptance.

The real authenticated API, owned ledger, fenced Worker and Navigation execute all
motion. Fixture clients inject whole units only into clear source endpoints and
drain received destination stock after one simulation second. Neither fixture
operation is claimed as native business handling or robot transport.
"""
import argparse
from collections import Counter
import json
import math
import os
from pathlib import Path
import platform
import signal
import threading
import time
from urllib.parse import urlsplit, urlunsplit
from uuid import NAMESPACE_URL, uuid5

import psycopg
from psycopg import sql

from fleet.api import create_app
from fleet.initialize import validate_configuration
from fleet.navigation import Navigation, intersects
from fleet.store import FleetStore
from fleet.worker import Worker


DEPARTMENTS = ('storage', 'manufacturing', 'logistics', 'shipping')
CATEGORIES = ('inbound_unload', 'shelf_putaway', 'manufacturing_transfer', 'outbound_loading')
WARMUP, WINDOW = 120, 600


def percentile(values, quantile):
    return sorted(values)[max(0, math.ceil(quantile * len(values)) - 1)] if values else None


def identity(value):
    return str(uuid5(NAMESPACE_URL, 'simu75/scheduler-budget/' + value))


def gap(a, b):
    return math.hypot(max(a[0] - b[2], b[0] - a[2], 0), max(a[1] - b[3], b[1] - a[3], 0))


def body_rectangle(pose):
    x, z, heading = pose
    hx, hz = (.425, .525) if heading % 2 == 0 else (.525, .425)
    return x-hx, z-hz, x+hx, z+hz


def load_rectangle(position, heading=0):
    x, _, z = position
    hx, hz = (.4, .43) if heading % 2 == 0 else (.43, .4)
    return x-hx, z-hz, x+hx, z+hz


def read_state(store):
    with store.transaction() as db:
        jobs = db.execute('SELECT id,unit_id,producer,request,release_time,state,robot_id,waiting_reason,proofs,blockers,route,phase_started,progress FROM fleet_jobs ORDER BY ordinal').fetchall()
        robots = db.execute('SELECT id,pose,reported FROM fleet_robots ORDER BY id').fetchall()
        events = db.execute('SELECT id,job_id,kind,body FROM fleet_outbox ORDER BY id').fetchall()
        reservations = {r['resource'] for r in db.execute('SELECT resource FROM fleet_reservations').fetchall()}
        assigned = db.execute("SELECT job_id,simulation_time FROM fleet_audit WHERE action='assign'").fetchall()
        run = db.execute('SELECT committed,state,reason FROM fleet_runs WHERE current').fetchone()
    return jobs, robots, events, reservations, assigned, run


def endpoints(catalog, prefix, shelf=False):
    values = sorted(k for k, value in catalog.items() if k.startswith(prefix) and (not shelf or value['kind'] == 'shelf'))
    # A coprime stride distributes shelf rows, bays and all four elevations.
    return [values[(index * 7) % len(values)] for index in range(len(values))] if shelf else values


def workload(catalog):
    return {
        'inbound_unload': (endpoints(catalog, 'logistics.inbound.truck'), endpoints(catalog, 'logistics.inbound.dock')),
        'shelf_putaway': (endpoints(catalog, 'storage.inbound.dock'), endpoints(catalog, 'storage.raw.', True)),
        'manufacturing_transfer': (endpoints(catalog, 'manufacturing.cell'), endpoints(catalog, 'storage.finished.', True)),
        'outbound_loading': (endpoints(catalog, 'shipping.outbound.'), endpoints(catalog, 'logistics.outbound.truck')),
    }


def primitive_duration(a, b):
    return .5 if a[2] != b[2] else math.hypot(b[0]-a[0], b[1]-a[1])


def route_primitives(poses):
    elapsed = 0.0
    for index, (a,b) in enumerate(zip(poses, poses[1:])):
        length = primitive_duration(a,b)
        yield {'index':index, 'a':a, 'b':b, 'start':elapsed, 'end':elapsed+length,
               'kind':'turn' if a[2] != b[2] else 'translation'}
        elapsed += length


def route_pose(poses, elapsed):
    """Independent integration at1m/s and0.5s per quarter turn."""
    for primitive in route_primitives(poses):
        a,b = primitive['a'],primitive['b']
        if elapsed < primitive['end']:
            if primitive['kind']=='turn':
                return tuple(a)
            length=primitive['end']-primitive['start']
            fraction=max(0,(elapsed-primitive['start'])/length) if length else 1
            return a[0]+(b[0]-a[0])*fraction,a[1]+(b[1]-a[1])*fraction,a[2]
    return tuple(poses[-1])


def same_pose(a,b):
    return a[2]==b[2] and math.hypot(a[0]-b[0],a[1]-b[1])<1e-7


def fail_geometry(message, diagnostic):
    raise AssertionError(message+' '+json.dumps(diagnostic,sort_keys=True,default=str))


def obstacle_hits(nav, bounds):
    return [{'id':o['id'],'bounds':o['bounds']} for o in nav.topology['obstacles'] if intersects(bounds,o['bounds'])]


def validate_plan(nav, job, robot_id, counters):
    job_id=str(job['id'])
    if job_id in counters['validated_plans']:
        return
    route=job['route']
    for first,second in (('approaching','carrying'),('carrying','returning')):
        if not same_pose(route[first]['poses'][-1],route[second]['poses'][0]):
            fail_geometry('Declared route legs are discontinuous',{'robot_id':robot_id,'job_id':job_id,'legs':[first,second]})
    for leg in ('approaching','carrying','returning'):
        poses=route[leg]['poses']
        if not poses:
            fail_geometry('Empty declared route',{'robot_id':robot_id,'job_id':job_id,'leg':leg})
        for primitive in route_primitives(poses):
            a,b=primitive['a'],primitive['b']
            invalid_turn=a[2]!=b[2] and (not same_pose((a[0],a[1],b[2]),b) or (b[2]-a[2])%4 not in (1,3))
            sweep=nav._sweep(tuple(a),tuple(b))
            hits=obstacle_hits(nav,sweep)
            if invalid_turn or hits or nav._edge(tuple(a),tuple(b),frozenset()) is None:
                fail_geometry('Declared route primitive violates fixed-floor clearance',
                              {'robot_id':robot_id,'job_id':job_id,'leg':leg,'phase_started':job['phase_started'],
                               'primitive':primitive,'sweep':sweep,'obstacles':hits,'clearance_metres':.15})
            counters['planned_primitive_checks']+=1
    counters['validated_plans'].add(job_id)


def timeline(job, assigned):
    route=job['route']
    start=assigned[str(job['id'])]
    travel=lambda leg:sum(primitive_duration(a,b) for a,b in zip(route[leg]['poses'],route[leg]['poses'][1:]))
    phases=[]
    end=start+travel('approaching')
    phases.append(('approaching',start,end))
    departure=job['proofs'].get('departure')
    if not departure:
        return phases+[('awaiting_departure',end,None)]
    pickup=max(end,departure['effective_time'],departure['received_time'])
    phases.extend([('awaiting_departure',end,pickup),('picking_up',pickup,pickup+route['pickup_duration'])])
    carrying=pickup+route['pickup_duration']
    placing=carrying+travel('carrying')
    arrival=placing+route['placement_duration']
    phases.extend([('carrying',carrying,placing),('placing',placing,arrival)])
    receipt=job['proofs'].get('receipt')
    if not receipt:
        return phases+[('awaiting_receipt',arrival,None)]
    returning=max(arrival,receipt['effective_time'],receipt['received_time'])
    phases.extend([('awaiting_receipt',arrival,returning),('returning',returning,returning+travel('returning')),
                   ('completed',returning+travel('returning'),None)])
    return phases


def validate_report(job, pose, committed, assigned, robot_id):
    route=job['route']
    phases=timeline(job,assigned)
    phase=next((value for value in phases if value[0]==job['state']),None)
    if phase is None or abs(phase[1]-job['phase_started'])>1e-6 or committed+1e-7<phase[1] or (phase[2] is not None and committed>phase[2]+1e-7):
        fail_geometry('Reported phase is inconsistent with immutable plan and causal proofs',
                      {'robot_id':robot_id,'job_id':job['id'],'state':job['state'],'phase_started':job['phase_started'],
                       'committed':committed,'declared_phase':phase,'timeline':phases})
    state=job['state']
    if state in ('approaching','carrying','returning'):
        expected=route_pose(route[state]['poses'],max(0,committed-phase[1]))
    elif state in ('awaiting_departure','picking_up'):
        expected=route['origin_pose']
    elif state in ('placing','awaiting_receipt'):
        expected=route['destination_pose']
    else:
        expected=route['returning']['poses'][-1]
    if not same_pose(pose,expected):
        fail_geometry('Reported pose is not on its causal declared route',
                      {'robot_id':robot_id,'job_id':job['id'],'state':state,'phase_started':job['phase_started'],
                       'committed':committed,'reported':pose,'expected':expected,'declared_phase':phase})


def validate_interval(nav,job,first,last,assigned,robot_id,counters):
    """Sweep the executed plan primitives, never a chord joining observations."""
    checked=[]
    for leg,start,end in timeline(job,assigned):
        if leg not in ('approaching','carrying','returning') or start>=last or end<=first:
            continue
        poses=job['route'][leg]['poses']
        for primitive in route_primitives(poses):
            begin=max(first,start+primitive['start'])
            finish=min(last,start+primitive['end'])
            if finish<=begin:
                continue
            a,b=primitive['a'],primitive['b']
            if primitive['kind']=='translation':
                # Clip within this primitive. Subtracting a phase anchor can
                # round a boundary into the preceding turn's heading.
                duration=primitive['end']-primitive['start']
                def clipped(at):
                    fraction=max(0,min(1,(at-start-primitive['start'])/duration))
                    return (a[0]+(b[0]-a[0])*fraction,
                            a[1]+(b[1]-a[1])*fraction,primitive['a'][2])
                clipped_start,clipped_end=clipped(begin),clipped(finish)
                a,b=clipped_start,clipped_end
            sweep=nav._sweep(tuple(a),tuple(b))
            hits=obstacle_hits(nav,sweep)
            diagnostic={'robot_id':robot_id,'job_id':str(job['id']),'leg':leg,'phase_started':start,
                        'previous_committed':first,'committed':last,'reported_context':counters.get('sampling_context'),'primitive':primitive,'executed_from':a,'executed_to':b,
                        'interval':[begin,finish],'sweep':sweep,'obstacles':hits}
            if hits:
                fail_geometry('Executed route primitive violates fixed obstacle clearance',diagnostic)
            counters['interval_primitive_checks']+=1
            checked.append(diagnostic)
    return checked


def collision_sample(nav, catalog, robots, jobs, placements, counters, committed, assignment_rows):
    """Check transforms and the actual continuous declared route primitives."""
    assigned={str(row['job_id']):row['simulation_time'] for row in assignment_rows}
    active = {str(j['id']): j for j in jobs}
    shapes = []
    for robot in robots:
        pose, report = robot['pose'], robot['reported']
        if not nav._safe(tuple(pose)):
            fail_geometry('Reported body violates fixed-floor clearance',{'robot_id':robot['id'],'current':pose,'previous':counters['previous'].get(robot['id']),'report':report,'obstacles':obstacle_hits(nav,nav._rectangle(tuple(pose)))})
        previous = counters['previous'].get(robot['id'])
        counters['sampling_context']={'robot_id':robot['id'],'previous':previous,'current':pose,'committed':committed}
        if previous is not None and committed<previous['time']:
            fail_geometry('Reported simulation time reversed',counters['sampling_context'])
        current_job=active.get(report.get('job_id'))
        checked=[]
        if current_job:
            validate_plan(nav,current_job,robot['id'],counters)
            validate_report(current_job,pose,committed,assigned,robot['id'])
            counters['reported_plan_checks']+=1
        if previous is not None:
            prior_job=active.get(previous['job_id'])
            if prior_job:
                checked.extend(validate_interval(nav,prior_job,previous['time'],committed,assigned,robot['id'],counters))
            if current_job and str(current_job['id'])!=previous['job_id']:
                checked.extend(validate_interval(nav,current_job,previous['time'],committed,assigned,robot['id'],counters))
                if prior_job and prior_job['state']!='completed':
                    fail_geometry('Robot reassigned before previous route completed',{'robot_id':robot['id'],'previous_job':previous['job_id'],'job_id':str(current_job['id'])})
            if not current_job:
                expected=prior_job['route']['returning']['poses'][-1] if prior_job else previous['pose']
                if not same_pose(pose,expected):
                    fail_geometry('Idle robot moved outside a completed plan',{'robot_id':robot['id'],'previous':previous,'current':pose,'committed':committed})
            chord=nav._sweep(previous['pose'],tuple(pose))
            chord_hits=obstacle_hits(nav,chord)
            if chord_hits:
                counters['chord_false_positives']+=1
                if len(counters['corrected_chords'])<8:
                    counters['corrected_chords'].append({'robot_id':robot['id'],'previous':previous,'current':pose,
                                                         'committed':committed,'phase':current_job['state'] if current_job else 'idle',
                                                         'chord':chord,'obstacles':chord_hits,'validated_primitives':checked})
        counters['previous'][robot['id']]={'pose':tuple(pose),'time':committed,'job_id':report.get('job_id')}
        shapes.append((robot['id'], 'body', body_rectangle(pose), None))
        carried = report.get('carried_unit_id')
        position = report.get('load_position')
        if carried and position:
            rect = load_rectangle(position, report.get('load_heading', pose[2]))
            shapes.append((robot['id'], 'load', rect, carried))
            offset = report.get('fork_offset', [0,0])
            if any(abs(value) > 1e-8 for value in offset):
                x,z,_ = pose
                fork = (min(x,x+offset[0])-.3, min(z,z+offset[1])-.3, max(x,x+offset[0])+.3, max(z,z+offset[1])+.3)
                shapes.append((robot['id'], 'fork', fork, carried))
                counters['fork_transform_samples'] += 1
            job = active.get(report.get('job_id'))
            targets = set()
            if job:
                targets = {job['request']['origin'], job['request']['destination']}
            for obstacle in nav.topology['obstacles']:
                own_support = any(endpoint.startswith(obstacle['id'] + '.') for endpoint in targets)
                if not own_support and any(gap(shape[2], obstacle['bounds']) < .15-1e-7 for shape in shapes if shape[0] == robot['id'] and shape[1] != 'body'):
                    raise AssertionError('Carried load violates foreign obstacle clearance')
    for index, a in enumerate(shapes):
        for b in shapes[index+1:]:
            if a[0] != b[0]:
                counters['pair_checks'] += 1
                if gap(a[2], b[2]) < .15 - 1e-7:
                    raise AssertionError('Reported robot/load envelopes violate separation')
        for unit, endpoint in placements.items():
            location = catalog[endpoint]
            if unit == a[3] or location['kind'] in ('shelf', 'truck'):
                continue
            counters['static_checks'] += 1
            if gap(a[2], load_rectangle(location['position'])) < .15 - 1e-7:
                raise AssertionError('Reported robot/load intersects confirmed ground unit')
    counters['samples'] += 1


def make_database(base_url, size):
    name = f'fleet_budget_{size}_{os.getpid()}'
    with psycopg.connect(base_url, autocommit=True) as db:
        db.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(name)))
    parts = urlsplit(base_url)
    return urlunsplit((parts.scheme, parts.netloc, '/' + name, parts.query, parts.fragment))


def run_case(base_url, size, wall_limit):
    started = time.perf_counter()
    store = FleetStore(make_database(base_url, size))
    store.migrate()
    topology = json.loads(Path('/app/contracts/fleet/v1/navigation.json').read_text())
    nav = Navigation(topology)
    sources = {name: {'run_id': identity(f'{size}/{name}/run'), 'epoch': identity(f'{size}/{name}/epoch'), 'offset': 0} for name in DEPARTMENTS}
    run_id, epoch = identity(f'{size}/run'), identity(f'{size}/epoch')
    store.initialize(run_id, epoch, sources, validate_configuration(topology, size))
    lease = psycopg.connect(store.url, autocommit=True)
    if not lease.execute('SELECT pg_try_advisory_lock(750003)').fetchone()[0]:
        raise RuntimeError('Isolated benchmark worker lease is unavailable')
    worker = Worker(store, navigation=nav)
    clients = create_app(store, {name: f'synthetic-budget-{name}' for name in (*DEPARTMENTS, 'observer')}).test_client()
    pools = workload(store.catalog)
    pools['manufacturing_transfer'] = ([x for x in pools['manufacturing_transfer'][0] if '.output' in x], pools['manufacturing_transfer'][1])
    placements, endpoint_claims, pending, requests, consumed_events = {}, {}, [], {}, set()
    drains, source_releases = {}, {}
    offers, admissions, receipts, completed, categories, failures = Counter(), Counter(), Counter(), Counter(), {}, Counter()
    measured_offers, measured_admissions = Counter(), Counter()
    original_plan = nav.plan
    def measured_plan(start, destination, occupied=frozenset()):
        result = original_plan(start, destination, occupied)
        if result is None:
            failures['no_path_with_dynamic_exclusions' if occupied else 'no_path_empty_floor'] += 1
        return result
    nav.plan = measured_plan
    tick_ms, utilization = [], []
    assignment_times, assignment_waits = {}, []
    collision = {'samples': 0, 'pair_checks': 0, 'static_checks': 0, 'previous': {}, 'fork_transform_samples': 0, 'validated_plans':set(), 'planned_primitive_checks':0, 'reported_plan_checks':0, 'interval_primitive_checks':0, 'chord_false_positives':0, 'corrected_chords':[]}
    progress = {'robots': size, 'simulation_time': 0, 'admitted': 0, 'completed': 0}
    stop_progress = threading.Event()
    def announce():
        while not stop_progress.wait(25):
            print('SCHEDULER_PROGRESS ' + json.dumps({**progress, 'wall_seconds': round(time.perf_counter()-started, 2)}), flush=True)
    reporter = threading.Thread(target=announce, daemon=True)
    reporter.start()
    elapsed, status, issue = 0, 'complete', None
    interrupted = False
    jobs, robots, events, reservations, assigned, run = read_state(store)
    def timeout(signum, _frame):
        nonlocal interrupted
        interrupted = signum != signal.SIGALRM or time.perf_counter()-started < wall_limit-.5
        raise TimeoutError('External benchmark interruption' if interrupted else 'Per-case wall limit reached')
    previous_handlers = {number: signal.signal(number, timeout) for number in (signal.SIGALRM, signal.SIGINT, signal.SIGTERM)}
    signal.setitimer(signal.ITIMER_REAL, max(.01, wall_limit-(time.perf_counter()-started)))
    def post(path, owner, body):
        response = clients.post(path, json=body, headers={'Authorization': f'Bearer synthetic-budget-{owner}'})
        if response.status_code not in (200, 201):
            raise RuntimeError(f'Authenticated fixture request rejected: {response.status_code} {response.json}')
        return response.json
    try:
        for current in range(WARMUP + WINDOW + 1):
            for unit, due in list(drains.items()):
                if due <= current:
                    endpoint = placements.pop(unit)
                    endpoint_claims.pop(endpoint, None)
                    del drains[unit]
            for endpoint, unit in list(source_releases.items()):
                if unit not in placements:
                    endpoint_claims.pop(endpoint, None)
                    del source_releases[endpoint]
            if current < WARMUP + WINDOW and current % 5 == 0:
                index = current // 5
                category = CATEGORIES[index % len(CATEGORIES)]
                pending.append({'sequence': index, 'offered_at': current, 'category': category})
                offers[category] += 1
                if current >= WARMUP:
                    measured_offers[category] += 1
            for intent in list(pending):
                origins, destinations = pools[intent['category']]
                chosen = None
                shift = intent['sequence'] // 4
                for index in range(len(origins)):
                    origin = origins[(shift + index) % len(origins)]
                    if origin in endpoint_claims:
                        continue
                    location = store.catalog[origin]
                    x, _, z = location['position']
                    footprint = nav._cells((x-.55, z-.58, x+.55, z+.58))
                    if not footprint.isdisjoint(reservations):
                        continue
                    for j in range(len(destinations)):
                        destination = destinations[(shift * 7 + j) % len(destinations)]
                        if destination not in endpoint_claims and destination != origin:
                            chosen = origin, destination
                            break
                    if chosen:
                        break
                if not chosen:
                    continue
                origin, destination = chosen
                owner = store.catalog[origin]['owner']
                unit = identity(f'{size}/unit/{intent["sequence"]}')
                handoff = identity(f'{size}/handoff/{intent["sequence"]}')
                job = str(uuid5(__import__('uuid').UUID(unit), f'fleet:{handoff}:1'))
                body = {'version': 1, 'id': job, 'run_id': run_id, 'epoch': epoch, 'producer': owner,
                        'source_run_id': sources[owner]['run_id'], 'source_epoch': sources[owner]['epoch'],
                        'unit_id': unit, 'origin': origin, 'destination': destination, 'custody_generation': 1, 'effective_time': current}
                post('/v1/jobs', owner, body)
                requests[job] = body
                categories[job] = intent['category']
                placements[unit] = origin
                endpoint_claims[origin] = unit
                endpoint_claims[destination] = unit
                admissions[intent['category']] += 1
                if current >= WARMUP:
                    measured_admissions[intent['category']] += 1
                pending.remove(intent)
            observations = {name: {**scope, 'committed': current, 'granted': current, 'state': 'running', 'cursor': str(current),
                                   'received_at': time.time(), 'placed_units': [{'unit_id': unit, 'position': endpoint} for unit, endpoint in placements.items() if store.catalog[endpoint]['owner'] == name]} for name, scope in sources.items()}
            tick_start = time.perf_counter()
            worker.tick(observations)
            tick_ms.append((time.perf_counter()-tick_start)*1000)
            elapsed = current
            jobs, robots, events, reservations, assigned, run = read_state(store)
            collision_sample(nav, store.catalog, robots, jobs, placements, collision, current, assigned)
            if current >= WARMUP:
                utilization.append(sum(job['robot_id'] is not None and job['state'] not in ('completed', 'cancelled') for job in jobs)/size)
            for event in assigned:
                job = str(event['job_id'])
                if job not in assignment_times:
                    assignment_times[job] = event['simulation_time']
                    release = requests[job]['effective_time']
                    if WARMUP <= event['simulation_time'] <= current:
                        assignment_waits.append(event['simulation_time']-release)
            for event in events:
                event_id, job = str(event['id']), str(event['job_id'])
                if event_id in consumed_events:
                    continue
                consumed_events.add(event_id)
                kind, fact = event['kind'], event['body']
                request = requests[job]
                if kind == 'completed':
                    if WARMUP <= fact['effective_time'] <= WARMUP + WINDOW:
                        completed[categories[job]] += 1
                    continue
                if kind not in ('pickup_ready', 'arrival'):
                    continue
                if fact['effective_time'] > current:
                    raise AssertionError('Worker emitted a future physical fact')
                owner = request['producer'] if kind == 'pickup_ready' else store.catalog[request['destination']]['owner']
                proof_kind = 'departure' if kind == 'pickup_ready' else 'receipt'
                proof = {'job_id': job, 'unit_id': request['unit_id'], 'run_id': run_id, 'epoch': epoch,
                         'source_run_id': sources[owner]['run_id'], 'source_epoch': sources[owner]['epoch'],
                         'custody_generation': request['custody_generation'], 'endpoint': request['origin' if proof_kind == 'departure' else 'destination'],
                         'effective_time': current+1}
                # Synthetic native clients commit at the next eligible boundary;
                # the minimum fleet clock remains current until the next tick.
                post(f'/v1/jobs/{job}/proofs/{proof_kind}', owner, proof)
                unit = request['unit_id']
                if proof_kind == 'departure':
                    placements.pop(unit)
                    source_releases[request['origin']] = unit
                else:
                    placements[unit] = request['destination']
                    drains[unit] = current+2
                    if WARMUP <= proof['effective_time'] <= WARMUP+WINDOW:
                        receipts[categories[job]] += 1
            progress.update(simulation_time=current, admitted=sum(admissions.values()), completed=sum(completed.values()))
    except TimeoutError as exc:
        status, issue = 'interrupted' if interrupted else 'wall_limit', str(exc)
    except Exception as exc:
        status, issue = 'failed', f'{type(exc).__name__}: {exc}'
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        for number, handler in previous_handlers.items():
            signal.signal(number, handler)
        stop_progress.set()
        reporter.join(timeout=1)
        lease.close()
    jobs, robots, events, reservations, assigned, run = read_state(store)
    measured = max(0, min(WINDOW, elapsed-WARMUP))
    waiting = Counter(job['waiting_reason'] or job['state'] for job in jobs if job['state'] != 'completed')
    queued = [job for job in jobs if job['state'] == 'queued']
    completed_count = sum(completed.values())
    blocker_groups = Counter(tuple(job['blockers']) for job in queued)
    report = {'robots': size, 'status': status, 'issue': issue, 'wall_seconds': time.perf_counter()-started,
              'warmup_seconds_requested': WARMUP, 'measurement_seconds_requested': WINDOW, 'simulation_seconds_reached': elapsed, 'measurement_seconds_actual': measured,
              'offered_per_minute': 12, 'offered_including_warmup': dict(offers), 'admitted_including_warmup': dict(admissions),
              'offered_measured_window': dict(measured_offers), 'admitted_measured_window': dict(measured_admissions), 'external_endpoint_wait_backlog': len(pending),
              'jobs_unfinished': sum(job['state'] != 'completed' for job in jobs), 'queued': len(queued),
              'states': dict(Counter(job['state'] for job in jobs)), 'free_robots': size-sum(job['robot_id'] is not None and job['state'] not in ('completed','cancelled','quarantined') for job in jobs),
              'blocker_groups': [{'blockers':list(group),'queued_jobs':count} for group,count in blocker_groups.items()],
              'completed_roundtrips': dict(completed), 'received_loaded_legs': dict(receipts),
              'completions_per_minute': completed_count*60/measured if measured else None,
              'loaded_receipts_per_minute': sum(receipts.values())*60/measured if measured else None,
              'target_12_per_minute_achieved': measured == WINDOW and completed_count >= 120,
              'queue_wait_assigned_p95_seconds': percentile(assignment_waits, .95), 'queue_wait_assigned_max_seconds': max(assignment_waits, default=None),
              'queue_wait_assigned_samples': len(assignment_waits), 'oldest_unassigned_age_seconds': max((elapsed-job['release_time'] for job in queued), default=0),
              'mean_robot_utilization': sum(utilization)/len(utilization) if utilization else None,
              'waiting_reasons': dict(waiting), 'route_failures': dict(failures),
              'worker_tick_ms': {'count': len(tick_ms), 'p95': percentile(tick_ms,.95), 'p99': percentile(tick_ms,.99), 'max': max(tick_ms,default=None)},
              'collision_checks': {k:v for k,v in collision.items() if k not in ('previous','validated_plans','sampling_context')},
              'categories_represented': sorted(offers), 'endpoint_pools': {k:{'origins':len(v[0]),'destinations':len(v[1])} for k,v in pools.items()},
              'final_clock': run['committed'], 'final_state': run['state'], 'final_reason': run['reason']}
    print('SCHEDULER_CASE ' + json.dumps(report, sort_keys=True), flush=True)
    return report


def verify_sampler():
    """Short real-floor geometry regression; no throughput or native claim."""
    from fleet.worker import pose_at
    topology=json.loads(Path('/app/contracts/fleet/v1/navigation.json').read_text())
    catalog={row['id']:row for row in json.loads(Path('/app/contracts/handling/v1/facility.json').read_text())['locations']}
    nav=Navigation(topology)
    worker=object.__new__(Worker)
    worker.navigation,worker.catalog=nav,catalog
    robot={**topology['parking'][0],'parking':topology['parking'][0]['pose']}
    job={'id':identity('sampler-regression'),'request':{'origin':'manufacturing.cell01.output01','destination':'storage.finished.r01.b01.l01'},'phase_started':0,'proofs':{}}
    route=worker.plan(robot,job,set())
    if route is None:
        raise AssertionError('Actual fixed-floor sampler regression route unavailable')
    job['route']=route
    assigned={str(job['id']):0}
    first_end=timeline(job,assigned)[0][2]
    job['proofs']['departure']={'effective_time':math.ceil(first_end)+1,'received_time':math.ceil(first_end)}
    arrival=next(row[1] for row in timeline(job,assigned) if row[0]=='awaiting_receipt')
    job['proofs']['receipt']={'effective_time':math.ceil(arrival)+1,'received_time':math.ceil(arrival)}
    phases=timeline(job,assigned)
    counters={'validated_plans':set(),'planned_primitive_checks':0,'interval_primitive_checks':0}
    boundary_job={'id':identity('sampler-float-boundary'),'proofs':{},
                  'route':{'approaching':{'poses':[[20.25,-17.55,2],[20.25,-13,2],
                                                  [20.25,-13,1],[20.5,-13,1]]}}}
    boundary_checks=validate_interval(nav,boundary_job,121,122,
                                     {boundary_job['id']:116.09},robot['id'],counters)
    assert all(check['executed_from'][2]==check['primitive']['a'][2]
               for check in boundary_checks if check['primitive']['kind']=='translation')
    validate_plan(nav,job,robot['id'],counters)
    previous=None
    corrected=[]
    for current in range(math.ceil(phases[-1][1])+1):
        state,start,end=next(row for row in phases if row[2] is None or current<row[2])
        job.update(state=state,phase_started=start)
        if state in ('approaching','carrying','returning'):
            pose=pose_at(route[state],current-start)
        else:
            pose=route['origin_pose'] if state in ('awaiting_departure','picking_up') else route['returning']['poses'][-1] if state=='completed' else route['destination_pose']
        validate_report(job,pose,current,assigned,robot['id'])
        if previous:
            primitives=validate_interval(nav,job,current-1,current,assigned,robot['id'],counters)
            hits=obstacle_hits(nav,nav._sweep(tuple(previous),tuple(pose)))
            if hits:
                corrected.append({'robot_id':robot['id'],'previous':previous,'current':pose,'committed':current,'phase':state,'obstacles':hits,'actual_primitives':primitives})
        previous=pose
    bad_pose=[robot['pose'][0]+10,robot['pose'][1],robot['pose'][2]]
    try:
        validate_report(job,bad_pose,current,assigned,robot['id'])
    except AssertionError:
        pass
    else:
        raise AssertionError('Sampler accepted a reported teleport')
    # Corrupt one primitive into a real rack and require precise core-style fault.
    a,b=[-28,-18,0],[-28,-17.75,0]
    broken={**job,'id':identity('sampler-invalid-route'),'route':{**route,'approaching':{'poses':[a,b]},'carrying':{'poses':[b]},'returning':{'poses':[b,a]}}}
    try:
        validate_plan(nav,broken,robot['id'],counters)
    except AssertionError as error:
        if 'Declared route primitive violates fixed-floor clearance' not in str(error):
            raise
    else:
        raise AssertionError('Sampler accepted an actual primitive through a rack')
    result={**{key:value for key,value in counters.items() if key!='validated_plans'},'corrected_chord_count':len(corrected),'corrected_chord_examples':corrected[:2],
            'reported_teleport_rejected':True,'actual_blocked_primitive_rejected':True}
    print('SAMPLER_VERIFICATION '+json.dumps(result,sort_keys=True),flush=True)
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--verify-sampler', action='store_true')
    parser.add_argument('--output')
    parser.add_argument('--size', type=int, choices=(4,8,16))
    parser.add_argument('--wall-limit', type=float, default=300)
    args = parser.parse_args()
    if args.verify_sampler:
        verify_sampler()
        return
    if args.output is None or args.size is None:
        parser.error('--output and --size are required for a scheduler case')
    if os.getenv('FLEET_BENCHMARK_ISOLATED') != '1' or not 0 < args.wall_limit <= 300:
        raise SystemExit('Explicit isolated benchmark environment and wall limit <=300s required')
    result = {'kind': 'synthetic_scheduler_workload_not_native_business_acceptance',
              'environment': {'python': platform.python_version(), 'platform': platform.platform(), 'cell_size_metres': .25, 'minimum_clearance_metres': .15},
              'method': {'clock_quantum_seconds':1, 'offered_interval_seconds':5, 'proof_boundary':'next_native_second',
                         'source_replenishment':'synthetic initial stock, never into an active route reservation',
                         'destination_drain':'synthetic external client drains one second after eligible receipt',
                         'queue_wait':'durable assignment audit time minus admitted native release; unassigned waits right-censored',
                         'collision_sampling':'every committed second; exact primitive intervals on immutable routes at1m/s and0.5s quarter turns; full planned primitive clearance checked once; body/fork/load and static stock samples' ,
                         'limitations':['Synthetic clients do not exercise native departmental business transactions or HELICS.',
                                        'Own source/destination support contact is exempted from load/obstacle checks; fixed fork-opening geometry is audited separately.',
                                        'Timeout cases report actual elapsed simulation time; the requested 600-second measurement is never fabricated.']},
              'cases': []}
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    for size in (args.size,):
        result['cases'].append(run_case(os.environ['TEST_DATABASE_URL'], size, args.wall_limit))
        output.write_text(json.dumps(result, indent=2, sort_keys=True)+'\n')
    print('SCHEDULER_RESULT ' + json.dumps(result, sort_keys=True), flush=True)
    # Throughput misses are measurements. Physical/infrastructure faults fail.
    raise SystemExit(130 if any(case['status']=='interrupted' for case in result['cases']) else 1 if any(case['status']=='failed' for case in result['cases']) else 0)


if __name__ == '__main__':
    main()

"""One fenced writer advances physical poses and owns all fleet reservations."""
import json
import math
import os
from pathlib import Path
import signal
import threading
import time
from uuid import uuid5, NAMESPACE_URL

import httpx
from psycopg.types.json import Jsonb

from .clock import authorized_time
from .navigation import Navigation
from .store import FleetStore, Conflict
from .sources import poll_sources
from .handling_pose import handling_pose, handling_duration


def route_data(route):
    return {'poses': route.poses, 'distance': route.distance}


def duration(route):
    return sum(math.hypot(a[0] - b[0], a[1] - b[1]) if a[2] == b[2] else .5
               for a, b in zip(route['poses'], route['poses'][1:]))


def pose_at(route, elapsed):
    points = route['poses']
    for a, b in zip(points, points[1:]):
        length = math.hypot(a[0] - b[0], a[1] - b[1]) if a[2] == b[2] else .5
        if elapsed < length:
            if a[2] != b[2]:
                # Discrete reported turn heading; reservation covers full swept body.
                return list(a)
            fraction = elapsed / length if length else 1
            return [a[0] + (b[0] - a[0]) * fraction, a[1] + (b[1] - a[1]) * fraction, a[2]]
        elapsed -= length
    return list(points[-1])


class Worker:
    def __init__(self, store, navigation=None, catalog=None):
        self.store = store
        root = Path(__file__).resolve().parents[1]
        self.navigation = navigation or Navigation(json.loads((root / 'contracts/fleet/v1/navigation.json').read_text()))
        self.catalog = catalog or store.catalog
        self.failed_assignments = {}
        self.protected_candidates = {}
        self.previous_blocked = frozenset()
        self.previous_idle = set()
        self.previous_static = frozenset()
        self.generation = store.claim_worker()
        with store.transaction() as db:
            run = store.run(db, self.generation)
            fault = 'Layout reconciliation required' if run['layout_digest'] != store.layout_digest else None
            if run['state'] != 'quarantined' and not fault:
                robots = db.execute('SELECT * FROM fleet_robots WHERE run_id=%s', (run['id'],)).fetchall()
                footprints = [self.navigation.occupancy(tuple(robot['pose'])) for robot in robots]
                if any(not self.navigation._safe(tuple(robot['pose'])) for robot in robots) or any(a & b for index,a in enumerate(footprints) for b in footprints[index+1:]):
                    fault = 'Robot pose clearance reconciliation required'
                for job in db.execute("SELECT * FROM fleet_jobs WHERE run_id=%s AND state NOT IN ('queued','completed','cancelled','quarantined')", (run['id'],)).fetchall():
                    actual = {r['resource'] for r in db.execute('SELECT resource FROM fleet_reservations WHERE job_id=%s', (job['id'],)).fetchall()}
                    if not job['route'] or not actual or actual != set(job['route'].get('resources', [])):
                        fault = 'Reservation reconciliation required'
            if fault:
                db.execute("UPDATE fleet_runs SET state='quarantined',reason=%s,revision=revision+1 WHERE id=%s", (fault,run['id']))
                db.execute("UPDATE fleet_jobs SET state='quarantined',waiting_reason=%s WHERE run_id=%s AND state NOT IN ('completed','cancelled')", (fault,run['id']))
                store.audit(db,run,None,'worker','recovery_fault',{'reason':fault})
            elif run['state'] != 'quarantined':
                db.execute("UPDATE fleet_runs SET state='held',reason='Validating worker recovery',revision=revision+1 WHERE id=%s", (run['id'],))

    def service_pose(self, endpoint):
        configured = self.navigation.topology.get('service_poses', {}).get(endpoint['id'])
        if configured:
            return tuple(configured)
        x, _, z = endpoint['position']
        ax, _, az = endpoint['access']
        if abs(ax - x) >= abs(az - z):
            return (x + (1.5 if ax >= x else -1.5), z, 0)
        return (x, z + (1.5 if az >= z else -1.5), 1)

    def plan(self, robot, job, occupied):
        origin, destination = (self.catalog[job['request'][key]] for key in ('origin', 'destination'))
        a, b = self.service_pose(origin), self.service_pose(destination)
        service = self.navigation.service_resources(origin, a) | self.navigation.service_resources(destination, b)
        if not service.isdisjoint(occupied):
            return None
        legs = []
        for index, (start, end) in enumerate(((tuple(robot['pose']), a), (a, b), (b, tuple(robot['parking'])))):
            excluded = set(occupied)
            # Empty travel must not pass through its own source load or the
            # freshly placed destination load. Those exist at different phases.
            location = origin if index == 0 else destination if index == 2 else None
            if location:
                x,_,z = location['position']
                excluded.update(self.navigation._cells((x-.55,z-.58,x+.55,z+.58)))
            leg = self.navigation.plan(start, end, excluded)
            if leg is None:
                return None
            legs.append(leg)
        resources = set(service)
        for leg in legs:
            resources.update(leg.resources)
        return {'approaching': route_data(legs[0]), 'carrying': route_data(legs[1]), 'returning': route_data(legs[2]),
                'resources': sorted(resources), 'origin_pose': a, 'destination_pose': b,
                'pickup_duration': handling_duration('picking_up',a,origin['position'],destination['position']),
                'placement_duration': handling_duration('placing',b,origin['position'],destination['position']),
                'origin_position': origin['position'], 'destination_position': destination['position'],
                'version': 1}

    def emit(self, db, run, job, kind, effective):
        body = {**job['request'], 'job_id': str(job['id']), 'robot_id': job['robot_id'],
                'effective_time': effective, 'route_version': 1, 'kind': kind}
        event_id = uuid5(NAMESPACE_URL, f"fleet/{job['id']}/{kind}")
        db.execute('INSERT INTO fleet_outbox(id,job_id,kind,body) VALUES(%s,%s,%s,%s) ON CONFLICT(job_id,kind) DO NOTHING',
                   (event_id, job['id'], kind, Jsonb(body)))

    def advance(self, db, run, job):
        state, started, carried = job['state'], job['phase_started'], job['carried']
        route, now = job['route'], run['committed']
        if state in {'completed', 'quarantined', 'queued'}:
            return
        robot = db.execute('SELECT * FROM fleet_robots WHERE run_id=%s AND id=%s', (run['id'], job['robot_id'])).fetchone()
        pose = robot['pose']
        wait, progress = None, job['progress']
        for _ in range(10):
            if state in {'approaching', 'carrying', 'returning'}:
                leg = route[state]
                length = duration(leg)
                pose = pose_at(leg, max(0, now - started))
                progress = min(1, max(0, now - started) / length) if length else 1
                if now < started + length:
                    break
                started += length
                if state == 'approaching':
                    state = 'awaiting_departure'
                    self.emit(db, run, job, 'pickup_ready', started)
                elif state == 'carrying':
                    state = 'placing'
                else:
                    state = 'completed'
                    db.execute('DELETE FROM fleet_reservations WHERE job_id=%s', (job['id'],))
                    self.emit(db, run, job, 'completed', started)
                    break
            elif state in {'awaiting_departure', 'awaiting_receipt'}:
                kind = 'departure' if state == 'awaiting_departure' else 'receipt'
                proof = job['proofs'].get(kind)
                if not proof or now < max(proof['effective_time'], proof['received_time']):
                    wait = kind
                    break
                started = max(started, proof['effective_time'], proof['received_time'])
                if state == 'awaiting_departure':
                    state, carried = 'picking_up', True
                else:
                    state, carried = 'returning', False
            elif state in {'picking_up', 'placing'}:
                length = route['pickup_duration' if state == 'picking_up' else 'placement_duration']
                progress = min(1, max(0, now - started) / length)
                if now < started + length:
                    break
                started += length
                if state == 'picking_up':
                    state, carried = 'carrying', True
                else:
                    state = 'awaiting_receipt'
                    self.emit(db, run, job, 'arrival', started)
            else:
                raise Conflict('Unrecognized physical phase')
        if state != job['state']:
            self.store.audit(db, run, job['id'], 'worker', 'phase', {'from': job['state'], 'to': state})
        physical=handling_pose(state,progress,pose,route['origin_position'],route['destination_position']) if carried else {'fork_height':.15,'fork_offset':[0,0],'load_position':None}
        reported = {'job_id': str(job['id']) if state != 'completed' else None,
                    'carried_unit_id': str(job['unit_id']) if carried else None,
                    **physical,'load_heading':0 if state in {'picking_up','placing','awaiting_receipt'} else pose[2]}
        db.execute('UPDATE fleet_robots SET pose=%s,reported=%s WHERE run_id=%s AND id=%s',
                   (Jsonb(pose), Jsonb(reported), run['id'], job['robot_id']))
        db.execute('UPDATE fleet_jobs SET state=%s,phase_started=%s,carried=%s,progress=%s,waiting_reason=%s WHERE id=%s',
                   (state, started, carried, progress, wait, job['id']))

    def tick(self, observations, now=None):
        with self.store.transaction() as db:
            run = self.store.run(db, self.generation)
            db.execute('UPDATE fleet_runs SET worker_seen_at=clock_timestamp() WHERE id=%s', (run['id'],))
            if run['state'] == 'quarantined':
                return
            for name,observation in observations.items():
                if any(placed['position'] not in self.catalog for placed in observation.get('placed_units', [])):
                    db.execute("UPDATE fleet_runs SET state='held',reason=%s,revision=revision+1 WHERE id=%s",
                               (name+': unmapped confirmed placement',run['id']))
                    return
            committed, reason = authorized_time(run, observations, time.time() if now is None else now)
            if reason:
                db.execute("UPDATE fleet_runs SET state='held',reason=%s,revision=revision+1 WHERE id=%s", (reason, run['id']))
                return
            resuming = run['state'] == 'held'
            gap = committed-run['committed']
            if resuming:
                # Simulation clocks may have advanced while motion was held.
                # Preserve physical progress rather than consuming that gap.
                db.execute("UPDATE fleet_jobs SET phase_started=CASE WHEN state IN ('awaiting_departure','awaiting_receipt') THEN %s ELSE phase_started+%s END WHERE run_id=%s AND state NOT IN ('queued','completed','quarantined')", (committed, gap, run['id']))
            run['committed'] = committed
            db.execute("UPDATE fleet_runs SET committed=%s,state='running',reason=NULL,observations=%s,revision=revision+1 WHERE id=%s",
                       (committed, Jsonb(observations), run['id']))
            if not resuming:
                for job in db.execute("SELECT * FROM fleet_jobs WHERE run_id=%s AND state NOT IN ('queued','completed','quarantined') ORDER BY ordinal", (run['id'],)).fetchall():
                    self.advance(db, run, job)
            jobs = db.execute("SELECT * FROM fleet_jobs WHERE run_id=%s AND state='queued' ORDER BY ordinal", (run['id'],)).fetchall()
            all_robots = db.execute('SELECT * FROM fleet_robots WHERE run_id=%s ORDER BY id', (run['id'],)).fetchall()
            busy = {row['robot_id'] for row in db.execute("SELECT robot_id FROM fleet_jobs WHERE run_id=%s AND robot_id IS NOT NULL AND state NOT IN ('completed','cancelled')", (run['id'],)).fetchall()}
            robots = [robot for robot in all_robots if robot['id'] not in busy]
            reservations = db.execute('SELECT resource,job_id FROM fleet_reservations').fetchall()
            locks = {row['resource'] for row in reservations}
            parking = {robot['id']:self.navigation.occupancy(tuple(robot['parking'])) for robot in all_robots}
            static = {}
            for observation in observations.values():
                for placed in observation.get('placed_units', []):
                    endpoint = self.catalog[placed['position']]
                    if endpoint['kind'] not in {'shelf','truck'}:
                        x,_,z=endpoint['position']
                        static[placed['unit_id']] = self.navigation._cells((x-.55,z-.58,x+.55,z+.58))
            blocked = frozenset(locks.union(*parking.values(),*static.values()))
            static_space=frozenset().union(*static.values())
            added_static=static_space-self.previous_static
            # An aged job must not protect a now-impossible path and prevent
            # the new load's own transport from clearing that dependency.
            for identity,candidate in list(self.protected_candidates.items()):
                if candidate and not added_static.isdisjoint(candidate['resources']):
                    del self.protected_candidates[identity]
            self.previous_static=static_space
            idle = {robot['id'] for robot in robots}
            # Adding physical exclusions cannot make a failed route feasible.
            # Retry only when space is freed or another robot becomes available.
            if self.previous_blocked-blocked or idle-self.previous_idle:
                self.failed_assignments.clear()
                self.protected_candidates.clear()
            self.previous_blocked,self.previous_idle=blocked,idle
            queued = {job['id'] for job in jobs}
            self.failed_assignments={key:value for key,value in self.failed_assignments.items() if key in queued}
            self.protected_candidates={key:value for key,value in self.protected_candidates.items() if key in queued}
            protected = frozenset()
            deadline = time.perf_counter()+.75
            blocker_ids = {str(row['job_id']) for row in reservations}
            for job in jobs:
                if job['release_time'] > committed:
                    db.execute("UPDATE fleet_jobs SET waiting_reason='release_time' WHERE id=%s", (job['id'],))
                    continue
                assigned = False
                pending_budget = False
                failed = self.failed_assignments.setdefault(job['id'],set())
                obstacles=set().union(*(cells for unit,cells in static.items() if unit!=str(job['unit_id'])))
                candidate = self.protected_candidates.get(job['id'])
                if candidate is None and robots and committed-job['release_time']>=30 and time.perf_counter()<deadline:
                    robot=robots[0]
                    future=obstacles.union(*(cells for identity,cells in parking.items() if identity!=robot['id']))
                    candidate=self.plan(robot,job,future) or False
                    self.protected_candidates[job['id']]=candidate
                for robot in robots:
                    cache_key=(robot['id'],protected)
                    if cache_key in failed:
                        continue
                    if time.perf_counter()>=deadline:
                        pending_budget=True
                        break
                    occupied = locks.union(protected,obstacles)
                    for other in all_robots:
                        if other['id']==robot['id']:
                            continue
                        occupied.update(self.navigation.occupancy(tuple(other['pose'])))
                        occupied.update(parking[other['id']])
                    db.execute('UPDATE fleet_jobs SET planning_attempts=planning_attempts+1 WHERE id=%s',(job['id'],))
                    route = self.plan(robot, job, occupied)
                    if route:
                        self.store.assign_within(db, run, job['id'], robot['id'], route)
                        locks.update(route['resources'])
                        blocker_ids.add(str(job['id']))
                        robots=[available for available in robots if available['id']!=robot['id']]
                        assigned = True
                        break
                    failed.add(cache_key)
                if not assigned:
                    if candidate:
                        protected=protected.union(candidate['resources'])
                    db.execute('UPDATE fleet_jobs SET waiting_reason=%s,blockers=%s WHERE id=%s',
                               ('planning' if pending_budget else 'traffic' if robots else 'fleet_capacity', Jsonb(sorted(blocker_ids)), job['id']))


def main():
    store = FleetStore(os.environ['DATABASE_URL'])
    store.migrate()
    # Keep a session lease for the process lifetime. Generation fencing protects
    # transactions even if this session is lost between HTTP polling and commit.
    lease = __import__('psycopg').connect(store.url, autocommit=True)
    if not lease.execute('SELECT pg_try_advisory_lock(750003)').fetchone()[0]:
        raise Conflict('Another fleet worker owns the process lease')
    worker = Worker(store)
    sources = json.loads(os.environ['FLEET_SOURCES'])
    stop = threading.Event()
    signal.signal(signal.SIGTERM, lambda *_: stop.set())
    signal.signal(signal.SIGINT, lambda *_: stop.set())
    with httpx.Client(timeout=2, follow_redirects=False, trust_env=False) as client:
        while not stop.is_set():
            lease.execute('SELECT 1')
            with store.transaction() as db:
                run = db.execute('SELECT id,epoch,sources FROM fleet_runs WHERE current').fetchone()
            expected = {**run,'id':str(run['id']),'epoch':str(run['epoch'])}
            observations = poll_sources(client,sources,expected)
            worker.tick(observations)
            stop.wait(.1)


if __name__ == '__main__':
    main()

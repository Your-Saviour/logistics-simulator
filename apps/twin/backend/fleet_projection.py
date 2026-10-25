"""Optional reported fleet read model. Never schedules or advances robots."""
from copy import deepcopy
from hashlib import sha256
import math
from uuid import UUID

from psycopg.types.json import Jsonb


def finite(value):
    return type(value) in (int, float) and math.isfinite(value)


def validate_fleet(value):
    if not isinstance(value, dict) or type(value.get('version')) is not int or value['version'] != 1 or value.get('mode') != 'operational':
        raise ValueError('Reported fleet version 1 required')
    run = value.get('run', {})
    try:
        UUID(run['id']); UUID(run['epoch'])
    except (KeyError, ValueError, TypeError, AttributeError) as exc:
        raise ValueError('Fleet run/epoch required') from exc
    if type(run.get('revision')) is not int or run['revision'] < 0 or not finite(run.get('committed')) or run['committed'] < 0:
        raise ValueError('Valid fleet revision/committed time required')
    if run.get('state') not in {'held', 'running', 'quarantined'} or type(run.get('fresh')) is not bool or not isinstance(run.get('sources'), dict):
        raise ValueError('Fleet execution and freshness state required')
    for name, source in run['sources'].items():
        if name not in {'storage', 'shipping', 'manufacturing', 'logistics'}:
            raise ValueError('Unknown fleet department')
        try:
            UUID(source['run_id']); UUID(source['epoch'])
        except (KeyError, ValueError, TypeError, AttributeError) as exc:
            raise ValueError('Fleet source scope required') from exc
    if any(not isinstance(value.get(field), list) for field in ('robots', 'jobs', 'reservations', 'events')):
        raise ValueError('Complete physical fleet snapshot required')
    if any(not isinstance(member, dict) for field in ('robots', 'jobs', 'reservations', 'events') for member in value[field]):
        raise ValueError('Fleet collection members must be objects')
    if len(value['robots']) > 16 or len(value['jobs']) > 10000:
        raise ValueError('Fleet snapshot bound exceeded')
    robots, units, jobs = set(), set(), set()
    for robot in value['robots']:
        if not isinstance(robot.get('id'), str) or not robot['id'] or robot['id'] in robots:
            raise ValueError('Unique stable robot identities required')
        robots.add(robot['id'])
        pose = robot.get('pose')
        if not isinstance(pose, list) or len(pose) != 3 or not all(finite(v) for v in pose) or type(pose[2]) is not int or pose[2] not in range(4):
            raise ValueError('Finite reported robot pose/cardinal heading required')
        if not finite(robot.get('fork_height')) or robot['fork_height'] < 0:
            raise ValueError('Reported fork height required')
        offset = robot.get('fork_offset')
        if not isinstance(offset, list) or len(offset) != 2 or not all(finite(v) for v in offset):
            raise ValueError('Reported fork offset required')
        unit = robot.get('carried_unit_id')
        if unit is not None:
            try: UUID(unit)
            except (ValueError, TypeError, AttributeError) as exc: raise ValueError('Carried unit UUID required') from exc
            if unit in units or not robot.get('job_id'):
                raise ValueError('Carried unit must have one robot and job')
            load = robot.get('load_position')
            if not isinstance(load, list) or len(load) != 3 or not all(finite(v) for v in load) or load[1] < 0:
                raise ValueError('Loaded robots require a finite reported load transform')
            units.add(unit)
    assigned = set()
    for job in value['jobs']:
        try: UUID(job['id']); UUID(job['unit_id'])
        except (ValueError, TypeError, KeyError, AttributeError) as exc: raise ValueError('Job/unit UUID required') from exc
        if job['id'] in jobs:
            raise ValueError('Duplicate fleet job')
        jobs.add(job['id'])
        robot = job.get('robot_id')
        if robot is not None and job['state'] not in {'completed', 'cancelled'}:
            if robot not in robots or robot in assigned:
                raise ValueError('One active job per known robot required')
            assigned.add(robot)
    for robot in value['robots']:
        if robot.get('job_id') and robot['job_id'] not in jobs:
            raise ValueError('Robot references unknown job')
        if robot.get('carried_unit_id'):
            job = next(job for job in value['jobs'] if job['id'] == robot['job_id'])
            if job['unit_id'] != robot['carried_unit_id'] or job.get('robot_id') != robot['id'] or not job.get('carried'):
                raise ValueError('Reported load must match its active robot/job assignment')
    def no_credentials(node):
        if isinstance(node, dict):
            if any(str(k).lower() in {'token', 'password', 'authorization', 'credentials'} for k in node):
                raise ValueError('Credentials forbidden in fleet projections')
            for child in node.values(): no_credentials(child)
        elif isinstance(node, list):
            for child in node: no_credentials(child)
    no_credentials(value)
    return value


def physical(value):
    result = deepcopy(value)
    for field in ('fresh', 'worker_seen_at'):
        result['run'].pop(field, None)
    return result


class FleetProjection:
    def __init__(self, store):
        self.store, self.generation = store, None

    def configure(self, config):
        if config:
            from .projection import safe_url
            if not isinstance(config, dict) or set(config) != {'url', 'token'} or not isinstance(config['token'], str) or not config['token']:
                raise ValueError('Private fleet URL and observer token required')
            config = {**config, 'url': safe_url(config['url'])}
        fingerprint = sha256(str(sorted(config.items()) if config else None).encode()).hexdigest()
        with self.store.transaction() as db:
            db.execute('INSERT INTO twin_fleet(id,configured,fingerprint) VALUES(1,%s,%s) ON CONFLICT(id) DO NOTHING', (bool(config), fingerprint))
            old = db.execute('SELECT * FROM twin_fleet WHERE id=1 FOR UPDATE').fetchone()
            if old['fingerprint'] != fingerprint:
                db.execute('UPDATE twin_fleet SET configured=%s,fingerprint=%s,generation=generation+1,connected=false,snapshot=NULL,retired_scopes=\'[]\' WHERE id=1', (bool(config), fingerprint))
            self.generation = db.execute('SELECT generation FROM twin_fleet WHERE id=1').fetchone()['generation']
        return config

    def accept(self, value):
        validate_fleet(value)
        with self.store.transaction() as db:
            old = db.execute('SELECT * FROM twin_fleet WHERE id=1 FOR UPDATE').fetchone()
            if not old or not old['configured'] or (self.generation is not None and old['generation'] != self.generation):
                return
            identity = lambda v: v['run']['id'] + '/' + v['run']['epoch']
            scope = identity(value)
            retired = old['retired_scopes']
            if scope in retired:
                raise ValueError('Retired fleet scope cannot return')
            previous = old['snapshot']
            if previous:
                if identity(previous) != scope:
                    retired = [*retired, identity(previous)]
                elif (value['run']['revision'] < previous['run']['revision'] or
                      (value['run']['revision'] == previous['run']['revision'] and physical(value) != physical(previous))):
                    raise ValueError('Reversed revision or conflicting reported state')
            db.execute('UPDATE twin_fleet SET snapshot=%s,retired_scopes=%s,connected=true,observed_at=clock_timestamp() WHERE id=1', (Jsonb(value), Jsonb(retired)))
            db.execute("INSERT INTO twin_revisions(source) VALUES('fleet')")

    def failure(self):
        with self.store.transaction() as db:
            db.execute('UPDATE twin_fleet SET connected=false WHERE id=1 AND (%s::bigint IS NULL OR generation=%s)', (self.generation, self.generation))

    def view(self):
        with self.store.transaction() as db:
            row = db.execute("SELECT configured,snapshot,NOT(connected AND observed_at>clock_timestamp()-interval '5 seconds') AS stale FROM twin_fleet WHERE id=1 AND configured").fetchone()
        if row and row['snapshot'] and not row['snapshot']['run']['fresh']:
            row['stale'] = True
        return row

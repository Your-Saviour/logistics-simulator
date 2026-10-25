"""Owned fleet ledger. Departmental databases are never connected here."""
from contextlib import contextmanager
from hashlib import sha256
import json
import math
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from .handling_pose import MOTION_MODEL_VERSION


class Conflict(Exception):
    pass


def number(value):
    if isinstance(value, bool) or not isinstance(value, (float, int)) or not math.isfinite(value) or value < 0:
        raise ValueError('Finite nonnegative simulation time required')
    return float(value)


def uuid(value):
    if not isinstance(value, str):
        raise ValueError('UUID string required')
    return str(UUID(value))


class FleetStore:
    def __init__(self, url):
        self.url = url
        root = Path(__file__).resolve().parents[1]
        catalog = json.loads((root / 'contracts/handling/v1/facility.json').read_text())
        self.catalog = {e['id']: e for e in catalog['locations']}
        navigation = json.loads((root / 'contracts/fleet/v1/navigation.json').read_text())
        self.layout_digest = sha256(json.dumps({'catalog':catalog,'navigation':navigation,'motion_model':MOTION_MODEL_VERSION},sort_keys=True,separators=(',',':')).encode()).hexdigest()

    @contextmanager
    def transaction(self):
        with psycopg.connect(self.url, row_factory=dict_row, connect_timeout=3) as db:
            yield db

    def migrate(self):
        with self.transaction() as db:
            db.execute('SELECT pg_advisory_xact_lock(750001)')
            db.execute('CREATE TABLE IF NOT EXISTS fleet_migrations(name text PRIMARY KEY, checksum text NOT NULL)')
            for path in sorted((Path(__file__).resolve().parents[1] / 'migrations').glob('*.sql')):
                body = path.read_text()
                checksum = sha256(body.encode()).hexdigest()
                old = db.execute('SELECT checksum FROM fleet_migrations WHERE name=%s', (path.name,)).fetchone()
                if old:
                    if old['checksum'] != checksum:
                        raise Conflict('Applied fleet migration checksum changed')
                    continue
                db.execute(body)
                db.execute('INSERT INTO fleet_migrations VALUES(%s,%s)', (path.name, checksum))

    def run(self, db, generation=None):
        run = db.execute('SELECT * FROM fleet_runs WHERE current FOR UPDATE').fetchone()
        if not run:
            raise Conflict('Fleet run is not initialized')
        if generation is not None and run['generation'] != generation:
            raise Conflict('Stale worker generation')
        return run

    def audit(self, db, run, job, actor, action, detail):
        db.execute('INSERT INTO fleet_audit(run_id,job_id,actor,action,simulation_time,detail) VALUES(%s,%s,%s,%s,%s,%s)',
                   (run['id'], job, actor, action, run['committed'], Jsonb(detail)))

    def changed(self, db, run):
        db.execute('UPDATE fleet_runs SET revision=revision+1 WHERE id=%s', (run['id'],))

    def initialize(self, run_id, epoch, sources, robots):
        run_id, epoch = uuid(run_id), uuid(epoch)
        if not sources or not isinstance(sources, dict) or not robots:
            raise ValueError('Sources and robots required')
        for name, scope in sources.items():
            if name not in {'storage', 'manufacturing', 'shipping', 'logistics'}:
                raise ValueError('Unknown department')
            uuid(scope['run_id']); uuid(scope['epoch']); number(scope['offset'])
        ids = set()
        for robot in robots:
            if not isinstance(robot['id'], str) or not robot['id'] or robot['id'] in ids:
                raise ValueError('Unique stable robot identity required')
            ids.add(robot['id'])
            pose = robot['pose']
            if len(pose) != 3 or pose[2] not in range(4):
                raise ValueError('Robot pose required')
            for value in pose[:2]:
                if isinstance(value, bool) or not isinstance(value, (float, int)) or not math.isfinite(value):
                    raise ValueError('Finite robot pose required')
        with self.transaction() as db:
            db.execute('SELECT pg_advisory_xact_lock(750002)')
            if db.execute('SELECT 1 FROM fleet_runs WHERE current').fetchone():
                raise Conflict('Run initialization requires explicit reconciliation of existing state')
            db.execute('INSERT INTO fleet_runs(id,epoch,sources,layout_digest) VALUES(%s,%s,%s,%s)', (run_id, epoch, Jsonb(sources), self.layout_digest))
            for robot in robots:
                db.execute('INSERT INTO fleet_robots VALUES(%s,%s,%s,%s)',
                           (run_id, robot['id'], Jsonb(robot['pose']), Jsonb(robot['pose'])))

    def validate(self, body):
        fields = {'version', 'id', 'run_id', 'epoch', 'producer', 'source_run_id', 'source_epoch',
                  'unit_id', 'origin', 'destination', 'custody_generation', 'effective_time'}
        if not isinstance(body, dict) or set(body) != fields or type(body['version']) is not int or body['version'] != 1:
            raise ValueError('Exact version-1 transport request fields required')
        for field in ('id', 'run_id', 'epoch', 'source_run_id', 'source_epoch', 'unit_id'):
            if uuid(body[field]) != body[field]:
                raise ValueError('Canonical UUID required')
        number(body['effective_time'])
        if type(body['custody_generation']) is not int or body['custody_generation'] < 0:
            raise ValueError('Nonnegative integer custody generation required')
        if not all(isinstance(body[field], str) for field in ('origin', 'destination')):
            raise ValueError('Catalog endpoint strings required')
        origin, destination = self.catalog.get(body['origin']), self.catalog.get(body['destination'])
        if not origin or not destination or origin['id'] == destination['id']:
            raise ValueError('Different catalog endpoints required')
        if origin['owner'] != body['producer'] or not set(origin['compatible']) & set(destination['compatible']):
            raise ValueError('Origin ownership or unit category mismatch')

    def admit(self, body):
        self.validate(body)
        try:
            with self.transaction() as db:
                run = self.run(db)
                source = run['sources'].get(body['producer'])
                if (str(run['id']) != body['run_id'] or str(run['epoch']) != body['epoch'] or not source
                        or source['run_id'] != body['source_run_id'] or source['epoch'] != body['source_epoch']):
                    raise Conflict('Transport scope mismatch')
                if self.catalog[body['destination']]['owner'] not in run['sources']:
                    raise Conflict('Destination department is not a participating fleet source')
                old = db.execute('SELECT * FROM fleet_jobs WHERE id=%s', (body['id'],)).fetchone()
                if old:
                    if old['request'] != body:
                        raise Conflict('Transport identity reused with different request')
                    return old
                job = db.execute('INSERT INTO fleet_jobs(id,run_id,epoch,unit_id,producer,request,release_time) VALUES(%s,%s,%s,%s,%s,%s,%s) RETURNING *',
                                 (body['id'], run['id'], run['epoch'], body['unit_id'], body['producer'], Jsonb(body), body['effective_time'] + source['offset'])).fetchone()
                self.audit(db, run, job['id'], body['producer'], 'admit', body)
                self.changed(db, run)
                return job
        except psycopg.errors.UniqueViolation as exc:
            raise Conflict('Unit already has an active transport job') from exc

    def claim_worker(self):
        with self.transaction() as db:
            run = self.run(db)
            return db.execute('UPDATE fleet_runs SET generation=generation+1 WHERE id=%s RETURNING generation', (run['id'],)).fetchone()['generation']

    def assign(self, job_id, robot_id, route, generation):
        try:
            with self.transaction() as db:
                run = self.run(db, generation)
                return self.assign_within(db, run, job_id, robot_id, route)
        except psycopg.errors.UniqueViolation as exc:
            raise Conflict('Robot or route resources already assigned') from exc

    def assign_within(self, db, run, job_id, robot_id, route):
        job = db.execute('SELECT * FROM fleet_jobs WHERE id=%s AND run_id=%s AND epoch=%s FOR UPDATE', (job_id, run['id'], run['epoch'])).fetchone()
        if not job or job['state'] != 'queued':
            raise Conflict('Queued job required')
        if not db.execute('SELECT 1 FROM fleet_robots WHERE run_id=%s AND id=%s', (run['id'], robot_id)).fetchone():
            raise Conflict('Unknown robot')
        for resource in sorted(set(route['resources'])):
            db.execute('INSERT INTO fleet_reservations VALUES(%s,%s)', (resource, job_id))
        db.execute("UPDATE fleet_jobs SET state='approaching',robot_id=%s,route=%s,phase_started=%s,waiting_reason=NULL WHERE id=%s",
                   (robot_id, Jsonb(route), run['committed'], job_id))
        db.execute("UPDATE fleet_robots SET reported=jsonb_build_object('job_id',%s::text,'carried_unit_id',NULL,'fork_height',0.15,'fork_offset',jsonb_build_array(0,0),'load_position',NULL) WHERE run_id=%s AND id=%s",
                   (str(job_id), run['id'], robot_id))
        self.audit(db, run, job_id, 'worker', 'assign', {'robot_id': robot_id})
        self.changed(db, run)

    def replace_epoch(self, epoch):
        epoch = uuid(epoch)
        with self.transaction() as db:
            run = self.run(db)
            db.execute("UPDATE fleet_runs SET epoch=%s,state='quarantined',reason='Epoch reconciliation required',generation=generation+1,revision=revision+1 WHERE id=%s", (epoch, run['id']))
            db.execute("UPDATE fleet_jobs SET state='quarantined',waiting_reason='Epoch reconciliation required' WHERE run_id=%s AND state NOT IN ('completed','cancelled')", (run['id'],))
            self.audit(db, run, None, 'operator', 'replace_epoch', {'epoch': epoch})

    def submit_proof(self, job_id, kind, proof, actor):
        if kind not in {'departure', 'receipt'} or not isinstance(proof, dict):
            raise ValueError('Departure or receipt proof required')
        fields = {'job_id', 'unit_id', 'run_id', 'epoch', 'source_run_id', 'source_epoch',
                  'custody_generation', 'endpoint', 'effective_time'}
        if set(proof) != fields:
            raise ValueError('Exact proof fields required')
        number(proof['effective_time'])
        if type(proof['custody_generation']) is not int or proof['custody_generation'] < 0:
            raise ValueError('Nonnegative integer custody generation required')
        with self.transaction() as db:
            run = self.run(db)
            job = db.execute('SELECT * FROM fleet_jobs WHERE id=%s FOR UPDATE', (job_id,)).fetchone()
            if not job or job['run_id'] != run['id'] or job['epoch'] != run['epoch']:
                raise Conflict('Unknown or retired transport job')
            body = job['request']
            owner = body['producer'] if kind == 'departure' else self.catalog[body['destination']]['owner']
            scope = run['sources'].get(owner)
            if actor != owner or not scope:
                raise Conflict('Proof must come from configured owning department')
            expected = {'job_id': str(job['id']), 'unit_id': str(job['unit_id']), 'run_id': str(run['id']),
                        'epoch': str(run['epoch']), 'source_run_id': scope['run_id'], 'source_epoch': scope['epoch'],
                        'custody_generation': body['custody_generation'], 'endpoint': body['origin' if kind == 'departure' else 'destination']}
            if any(proof.get(key) != value for key, value in expected.items()):
                raise Conflict('Proof identity or scope mismatch')
            old = job['proofs'].get(kind)
            if old:
                if old['body'] != proof:
                    raise Conflict('Conflicting transport proof retry')
                return old['body']
            effective = proof['effective_time'] + scope['offset']
            if effective < job['release_time']:
                raise Conflict('Proof predates transport release')
            if kind == 'receipt':
                arrival = db.execute("SELECT body FROM fleet_outbox WHERE job_id=%s AND kind='arrival'", (job_id,)).fetchone()
                if not arrival or effective < arrival['body']['effective_time']:
                    raise Conflict('Receipt requires committed physical arrival')
            proofs = {**job['proofs'], kind: {'body': proof, 'effective_time': effective, 'received_time': run['committed']}}
            db.execute('UPDATE fleet_jobs SET proofs=%s WHERE id=%s', (Jsonb(proofs), job_id))
            self.audit(db, run, job_id, actor, kind, proof)
            self.changed(db, run)
            return proof

    def snapshot(self):
        with self.transaction() as db:
            # A single repeatable-read snapshot avoids mixing poses and reservations.
            db.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
            run = db.execute('SELECT * FROM fleet_runs WHERE current').fetchone()
            if not run:
                raise Conflict('Fleet run is not initialized')
            run['fresh'] = bool(run['worker_seen_at'] and (datetime.now(timezone.utc) - run['worker_seen_at']).total_seconds() <= 5)
            jobs = db.execute("SELECT * FROM fleet_jobs WHERE run_id=%s AND (state NOT IN ('completed','cancelled') OR id IN (SELECT id FROM fleet_jobs WHERE run_id=%s AND state IN ('completed','cancelled') ORDER BY ordinal DESC LIMIT 256)) ORDER BY ordinal", (run['id'],run['id'])).fetchall()
            for job in jobs:
                if job['state'] in {'completed','cancelled'}:
                    # Full immutable routes remain available on GET job and in
                    # SQL; old path meshes must not grow every live poll forever.
                    job['route']=None
            robots = db.execute('SELECT * FROM fleet_robots WHERE run_id=%s ORDER BY id', (run['id'],)).fetchall()
            for robot in robots:
                robot.update({'job_id': None, 'carried_unit_id': None, 'fork_height': .15,
                              'fork_offset': [0, 0], 'load_position': None, **robot.pop('reported')})
            reservations = db.execute('SELECT * FROM fleet_reservations ORDER BY resource').fetchall()
            outbox = db.execute('SELECT * FROM fleet_outbox WHERE NOT acknowledged ORDER BY id').fetchall()
            return json.loads(json.dumps({'version': 1, 'mode': 'operational', 'run': run, 'jobs': jobs, 'robots': robots,
                                          'reservations': reservations, 'events': outbox}, default=str))

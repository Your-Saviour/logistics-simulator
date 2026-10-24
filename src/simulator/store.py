"""PostgreSQL is the durable completion ledger and the transition authority.

Lock order is always current run, then jobs/outboxes. All replicas serialize
transition boundaries on that run row; no worker trusts its own wall clock.
"""
import json
import math
from pathlib import Path
from uuid import uuid4

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from .contracts import Envelope, SamplePayload


class Conflict(ValueError):
    pass


class Store:
    def __init__(self, url, mode='standalone', run_id='', epoch=''):
        self.url, self.mode, self.initial_run, self.initial_epoch = url, mode, run_id, epoch

    def connect(self):
        return psycopg.connect(self.url, row_factory=dict_row, connect_timeout=5)

    def migrate(self):
        with self.connect() as db:
            db.execute('SELECT pg_advisory_xact_lock(8192101)')
            db.execute(Path('migrations/001_bootstrap.sql').read_text())
            if not db.execute('SELECT 1 FROM runs WHERE current').fetchone():
                if self.mode == 'helics' and not (self.initial_run and self.initial_epoch):
                    raise Conflict('Federation owner must supply run and epoch IDs')
                db.execute('INSERT INTO runs(id,epoch,mode) VALUES (%s,%s,%s)',
                           (self.initial_run or uuid4(), self.initial_epoch or uuid4(), self.mode))
            run = self._run(db)
            if run['mode'] != self.mode:
                raise Conflict('Persisted run mode differs; use a fresh deployment database')
            if self.mode == 'helics' and (str(run['id']) != self.initial_run or str(run['epoch']) != self.initial_epoch):
                raise Conflict('Persisted federation identity differs; archive and use a fresh database')

    @staticmethod
    def _run(db):
        for _ in range(10):
            run = db.execute('SELECT * FROM runs WHERE current FOR UPDATE').fetchone()
            if run is not None:
                return run
            # At READ COMMITTED, a waiter can recheck an archived row after
            # reset without seeing its replacement in that statement snapshot.
            # A new statement sees the newly committed current run.
        raise Conflict('Current run changed repeatedly; retry the command')

    def status(self):
        with self.connect() as db:
            run = self._run(db)
            jobs = db.execute('SELECT * FROM jobs WHERE run_id=%s ORDER BY created_at DESC LIMIT 100', (run['id'],)).fetchall()
            effects = db.execute('SELECT COALESCE(sum(quantity),0) AS n FROM effects WHERE run_id=%s', (run['id'],)).fetchone()['n']
            heartbeats = db.execute("SELECT role, seen_at, detail, seen_at > clock_timestamp()-interval '15 seconds' AS healthy FROM heartbeats").fetchall()
            pending = db.execute('SELECT count(*) AS n FROM boundary_outbox WHERE run_id=%s AND sent_at IS NULL', (run['id'],)).fetchone()['n']
            return {'run': run, 'jobs': jobs, 'effects': effects, 'heartbeats': heartbeats, 'pending_boundary_outputs': pending}

    def schedule(self, key, due_at, payload, quantum=1):
        payload = SamplePayload.model_validate(payload).model_dump()
        if not key or len(key) > 128 or not math.isfinite(due_at):
            raise Conflict('Valid idempotency key and finite due time required')
        with self.connect() as db:
            run = self._run(db)
            old = db.execute('SELECT * FROM jobs WHERE run_id=%s AND idempotency_key=%s', (run['id'], key)).fetchone()
            if old:
                if old['original_due_at'] != due_at or old['payload'] != payload:
                    raise Conflict('Idempotency key already used with a different command')
                return old
            if run['state'] not in ('running', 'held') or due_at < max(run['granted'], run['requested']) + quantum:
                raise Conflict('Schedule at least one quantum beyond granted/requested time in an active run')
            return db.execute('INSERT INTO jobs(id,run_id,epoch,idempotency_key,due_at,original_due_at,payload) VALUES (%s,%s,%s,%s,%s,%s,%s) RETURNING *',
                              (uuid4(), run['id'], run['epoch'], key, due_at, due_at, Jsonb(payload))).fetchone()

    def execute(self, job_id):
        with self.connect() as db:
            run = self._run(db)
            job = db.execute('SELECT * FROM jobs WHERE id=%s FOR UPDATE', (job_id,)).fetchone()
            if not job or job['run_id'] != run['id'] or job['epoch'] != run['epoch']:
                return 'fenced'
            if job['status'] == 'completed':
                return 'duplicate'
            if job['status'] == 'dead':
                return 'dead'
            if run['state'] != 'running' or job['due_at'] > run['granted']:
                return 'waiting'
            alive = db.execute("SELECT 1 FROM heartbeats WHERE role='controller' AND seen_at>clock_timestamp()-interval '15 seconds'").fetchone()
            if not alive:
                return 'waiting'
            if not db.execute('SELECT retry_after <= clock_timestamp() AS ready FROM jobs WHERE id=%s', (job_id,)).fetchone()['ready']:
                return 'waiting'
            db.execute('INSERT INTO inbox(event_id,run_id,epoch) VALUES (%s,%s,%s) ON CONFLICT DO NOTHING', (job_id, run['id'], run['epoch']))
            db.execute('INSERT INTO effects(job_id,run_id,quantity) VALUES (%s,%s,%s)', (job_id, run['id'], job['payload']['quantity']))
            db.execute("UPDATE jobs SET status='completed',error=NULL WHERE id=%s", (job_id,))
            # Incoming boundary samples are recorded once and never echoed to a peer.
            if run['mode'] == 'helics' and not job['idempotency_key'].startswith('boundary:'):
                db.execute('INSERT INTO boundary_outbox(id,run_id,envelope) VALUES (%s,%s,%s)',
                           (uuid4(), run['id'], Jsonb({'job_id': str(job_id), 'quantity': job['payload']['quantity'], 'time': run['granted']})))
            return 'completed'

    def fail_job(self, job_id, error):
        with self.connect() as db:
            run = self._run(db)
            job = db.execute('SELECT * FROM jobs WHERE id=%s FOR UPDATE', (job_id,)).fetchone()
            if not job or job['run_id'] != run['id'] or job['status'] in ('completed', 'dead'):
                return 'dead' if job and job['status'] == 'dead' else 'fenced'
            attempts = job['attempts'] + 1
            db.execute("UPDATE jobs SET attempts=%s,status=%s,error=%s,retry_after=clock_timestamp()+interval '2 seconds' WHERE id=%s",
                       (attempts, 'dead' if attempts >= 3 else 'pending', str(error)[:1000], job_id))
            if attempts >= 3:
                db.execute("UPDATE runs SET state='failed',error='Job retry limit exceeded' WHERE id=%s", (run['id'],))
            return 'dead' if attempts >= 3 else 'retry'

    def dispatchable(self):
        with self.connect() as db:
            run = self._run(db)
            if run['state'] != 'running':
                return []
            jobs = db.execute("SELECT * FROM jobs WHERE run_id=%s AND due_at<=%s AND status IN ('pending','queued') AND retry_after<=clock_timestamp()", (run['id'], run['granted'])).fetchall()
            for job in jobs:
                db.execute('INSERT INTO outbox(id,job_id,run_id) VALUES (%s,%s,%s) ON CONFLICT(job_id) DO NOTHING', (uuid4(), job['id'], run['id']))
            return db.execute("SELECT o.id,o.job_id FROM outbox o JOIN jobs j ON j.id=o.job_id WHERE o.run_id=%s AND j.status IN ('pending','queued') AND j.retry_after<=clock_timestamp() AND o.retry_after<=clock_timestamp()", (run['id'],)).fetchall()

    def published(self, outbox_id):
        # Resend uncompleted jobs after a bounded wall-time interval. A lost ACK
        # cannot lose a job; duplicates are harmless at the transaction boundary.
        with self.connect() as db:
            self._run(db)
            db.execute("UPDATE outbox SET sent_at=clock_timestamp(),retry_after=clock_timestamp()+interval '5 seconds' WHERE id=%s", (outbox_id,))

    def grant(self, granted, expected_epoch=None, blocked_reason=None, quantum=1):
        with self.connect() as db:
            run = self._run(db)
            if expected_epoch is not None and run['epoch'] != expected_epoch:
                raise Conflict('Stale controller epoch')
            if run['state'] in ('failed', 'stalled', 'finalized') or (run['mode'] == 'standalone' and run['state'] == 'held'):
                return False
            if not math.isfinite(granted) or granted < run['granted']:
                raise Conflict('Grant must be finite and monotonic')
            db.execute('UPDATE runs SET granted=%s,requested=GREATEST(requested,%s),anchor=clock_timestamp() WHERE id=%s', (granted, granted, run['id']))
            db.execute('UPDATE runs SET blocked_reason=%s WHERE id=%s', (blocked_reason, run['id']))
            if blocked_reason:
                db.execute("UPDATE jobs SET due_at=%s WHERE run_id=%s AND status IN ('pending','queued') AND due_at<=%s", (granted + quantum, run['id'], granted))
            db.execute("INSERT INTO heartbeats(role) VALUES ('controller') ON CONFLICT(role) DO UPDATE SET seen_at=clock_timestamp()")
            return True

    @staticmethod
    def _outstanding(db, run):
        return db.execute("SELECT EXISTS(SELECT 1 FROM jobs WHERE run_id=%s AND due_at<=%s AND status NOT IN ('completed','fenced')) OR EXISTS(SELECT 1 FROM boundary_outbox WHERE run_id=%s AND sent_at IS NULL) AS busy", (run['id'], run['granted'], run['id'])).fetchone()['busy']

    def prepare_request(self, target, expected_epoch=None):
        with self.connect() as db:
            run = self._run(db)
            if expected_epoch is not None and run['epoch'] != expected_epoch:
                return False
            if run['state'] != 'running' or self._outstanding(db, run):
                return False
            if not math.isfinite(target) or target <= run['granted']:
                raise Conflict('Next request must advance time')
            db.execute('UPDATE runs SET committed=granted,requested=%s WHERE id=%s', (target, run['id']))
            return True

    def control(self, action, speed=1, expected_run_id=None):
        with self.connect() as db:
            run = self._run(db)
            if action == 'reset':
                if expected_run_id is not None and str(run['id']) != str(expected_run_id):
                    raise Conflict('Reset confirmation does not match the current run')
                if run['mode'] == 'helics':
                    raise Conflict('Finalize the federation and allocate a new deployment run/epoch; live reset is forbidden')
                db.execute('UPDATE runs SET current=false WHERE id=%s', (run['id'],))
                db.execute('INSERT INTO runs(id,epoch,mode) VALUES (%s,%s,%s)', (uuid4(), uuid4(), self.mode))
            elif action in ('hold', 'resume'):
                if run['state'] not in ('running', 'held'):
                    raise Conflict('Cannot resume a failed, stalled or finalized run')
                db.execute('UPDATE runs SET state=%s,anchor=clock_timestamp() WHERE id=%s', ('held' if action == 'hold' else 'running', run['id']))
            elif action == 'speed':
                if run['mode'] != 'standalone' or speed not in (1, 5, 20, 60):
                    raise Conflict('Only standalone speeds 1, 5, 20, 60 are supported')
                db.execute('UPDATE runs SET speed=%s,anchor=clock_timestamp() WHERE id=%s', (speed, run['id']))
            elif action == 'finalize':
                if self._outstanding(db, run):
                    raise Conflict('Hold and settle current-time work before finalizing')
                db.execute("UPDATE runs SET state='finalized' WHERE id=%s", (run['id'],))
            else:
                raise Conflict('Unknown control')
        return self.status()

    def heartbeat(self, role, detail=''):
        with self.connect() as db:
            db.execute('INSERT INTO heartbeats(role,detail) VALUES (%s,%s) ON CONFLICT(role) DO UPDATE SET seen_at=clock_timestamp(),detail=EXCLUDED.detail', (role, detail))

    def stall(self, error, expected_epoch=None):
        with self.connect() as db:
            # Exception unwinding releases the session lease. Do not overwrite
            # recovery by a replacement controller that acquired it meanwhile.
            if not db.execute('SELECT pg_try_advisory_xact_lock(8192102) AS held').fetchone()['held']:
                return
            run = self._run(db)
            if expected_epoch is not None and run['epoch'] != expected_epoch:
                return
            db.execute("UPDATE runs SET state='stalled',error=%s WHERE current", (str(error)[:1000],))

    def ingest(self, envelope: Envelope, allowed_source, boundary, destination, quantum=1):
        with self.connect() as db:
            run = self._run(db)
            if (str(run['id']), str(run['epoch'])) != (str(envelope.run_id), str(envelope.epoch)):
                return 'fenced'
            if envelope.source != allowed_source or envelope.boundary != boundary or envelope.destination != destination:
                raise Conflict('Boundary owner/routing mismatch')
            if db.execute('SELECT 1 FROM inbox WHERE event_id=%s', (envelope.event_id,)).fetchone():
                return 'duplicate'
            if envelope.effective_time < run['granted']:
                raise Conflict('Late event cannot change committed history')
            db.execute('INSERT INTO inbox(event_id,run_id,epoch) VALUES (%s,%s,%s)', (envelope.event_id, run['id'], run['epoch']))
            due = max(envelope.effective_time, run['granted'] + quantum) if run['blocked_reason'] else envelope.effective_time
            db.execute('INSERT INTO jobs(id,run_id,epoch,idempotency_key,due_at,original_due_at,payload) VALUES (%s,%s,%s,%s,%s,%s,%s)',
                       (uuid4(), run['id'], run['epoch'], 'boundary:' + str(envelope.event_id), due, envelope.effective_time, Jsonb(envelope.payload.model_dump())))
            return 'accepted'

    def sources(self):
        with self.connect() as db:
            return db.execute("SELECT name,status,connected AND observed_at>clock_timestamp()-interval '15 seconds' AS connected,observed_at,error FROM source_snapshots ORDER BY name").fetchall()

    def project(self, name, status=None, error=None):
        with self.connect() as db:
            db.execute('INSERT INTO source_snapshots(name,status,connected,observed_at,error) VALUES (%s,%s,%s,clock_timestamp(),%s) ON CONFLICT(name) DO UPDATE SET status=COALESCE(EXCLUDED.status,source_snapshots.status),connected=EXCLUDED.connected,observed_at=EXCLUDED.observed_at,error=EXCLUDED.error',
                       (name, Jsonb(status) if status else None, error is None, error))

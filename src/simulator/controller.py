"""One controller per application, guarded by a PostgreSQL session lease."""
from datetime import datetime, timezone
import json
import logging
import os
import signal
import time
from uuid import UUID

import helics as h
from psycopg.types.json import Jsonb

from .clocks import HelicsClock
from .config import Settings
from .contracts import Envelope
from .store import Store, Conflict

log = logging.getLogger(__name__)


def publish_boundaries(store, clock, settings, outputs):
    # Current-time work is completed before publishing. Failure here stalls
    # the federation. A restarted live HELICS participant is never auto-resumed.
    with store.connect() as db:
        run = store._run(db)
        rows = db.execute('SELECT * FROM boundary_outbox WHERE run_id=%s AND sent_at IS NULL ORDER BY id', (run['id'],)).fetchall()
        for row in rows:
            sample = row['envelope']
            for output in outputs:
                envelope = Envelope(event_id=row['id'], federation_id=settings.federation_id, run_id=run['id'], epoch=run['epoch'],
                                    correlation_id=UUID(sample['job_id']), causation_id=UUID(sample['job_id']), aggregate_id=UUID(sample['job_id']),
                                    aggregate_version=1, source=settings.app, destination=output['destination'], boundary=output['boundary'],
                                    effective_time=run['granted'] + settings.quantum, payload={'quantity': sample['quantity']})
                clock.send(envelope.model_dump(mode='json'), output['endpoint'])
            db.execute('UPDATE boundary_outbox SET sent_at=clock_timestamp() WHERE id=%s', (row['id'],))


def ingest_boundaries(store, clock, settings, peers):
    for source_endpoint, raw in clock.receive():
        envelope = Envelope.model_validate(raw)
        peer = peers.get(envelope.boundary)
        if not peer or peer['endpoint'] != source_endpoint or envelope.federation_id != settings.federation_id:
            raise Conflict('Unconfigured HELICS sender or federation')
        store.ingest(envelope, peer['source'], envelope.boundary, settings.app, quantum=settings.quantum)


def settle_outputs(store, clock, settings, outputs):
    if clock.pending:
        return False
    publish_boundaries(store, clock, settings, outputs)
    clock.publish_value(float(store.status()['effects']))
    return True


def grant_local(store, target, epoch):
    try:
        return store.grant(target, expected_epoch=epoch)
    except Conflict:
        if store.status()['run']['epoch'] != epoch:
            return False  # A reset between request and grant is expected.
        raise


def main():
    logging.basicConfig(level=logging.INFO)
    settings = Settings.from_env()
    if settings.app == 'twin':
        raise ValueError('Twin has no business clock')
    store = Store(settings.database_url, settings.mode, settings.run_id, settings.epoch, scenario=settings.scenario)
    store.migrate()
    stop = False

    def stopping(*_):
        nonlocal stop
        stop = True

    signal.signal(signal.SIGTERM, stopping)
    signal.signal(signal.SIGINT, stopping)
    clock = None
    lease_owned = False
    try:
        with store.connect() as lease:
            lease.autocommit = True
            if not lease.execute('SELECT pg_try_advisory_lock(8192102) AS held').fetchone()['held']:
                raise RuntimeError('Another controller owns this simulator')
            lease_owned = True
            run = store.status()['run']
            if run['state'] in ('stalled', 'failed', 'finalized'):
                raise Conflict('Run requires operator recovery with a new federation epoch or standalone reset')
            peers = json.loads(os.getenv('HELICS_PEERS', '{}'))
            outputs = json.loads(os.getenv('HELICS_OUTPUTS', '[]'))
            initialized = settings.mode == 'standalone'
            if settings.mode == 'helics':
                if run['granted'] or run['requested'] or run['committed']:
                    raise Conflict('Live federation restart requires coordinated new run/epoch')
                if set(peers) != {key for key, value in settings.providers.items() if value == 'helics'} or not settings.federation_id or not outputs:
                    raise Conflict('Connected mode requires explicit peer routes, outputs and federation identity')
                clock = HelicsClock(settings.helics_config)
                clock.initialize()
            timeout = float(os.getenv('HELICS_TIMEOUT_SECONDS', '60'))
            while not stop:
                lease.execute('SELECT 1')  # Detect loss of singleton ownership before any grant.
                run = store.status()['run']
                store.heartbeat('controller', json.dumps(clock.values()) if initialized and clock else '')
                if run['state'] in ('failed', 'stalled', 'finalized'):
                    break
                if clock and clock.requested_at and time.monotonic() - clock.requested_at > timeout:
                    raise TimeoutError('HELICS peer/initialization grant timed out; synthetic fallback is forbidden')
                if not initialized:
                    initialized = clock.initialized()
                    time.sleep(0.05)
                    continue
                if clock:
                    grant = clock.poll()
                    if grant is not None:
                        if grant > 1e20:
                            raise Conflict('Federation ended unexpectedly')
                        blocked = None
                        if settings.app == 'manufacturing' and 'power' in peers:
                            power = clock.values().get(peers['power'].get('value_target', 'external-power/available_power_kw'), 0)
                            if not (0 < power < 1e12):
                                blocked = 'External power unavailable; sample work deferred'
                        store.grant(grant, expected_epoch=run['epoch'], blocked_reason=blocked, quantum=settings.quantum)
                        ingest_boundaries(store, clock, settings, peers)
                        run = store.status()['run']
                    settle_outputs(store, clock, settings, outputs)
                if run['state'] == 'held':
                    time.sleep(0.1)
                    continue
                # Seeded autonomous bootstrap work uses the exact same command
                # validation as employee work. No V1 inventory effects are claimed.
                if os.getenv('AUTONOMOUS_SAMPLE', 'true').lower() == 'true':
                    store.seed_boundaries(settings)
                target = run['granted'] + settings.quantum
                if clock and not clock.pending:
                    if store.prepare_request(target, expected_epoch=run['epoch']):
                        clock.request(target)
                elif not clock:
                    elapsed = (datetime.now(timezone.utc) - run['anchor']).total_seconds()
                    if elapsed * run['speed'] >= settings.quantum and store.prepare_request(target, expected_epoch=run['epoch']):
                        grant_local(store, target, run['epoch'])
                time.sleep(0.05)
    except Exception as exc:
        log.exception('Controller stalled; operator recovery required')
        if lease_owned:
            store.stall(str(exc), expected_epoch=run['epoch'])
        if clock:
            h.helicsFederateGlobalError(clock.federate, 1, str(exc))
    finally:
        if clock:
            clock.finalize()


if __name__ == '__main__':
    main()

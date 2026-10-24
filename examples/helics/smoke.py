"""Real five-process federation: four bootstrap apps and an external power peer.

Uses isolated temporary PostgreSQL databases. Delays a peer grant, checks that
future work remains untouched, exchanges typed power values and versioned
messages, then finalizes and removes only these temporary databases.
"""
import json
import multiprocessing as mp
import os
import queue
import time
import traceback
from urllib.parse import urlsplit, urlunsplit
from uuid import uuid4

import helics as h
import psycopg
from psycopg import sql

from simulator.clocks import HelicsClock
from simulator.contracts import Envelope
from simulator.store import Store
from simulator.config import Settings
from simulator.controller import publish_boundaries, settle_outputs
from simulator.federation_config import config, ROUTES, PROVIDERS

APPS = ['manufacturing', 'storage', 'logistics', 'shipping']


def business(name, url, broker, run_id, epoch, results):
    clock = None
    try:
        store = Store(url, 'helics', run_id, epoch)
        store.migrate()
        job = store.schedule('grant-gated', 1, {'quantity': 2})
        future_job=store.schedule('future-after-interrupt',8,{'quantity':7})
        clock = HelicsClock(config(name, broker))
        clock.initialize()
        deadline = time.monotonic()+20
        while not clock.initialized():
            if time.monotonic() > deadline:
                raise TimeoutError('Initializing HELICS')
            time.sleep(0.01)
        assert store.prepare_request(1)
        clock.request(1)
        assert settle_outputs(store,clock,None,[]) is False
        # External peer deliberately has not requested time yet.
        time.sleep(0.2)
        assert clock.poll() is None, 'Unexpected grant before delayed power peer'
        assert store.execute(job['id']) == 'waiting'
        assert store.status()['effects'] == 0
        grant = None
        while grant is None:
            grant = clock.poll()
            if time.monotonic() > deadline:
                raise TimeoutError('Waiting for delayed grant')
            time.sleep(0.01)
        power = clock.values()['external-power/available_power_kw']
        assert power == 25.0
        store.grant(grant, expected_epoch=store.status()['run']['epoch'])
        assert store.execute(job['id']) == 'completed'
        destination, boundary = ROUTES[name]
        settings=Settings(app=name,mode='helics',providers=PROVIDERS[name],federation_id='bootstrap-smoke')
        publish_boundaries(store,clock,settings,[{'destination':destination,'boundary':boundary,'endpoint':destination+'/events'}])
        assert store.prepare_request(5)
        clock.publish_value(2)
        clock.request(5)
        grant = None
        while grant is None:
            grant = clock.poll()
            if time.monotonic() > deadline:
                raise TimeoutError('Waiting for message grant')
            time.sleep(0.01)
        assert grant==2 and grant<5, 'Peer message must interrupt the request for time 5'
        store.grant(grant)
        assert store.execute(future_job['id'])=='waiting'
        received = clock.receive()
        assert len(received) == 1, f'{name} expected one peer message, got {len(received)}'
        sender, raw = received[0]
        incoming = Envelope.model_validate(raw)
        assert incoming.payload.quantity == 2
        assert sender == incoming.source+'/events'
        assert store.ingest(incoming, incoming.source, incoming.boundary, name) == 'accepted'
        assert store.ingest(incoming, incoming.source, incoming.boundary, name) == 'duplicate'
        incoming_job = next(j for j in store.status()['jobs'] if j['idempotency_key'].startswith('boundary:'))
        assert store.execute(incoming_job['id']) == 'completed'
        assert store.status()['effects'] == 4
        results.put((name, 'passed', 'delayed grant; requested 5, granted 2; typed 25 kW; peer event and deduplication'))
    except Exception as exc:
        traceback.print_exc()
        results.put((name, 'failed', repr(exc)))
    finally:
        if clock:
            clock.finalize()


def external(broker, results):
    clock = None
    try:
        clock = HelicsClock(config('external-power', broker, power=True))
        clock.initialize()
        deadline = time.monotonic()+20
        while not clock.initialized():
            if time.monotonic()>deadline:
                raise TimeoutError('Power peer initialization')
            time.sleep(0.01)
        clock.publish_value(25)
        time.sleep(1)  # Deliberate wall-time delay, not simulation-time advancement.
        for target in (1,2):
            clock.request(target)
            while clock.poll() is None:
                if time.monotonic()>deadline:
                    raise TimeoutError('Power peer time grant')
                time.sleep(0.01)
        results.put(('external-power', 'passed', 'typed value publication'))
    except Exception as exc:
        results.put(('external-power', 'failed', repr(exc)))
    finally:
        if clock:
            clock.finalize()


def main():
    admin_url = os.environ['TEST_DATABASE_URL']
    context = mp.get_context('spawn')
    results = context.Queue()
    suffix = uuid4().hex[:8]
    run_id, epoch = str(uuid4()), str(uuid4())
    databases = []
    broker = h.helicsCreateBroker('tcp_ss', 'bootstrap-'+suffix, '-f5 --port=24900 --loglevel=warning')
    address = h.helicsBrokerGetAddress(broker)
    processes = []
    try:
        with psycopg.connect(admin_url, autocommit=True) as db:
            for app in APPS:
                database = 'simu_smoke_'+app+'_'+suffix
                db.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(database)))
                databases.append(database)
                parts = urlsplit(admin_url)
                url = urlunsplit((parts.scheme, parts.netloc, '/'+database, parts.query, ''))
                processes.append(context.Process(target=business, args=(app,url,address,run_id,epoch,results)))
        processes.append(context.Process(target=external,args=(address,results)))
        for process in processes:
            process.start()
        for process in processes:
            process.join(30)
        outcomes=[]
        for _ in processes:
            try:
                outcomes.append(results.get(timeout=2))
            except queue.Empty:
                raise AssertionError('Missing federation process result')
        for outcome in sorted(outcomes):
            print(' | '.join(outcome), flush=True)
        assert all(x[1]=='passed' for x in outcomes)
        assert all(p.exitcode == 0 for p in processes)
        print('HELICS federation smoke passed (four applications + external peer).')
    finally:
        for process in processes:
            if process.is_alive():
                process.terminate()
                process.join(3)
        h.helicsBrokerDisconnect(broker)
        h.helicsBrokerFree(broker)
        with psycopg.connect(admin_url, autocommit=True) as db:
            for database in databases:
                db.execute(sql.SQL('DROP DATABASE {} WITH (FORCE)').format(sql.Identifier(database)))


if __name__ == '__main__':
    main()

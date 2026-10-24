"""Durable, optional read projection. No business handlers or HELICS calls."""
import json
from hashlib import sha256
from datetime import datetime
import logging
import math
import os
import signal
import threading
from urllib.parse import urlsplit
from uuid import UUID

import httpx
import psycopg
from psycopg.types.json import Jsonb

from simulator.config import Settings
from simulator.store import Store
from .handling_projection import validate_handling, retain_handling, register_manifests, validate_handling_events, ManifestConflict, reconcile_handling

NAMES = {'manufacturing', 'storage', 'logistics', 'shipping'}
RUN_FIELDS = {'id', 'epoch', 'mode', 'state', 'granted', 'requested', 'committed',
              'speed', 'anchor', 'scenario', 'blocked_reason'}


def safe_url(value):
    if not isinstance(value, str):
        raise ValueError('HTTP URL required')
    parsed = urlsplit(value)
    if parsed.scheme not in {'http', 'https'} or not parsed.hostname or parsed.username or parsed.password or parsed.fragment or parsed.query:
        raise ValueError('HTTP URL without embedded credentials, query or fragment required')
    return value.rstrip('/')


def configurations(values):
    if not isinstance(values, list):
        raise ValueError('TWIN_SOURCES must be a list')
    result, names = [], set()
    for value in values:
        if not isinstance(value, dict) or value.get('name') not in NAMES or value['name'] in names:
            raise ValueError('Unique departmental source names required')
        names.add(value['name'])
        if not all(isinstance(value.get(key), str) and value[key] for key in ('username', 'password')):
            raise ValueError('Server-side source credentials required')
        result.append({**value, 'url': safe_url(value['url']),
                       'website_url': safe_url(value['website_url']) if value.get('website_url') else None})
    return result


def validate(config, value):
    if not isinstance(value, dict) or value.get('version') != 1 or value.get('source') != config['name']:
        raise ValueError('Projection version or source identity mismatch')
    run = value.get('run')
    if not isinstance(run, dict):
        raise ValueError('Source run required')
    for key in ('id', 'epoch'):
        try: UUID(run[key])
        except (KeyError, TypeError, ValueError, AttributeError) as exc:
            raise ValueError('Source run and epoch UUID required') from exc
    for key in ('granted', 'requested', 'committed'):
        number = run.get(key)
        if isinstance(number, bool) or not isinstance(number, (int, float)) or not math.isfinite(number) or number < 0:
            raise ValueError('Finite nonnegative source watermark required')
    if run['committed'] > run['granted']:
        raise ValueError('Committed time cannot exceed grant')
    cursor = value.get('cursor')
    if not isinstance(cursor, str) or not 1 <= len(cursor) <= 256:
        raise ValueError('Opaque source cursor required')
    if not isinstance(value.get('snapshot'), dict) or not isinstance(value.get('events'), list):
        raise ValueError('Complete snapshot and event list required')
    if 'handling' in value['snapshot']:
        validate_handling(config['name'], run, value['snapshot']['handling'])
        validate_handling_events(config['name'], value['snapshot']['handling'], value['events'])
    seen = set()
    for event in value['events']:
        if not isinstance(event, dict) or not isinstance(event.get('id'), str) or not 1 <= len(event['id']) <= 256 or event['id'] in seen:
            raise ValueError('Unique stable source event identities required')
        for key in ('run_id', 'epoch'):
            if key in event and str(event[key]) != run['id' if key == 'run_id' else key]:
                raise ValueError('Event belongs to a different run or epoch')
        if 'simulation_time' in event:
            number = event['simulation_time']
            if isinstance(number, bool) or not isinstance(number, (int, float)) or not math.isfinite(number) or number < 0:
                raise ValueError('Finite nonnegative event time required')
        if 'correlation_id' in event and event['correlation_id'] is not None and not isinstance(event['correlation_id'], str):
            raise ValueError('String event correlation required')
        seen.add(event['id'])
    # Source responses contain domain data only; never persist HTTP authentication metadata.
    clean = {key: run[key] for key in RUN_FIELDS if key in run}
    return {**value, 'run': clean}


def source_key(source):
    return sha256((source['url'].rstrip('/')+'\n'+source['username']).encode()).hexdigest()


def operational_health(value):
    if not isinstance(value, dict):
        return None
    result = {key: value.get(key) if type(value.get(key)) is bool else None
              for key in ('ready', 'broker')}
    for key in ('pending_jobs', 'dead_letters'):
        number = value.get(key)
        result[key] = number if type(number) is int and number >= 0 else None
    result['heartbeats'] = []
    for heartbeat in value.get('heartbeats', []) if isinstance(value.get('heartbeats'), list) else []:
        if isinstance(heartbeat, dict) and isinstance(heartbeat.get('role'), str):
            item = {'role': heartbeat['role'], 'healthy': heartbeat.get('healthy') if type(heartbeat.get('healthy')) is bool else None}
            if isinstance(heartbeat.get('seen_at'), str): item['seen_at'] = heartbeat['seen_at']
            result['heartbeats'].append(item)
    return result


class ProjectionStore:
    def __init__(self, store):
        self.store = store

    @staticmethod
    def revision(db, source):
        # All writers take this lock before assigning revisions. A lower sequence
        # cannot commit after a higher one and disappear behind a browser cursor.
        db.execute('SELECT pg_advisory_xact_lock(8192110)')
        db.execute('INSERT INTO twin_revisions(source) VALUES (%s)', (source,))

    def configure(self, sources):
        sources = configurations(sources)
        with self.store.transaction() as db:
            db.execute('SELECT pg_advisory_xact_lock(8192110)')
            configured = [row['name'] for row in db.execute('SELECT name FROM twin_sources WHERE configured').fetchall()]
            names = [s['name'] for s in sources]
            db.execute('UPDATE twin_sources SET configured=false,connected=false WHERE NOT (name=ANY(%s))', (names,))
            for source in sources:
                db.execute('''INSERT INTO twin_sources(name,website_url,source_key) VALUES (%s,%s,%s)
                    ON CONFLICT(name) DO UPDATE SET configured=true,website_url=EXCLUDED.website_url,
                    connected=CASE WHEN twin_sources.source_key IS DISTINCT FROM EXCLUDED.source_key THEN false ELSE twin_sources.connected END,
                    generation=CASE WHEN twin_sources.source_key IS DISTINCT FROM EXCLUDED.source_key THEN twin_sources.generation+1 ELSE twin_sources.generation END,
                    source_key=EXCLUDED.source_key''',
                           (source['name'], source['website_url'], source_key(source)))
            if set(configured) != set(names): self.revision(db, 'configuration')
        return sources

    def begin(self, name, config=None):
        with self.store.transaction() as db:
            saved = db.execute('UPDATE twin_sources SET generation=generation+1 WHERE name=%s AND configured AND (%s::text IS NULL OR source_key=%s) RETURNING generation',
                               (name, source_key(config) if config else None, source_key(config) if config else None)).fetchone()
            return saved['generation'] if saved else None

    def accept(self, config, value, generation=None):
        value = validate(config, value)
        run = value['run']
        with self.store.transaction() as db:
            db.execute('SELECT pg_advisory_xact_lock(8192110)')
            previous = db.execute('SELECT * FROM twin_sources WHERE name=%s AND configured FOR UPDATE', (config['name'],)).fetchone()
            if not previous or previous['source_key'] != source_key(config) or generation is not None and generation != previous['generation']:
                return False
            old = previous['status']['run'] if previous['status'] else None
            retired = previous['retired_epochs']
            scope = [run['id'], run['epoch']]
            if scope in retired:
                raise ValueError('Retired source epoch cannot become current')
            if old and (old['id'], old['epoch']) == tuple(scope):
                if any(run[key] < old[key] for key in ('granted', 'committed')):
                    raise ValueError('Source watermark regressed')
                retain_handling(previous['snapshot'], value['snapshot'])
                # Full history cannot forget previously observed committed facts.
                ids = [e['id'] for e in value['events']]
                if db.execute('SELECT 1 FROM twin_events WHERE source=%s AND run_id=%s AND epoch=%s AND NOT(id=ANY(%s)) LIMIT 1',
                              (config['name'], *scope, ids)).fetchone():
                    raise ValueError('Source omitted retained event history')
            elif old:
                retired = [*retired, [old['id'], old['epoch']]]
            if 'handling' in value['snapshot']:
                register_manifests(db, config['name'], value['snapshot']['handling'])
            for event in value['events']:
                saved = db.execute('SELECT payload FROM twin_events WHERE source=%s AND run_id=%s AND epoch=%s AND id=%s',
                                   (config['name'], *scope, event['id'])).fetchone()
                if saved and saved['payload'] != event:
                    raise ValueError('Source reused event identity with different content')
                if not saved:
                    db.execute('INSERT INTO twin_events(source,run_id,epoch,id,payload) VALUES (%s,%s,%s,%s,%s)',
                               (config['name'], *scope, event['id'], Jsonb(event)))
            db.execute("UPDATE twin_sources SET status=%s,snapshot=%s,cursor=%s,connected=true,observed_at=clock_timestamp(),last_success_at=clock_timestamp(),error=NULL,handling_conflicts='[]',retired_epochs=%s WHERE name=%s",
                       (Jsonb({'run': run, 'health': operational_health(value.get('health')), **({'effects': value['effects']} if isinstance(value.get('effects'), (int, float)) else {})}), Jsonb(value['snapshot']), value['cursor'], Jsonb(retired), config['name']))
            # Freshness is visible state, even when business content is unchanged.
            self.revision(db, config['name'])
        return True

    def failure(self, name, generation=None, conflict=None):
        with self.store.transaction() as db:
            db.execute('SELECT pg_advisory_xact_lock(8192110)')
            saved = db.execute("UPDATE twin_sources SET handling_conflicts=COALESCE(%s::jsonb,handling_conflicts),connected=false,observed_at=clock_timestamp(),error='Source unavailable or projection contract rejected' WHERE name=%s AND configured AND (%s::bigint IS NULL OR generation=%s) RETURNING name", (Jsonb([conflict]) if conflict is not None else None, name, generation, generation)).fetchone()
            if saved: self.revision(db, name)

    def view(self):
        with self.store.connect() as db:
            # One repeatable snapshot for sources/events/revision; never a
            # federation-wide snapshot of the independent business databases.
            db.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ')
            db.execute('SELECT pg_advisory_xact_lock_shared(8192103)')
            revision = db.execute('SELECT COALESCE(max(id),0) AS id FROM twin_revisions').fetchone()['id']
            heartbeats = db.execute("SELECT role,seen_at,seen_at>clock_timestamp()-interval '15 seconds' AS healthy FROM heartbeats ORDER BY role").fetchall()
            sources = db.execute("SELECT name,website_url,status,snapshot,cursor,handling_conflicts,observed_at,last_success_at,error,connected AND last_success_at>clock_timestamp()-interval '15 seconds' AS connected,NOT(connected AND last_success_at>clock_timestamp()-interval '15 seconds') AS stale FROM twin_sources WHERE configured ORDER BY name").fetchall()
            events = db.execute("SELECT e.* FROM twin_events e JOIN twin_sources s ON s.name=e.source AND s.configured AND s.status->'run'->>'id'=e.run_id AND s.status->'run'->>'epoch'=e.epoch ORDER BY e.source,e.id").fetchall()
        for source in sources:
            source['health'] = (source['status'] or {}).get('health')
        for event in events:
            event.update({key: event['payload'][key] for key in ('correlation_id', 'simulation_time') if key in event['payload']})
        aligned = None
        if sources and all(s['connected'] and s['status'] for s in sources):
            runs = [s['status']['run'] for s in sources]
            # Federated sources share run/epoch AND the scenario's time origin.
            def identity(r):
                scenario = r.get('scenario') or {}
                if not isinstance(scenario, dict): return None
                try:
                    origin = datetime.fromisoformat(scenario.get('start_at', r.get('anchor')).replace('Z', '+00:00'))
                    if origin.utcoffset() is None: return None
                except (AttributeError, TypeError, ValueError):
                    return None
                return r['id'], r['epoch'], origin.timestamp(), scenario.get('time_zone')
            if identity(runs[0]) is not None and all(identity(r) == identity(runs[0]) for r in runs):
                aligned = {'run_id': runs[0]['id'], 'epoch': runs[0]['epoch'],
                           'committed': min(r['committed'] for r in runs)}
        return {'revision': revision, 'sources': sources, 'events': events, 'handling': reconcile_handling(sources),
                'aligned': aligned, 'mode': 'live', 'controls': [], 'heartbeats': heartbeats}


class Consumer:
    def __init__(self, projection, sources, client):
        self.projection, self.client = projection, client
        self.sources = projection.configure(sources)

    def tick(self):
        for source in self.sources:
            generation = self.projection.begin(source['name'], source)
            if generation is None:
                continue
            try:
                with self.client.stream('GET', source['url'] + '/api/projection',
                                        auth=(source['username'], source['password'])) as response:
                    response.raise_for_status()
                    data = bytearray()
                    for chunk in response.iter_bytes():
                        data.extend(chunk)
                        if len(data) > 32 * 1024 * 1024:
                            raise ValueError('Projection exceeds bounded response size')
                    value = json.loads(data)
                if not isinstance(value, dict):
                    raise ValueError('Projection object required')
                health = operational_health(value.get('health')) or operational_health({})
                try:
                    readiness = self.client.get(source['url'] + '/api/health/ready',
                                                auth=(source['username'], source['password']), timeout=1)
                    if readiness.status_code in (200, 503):
                        if readiness.status_code == 503:
                            health['ready'] = False
                        detail = readiness.json()
                        if isinstance(detail, dict):
                            if readiness.status_code == 200 and type(detail.get('ready')) is bool:
                                health['ready'] = detail['ready']
                            if type(detail.get('broker')) is bool:
                                health['broker'] = detail['broker']
                except (httpx.HTTPError, ValueError):
                    # A missing health probe never destroys a valid business snapshot.
                    pass
                value['health'] = health
                self.projection.accept(source, value, generation)
            except (httpx.HTTPError, ValueError, KeyError, TypeError) as error:
                # No upstream bodies, credentials or URLs in persisted errors/logs.
                self.projection.failure(source['name'], generation, conflict=error.conflict if isinstance(error, ManifestConflict) else None)
        self.projection.store.heartbeat('projection')


def main():
    logging.basicConfig(level=logging.INFO)
    settings = Settings.from_env()
    store = Store(settings.database_url)
    store.migrate()
    stopping = threading.Event()
    signal.signal(signal.SIGTERM, lambda *_: stopping.set())
    signal.signal(signal.SIGINT, lambda *_: stopping.set())
    with httpx.Client(timeout=3, follow_redirects=False) as client:
        consumer = Consumer(ProjectionStore(store), json.loads(os.getenv('TWIN_SOURCES', '[]')), client)
        while not stopping.is_set():
            try: consumer.tick()
            except psycopg.Error: logging.error('Twin projection database unavailable')
            stopping.wait(1)


if __name__ == '__main__':
    main()

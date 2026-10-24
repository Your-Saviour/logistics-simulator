"""Container-only production Twin recovery checks and explicit contract fixtures.

Fixtures model the complete-history projection contract; they do not model native
HELICS or departmental transactions. No Docker socket or host ports are needed.
"""
import argparse
import base64
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

RUN = '00000000-0000-4000-8000-000000000001'
EPOCH = '00000000-0000-4000-8000-000000000002'
SOURCE_AUTH = ('fixture-observer', 'isolated-source-password')
TWIN_AUTH = ('twin-observer', 'isolated-observer')


def auth(credentials):
    return 'Basic ' + base64.b64encode(':'.join(credentials).encode()).decode()


def request(url, credentials=TWIN_AUTH, method='GET'):
    with urlopen(Request(url, headers={'Authorization': auth(credentials)}, method=method), timeout=4) as response:
        return json.load(response)


def wait(check, timeout=90):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            value = request('http://api:8000/api/twin')
            if check(value):
                return value
        except (HTTPError, URLError, TimeoutError, ConnectionError):
            pass
        time.sleep(.25)
    raise AssertionError('Twin acceptance condition timed out')


def serve(name):
    class Handler(BaseHTTPRequestHandler):
        sequence = 1

        def log_message(self, *_):
            pass

        def do_GET(self):
            if self.headers.get('Authorization') != auth(SOURCE_AUTH):
                self.send_error(401)
                return
            if self.path != '/api/projection':
                self.send_error(404)
                return
            value = {'version': 1, 'source': name,
                     'run': {'id': RUN if name == 'storage' else '00000000-0000-4000-8000-000000000003', 'epoch': EPOCH, 'state': 'running',
                             'mode': 'standalone', 'granted': self.sequence,
                             'requested': self.sequence, 'committed': self.sequence},
                     'cursor': str(self.sequence), 'snapshot': {'effects': self.sequence},
                     'events': [{'id': f'{name}-{i}', 'kind': 'fixture.effect',
                                 'correlation_id': f'fixture-handoff-{i}', 'simulation_time': i}
                                for i in range(1, self.sequence + 1)]}
            payload = json.dumps(value).encode()
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def do_POST(self):
            if self.headers.get('Authorization') != auth(SOURCE_AUTH):
                self.send_error(401)
                return
            if self.path != '/advance':
                self.send_error(404)
                return
            type(self).sequence += 1
            self.do_projection_ack()

        def do_projection_ack(self):
            body = json.dumps({'committed': self.sequence}).encode()
            self.send_response(200)
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    ThreadingHTTPServer(('0.0.0.0', 8000), Handler).serve_forever()


def verify(phase):
    def sources(value):
        return {source['name']: source for source in value['sources']}

    if phase == 'zero':
        value = wait(lambda v: v['sources'] == [] and any(h['role'] == 'projection' and h['healthy'] for h in v.get('heartbeats', [])))
        assert value['events'] == [] and value['controls'] == []
        readiness = request('http://api:8000/api/health/ready')
        assert readiness['ready'] and readiness['database'] and readiness['broker']
    elif phase in ('subset', 'reconfigured'):
        value = wait(lambda v: set(sources(v)) == {'storage'} and sources(v)['storage']['connected'])
        assert all(event['source'] == 'storage' for event in value['events'])
        assert len(value['events']) == (3 if phase == 'reconfigured' else 1)
    elif phase == 'connected':
        value = wait(lambda v: set(sources(v)) == {'storage', 'shipping'} and all(s['connected'] for s in v['sources']))
        assert len(value['events']) == 2
        # Independent run identities must not claim federation alignment.
        assert value['aligned'] is None and value['controls'] == []
        for source in value['sources']:
            assert source['health']['ready'] is None and source['health']['broker'] is None
            assert source['health']['pending_jobs'] is None and source['health']['dead_letters'] is None
    elif phase == 'stale':
        value = wait(lambda v: 'shipping' in sources(v) and sources(v)['shipping']['stale'])
        source = sources(value)['shipping']
        assert not source['connected'] and source['snapshot']['effects'] == 1
        assert sources(value)['storage']['connected'] and not sources(value)['storage']['stale']
        assert source['last_success_at'] and source['error']
        assert any(event['source'] == 'shipping' for event in value['events'])
    elif phase == 'advance':
        for name in ('storage', 'shipping'):
            for expected in (2, 3):
                value = request(f'http://{name}-fixture:8000/advance', SOURCE_AUTH, 'POST')
                assert value['committed'] == expected
        print('Contract fixtures advanced twice while all Twin application services were stopped.', flush=True)
        return
    elif phase in ('catchup', 'durable'):
        value = wait(lambda v: len(v['sources']) == 2 and all(s['connected'] and s['cursor'] == '3' for s in v['sources']))
        assert len(value['events']) == 6
        assert len({(e['source'], e['run_id'], e['epoch'], e['id']) for e in value['events']}) == 6
        assert all(s['snapshot']['effects'] == 3 for s in value['sources'])
        revision = value['revision']
        replay = request(f'http://api:8000/api/twin/events?after={max(0, revision - 1)}')
        assert replay['revision'] >= revision and len(replay['events']) == 6
    else:
        raise AssertionError('Unknown phase')
    assert value['mode'] == 'live'
    serialized = json.dumps(value)
    assert SOURCE_AUTH[1] not in serialized and TWIN_AUTH[1] not in serialized
    # Exercise production Nginx proxy as a distinct deployed website.
    website = request('http://web:8080/api/twin')
    assert website['mode'] == 'live'
    with urlopen('http://web:8080/', timeout=4) as response:
        assert response.status == 200 and 'text/html' in response.headers['Content-Type']
    print(f'Twin production contract acceptance: {phase} passed.', flush=True)


def native(phase, twin_url, skip_sites):
    """Read actual departmental projections after the existing browser workflows."""
    configs = json.loads(os.environ['TWIN_SOURCES'])
    assert {c['name'] for c in configs} == {'storage', 'manufacturing', 'logistics', 'shipping'}
    credentials = (os.environ['APP_USERNAME'], os.environ['APP_PASSWORD'])
    if phase == 'without-twin':
        try:
            request(twin_url.rstrip('/') + '/api/twin', credentials)
        except HTTPError:
            raise AssertionError('Twin API still responds over HTTP') from None
        except (URLError, TimeoutError, ConnectionError):
            pass
        else:
            raise AssertionError('Twin API must be stopped for this phase')

        def runs():
            return {config['name']: request(config['url'].rstrip('/') + '/api/status',
                    (config['username'], config['password']))['run'] for config in configs}

        before = runs()
        assert all(run['state'] == 'running' for run in before.values()), 'All native sources must be running'
        deadline = time.monotonic() + 20
        progressed = set()
        while time.monotonic() < deadline:
            after = runs()
            progressed = set()
            for name, run in after.items():
                assert run['state'] == 'running', name + ': source stopped running'
                assert (run['id'], run['epoch']) == (before[name]['id'], before[name]['epoch']), name + ': source run changed'
                if run['granted'] > before[name]['granted'] and run['committed'] > before[name]['committed']:
                    progressed.add(name)
            if progressed == set(before):
                print('Native independence: all four running sources advanced granted and committed time while Twin API, consumer and website were stopped.', flush=True)
                return
            time.sleep(.5)
        raise AssertionError('Native sources did not advance while Twin stopped: ' + ','.join(sorted(set(before) - progressed)))
    if phase == 'five-sites':
        sites = json.loads(os.environ.get('STACK_APPS', '[]')) or [
            {'name': name, 'url': f'http://{name}-web:' + ('8080' if name == 'twin' else '80')}
            if name != 'shipping' else {'name': name, 'url': 'http://shipping-api:8000'}
            for name in ('storage', 'manufacturing', 'logistics', 'shipping', 'twin')]
        assert len(sites) == 5 and len({site['url'] for site in sites}) == 5
        assert set(skip_sites).issubset({site['name'] for site in sites})
        def ready(check, name):
            deadline = time.monotonic() + 30
            while time.monotonic() < deadline:
                try:
                    if check():
                        return
                except (HTTPError, URLError, TimeoutError, ConnectionError):
                    pass
                time.sleep(.25)
            raise AssertionError(name + ': HTTP service did not become ready')

        def html(url):
            with urlopen(url, timeout=5) as response:
                return response.status == 200 and 'text/html' in response.headers['Content-Type']

        for site in sites:
            if site['name'] in skip_sites:
                continue
            ready(lambda: html(site['url']), site['name'])
        for config in configs:
            # Shipping serves HTML and API in the same process; its explicit
            # website outage therefore excludes only that source's HTTP API.
            if config['name'] == 'shipping' and 'shipping' in skip_sites:
                continue
            ready(lambda: request(config['url'].rstrip('/') + '/api/projection',
                                 (config['username'], config['password'])).get('source') == config['name'], config['name'])
        ready(lambda: request(twin_url.rstrip('/') + '/api/twin', credentials).get('mode') == 'live', 'twin')
        print('Five distinct native websites: remaining URLs returned HTML and independent source/Twin APIs responded; excluded site: ' + ','.join(skip_sites), flush=True)
        return
    captured = {}
    for config in configs:
        value = request(config['url'].rstrip('/') + '/api/projection', (config['username'], config['password']))
        assert value['version'] == 1 and value['source'] == config['name']
        assert value['cursor'] and isinstance(value['snapshot'], dict)
        assert len({event['id'] for event in value['events']}) == len(value['events'])
        captured[config['name']] = value
    # These records are created and committed by existing native employee browser
    # checks. Shipping is deliberately checked only as an observed source.
    for name, key, state in [('storage', 'transfers', 'received'),
                             ('manufacturing', 'orders', 'completed'),
                             ('logistics', 'transfers', 'received')]:
        assert any(row['status'] == state for row in captured[name]['snapshot'][key]), name
        assert captured[name]['events'], name
    deadline = time.monotonic() + 90
    while time.monotonic() < deadline:
        twin = request(twin_url.rstrip('/') + '/api/twin', credentials)
        sources = {source['name']: source for source in twin['sources']}
        events = {(event['source'], event['id']): event for event in twin['events']}
        matched = set(sources) == set(captured)
        for name, value in captured.items():
            source = sources.get(name, {})
            matched = matched and source.get('connected') and not source.get('stale')
            matched = matched and ((source.get('status') or {}).get('run') or {}).get('id') == value['run']['id']
            matched = matched and ((source.get('status') or {}).get('run') or {}).get('epoch') == value['run']['epoch']
            record_key = 'transfers' if name in ('storage', 'logistics') else 'orders'
            current_records = (source.get('snapshot') or {}).get(record_key, [])
            # Compare immutable identities for records that can keep progressing.
            # Only the explicitly asserted terminal browser states are fenced to
            # their captured status; a pending shipping order may finish meanwhile.
            expected_ids = {row['id'] for row in value['snapshot'][record_key]}
            matched = matched and expected_ids.issubset({row['id'] for row in current_records})
            if name != 'shipping':
                terminal = 'completed' if name == 'manufacturing' else 'received'
                expected_terminal = {row['id'] for row in value['snapshot'][record_key] if row['status'] == terminal}
                observed_terminal = {row['id'] for row in current_records if row['status'] == terminal}
                matched = matched and expected_terminal.issubset(observed_terminal)
            for event in value['events']:
                observed = events.get((name, event['id']), {})
                matched = matched and observed.get('payload') == event
        if matched:
            assert twin['mode'] == 'live' and twin['controls'] == []
            # Independent standalone runs must remain separate timelines.
            if len({v['run']['id'] for v in captured.values()}) > 1:
                assert twin['aligned'] is None
            public = json.dumps(twin)
            assert all(config['password'] not in public for config in configs)
            print('Native Twin observation: authenticated four-source contracts, committed storage/production/transport records and complete captured event payloads passed.', flush=True)
            return
        time.sleep(.5)
    raise AssertionError('Native Twin did not catch up to committed departmental snapshots/history')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--serve', choices=['storage', 'shipping'])
    parser.add_argument('--phase', default='connected', choices=['zero', 'subset', 'connected', 'stale', 'advance', 'catchup', 'durable', 'reconfigured', 'native', 'five-sites', 'without-twin'])
    parser.add_argument('--twin-url', default='http://twin-api:8000')
    parser.add_argument('--skip-site', action='append', default=[])
    args = parser.parse_args()
    if args.serve:
        serve(args.serve)
    elif args.phase in ('native', 'five-sites', 'without-twin'):
        native(args.phase, args.twin_url, args.skip_site)
    else:
        verify(args.phase)

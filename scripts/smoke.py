#!/usr/bin/env python3
"""HTTP acceptance check for a running standalone application or suite."""
import argparse
import base64
import json
from pathlib import Path
import time
import urllib.request
from uuid import uuid4

APPS = ['manufacturing', 'storage', 'logistics', 'shipping', 'twin']


def call(app, path, body=None, key=None):
    secret = json.loads(Path(f'deploy/generated/{app}.secrets.json').read_text())['application']
    authorization = base64.b64encode((app+'-operator:'+secret).encode()).decode()
    headers = {'Authorization': 'Basic '+authorization}
    if body is not None:
        headers['Content-Type'] = 'application/json'
    if key:
        headers['Idempotency-Key'] = key
    request = urllib.request.Request(f'http://127.0.0.1:{8181+APPS.index(app)}/api/{path}',
                                     data=json.dumps(body).encode() if body is not None else None, headers=headers)
    with urllib.request.urlopen(request, timeout=10) as response:
        return json.load(response)


def check(app):
    deadline = time.monotonic()+180
    while True:
        try:
            status = call(app, 'status')
            assert status['application'] == app
            assert call(app, 'health/ready')['ready']
            break
        except Exception:
            if time.monotonic() > deadline:
                raise
            time.sleep(1)
    if app == 'twin':
        sources = call(app, 'sources')
        print(f'{app}: healthy; {len(sources)} configured sources')
        return
    # Hold prevents wall-time advancement while testing the transaction.
    call(app, 'control/hold', {})
    run = call(app, 'status')['run']
    before = call(app, 'status')['effects']
    body = {'due_at': max(run['granted'],run['requested'])+2, 'quantity': 7}
    key = 'smoke-'+uuid4().hex
    job = call(app, 'jobs', body, key)
    duplicate = call(app, 'jobs', body, key)
    assert duplicate['id'] == job['id']
    time.sleep(0.25)
    assert call(app, 'status')['effects'] == before
    call(app, 'control/resume', {})
    deadline = time.monotonic()+30
    while True:
        status = call(app, 'status')
        found = next(j for j in status['jobs'] if j['id'] == job['id'])
        if found['status']=='completed':
            break
        if time.monotonic()>deadline:
            raise AssertionError(f'{app} did not complete its sample job')
        time.sleep(0.3)
    assert status['effects'] >= before+7
    print(f'{app}: healthy; held/future work, idempotent submission and committed sample passed')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('app',choices=APPS+['suite'])
    args=parser.parse_args()
    for app in APPS if args.app=='suite' else [args.app]:
        check(app)

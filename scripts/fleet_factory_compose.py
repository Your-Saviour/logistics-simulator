"""Disposable four-native HELICS + fleet fixture; host generation/control only.

Reuse the custody fixture without rewriting its manifest or shared identity file.
Every generated input belongs to this invocation's ignored directory.
"""
import argparse
from contextlib import redirect_stdout
import io
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys
import time
from uuid import uuid4

import handling_factory_compose as native
import stacks_compose as stacks

ROOT = Path(__file__).resolve().parents[1]
APPS = ('storage', 'manufacturing', 'shipping', 'logistics')


class FixtureRoot:
    def __init__(self, manifest, inputs):
        self.manifest, self.inputs = manifest, inputs

    def __str__(self):
        return str(ROOT)

    def __truediv__(self, part):
        if str(part) == 'deploy':
            return self.inputs / 'deploy'
        if str(part) == 'deploy/generated/handling-factory.json':
            return self.manifest
        return ROOT / part


def private_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2))
    path.chmod(0o600)


def generate(manifest, artifacts, with_twin=False):
    isolated = FixtureRoot(manifest, manifest.with_suffix('.inputs'))
    original_native, original_stacks = native.ROOT, stacks.ROOT
    previous_artifacts = os.environ.get('HANDLING_FACTORY_ARTIFACTS')
    try:
        native.ROOT = stacks.ROOT = isolated
        os.environ['HANDLING_FACTORY_ARTIFACTS'] = str(artifacts)
        with redirect_stdout(io.StringIO()):
            native.main()
        value = json.loads(manifest.read_text())
        twin = stacks.generate(['twin'], write=False) if with_twin else None
    finally:
        native.ROOT, stacks.ROOT = original_native, original_stacks
        if previous_artifacts is None:
            os.environ.pop('HANDLING_FACTORY_ARTIFACTS', None)
        else:
            os.environ['HANDLING_FACTORY_ARTIFACTS'] = previous_artifacts
    value['name'] = 'simu-fleet-factory-' + uuid4().hex[:10]
    services = value['services']
    # Internal-only diagnostics for a stalled native grant; no host port.
    services['factory-helics-broker']['entrypoint'].extend([
        '--name=fleet-factory-broker', '--http',
        '--http_server_args=--http_port=43542 --external'])
    fleet_run, fleet_epoch = str(uuid4()), str(uuid4())
    tokens = {name: secrets.token_hex(32) for name in (*APPS, 'observer')}
    sources, scopes = [], {}
    for app in APPS:
        env = services[app + '-api']['environment']
        scopes[app] = {'run_id': env['FEDERATION_RUN_ID'], 'epoch': env['FEDERATION_EPOCH'], 'offset': 0}
        observer = next(account for account in json.loads(env['APP_IDENTITIES']) if account['role'] == 'service')
        sources.append({'name': app, 'url': f'http://{app}-api:8000', 'username': observer['username'], 'password': observer['password']})
        for role in ('api', 'worker', 'controller'):
            own = services[app + '-' + role]['environment']
            own.update(FLEET_MODE='coordinated', FLEET_URL='http://fleet-api:8000', FLEET_TOKEN=tokens[app],
                       FLEET_RUN_ID=fleet_run, FLEET_EPOCH=fleet_epoch, FLEET_TIME_OFFSET='0',
                       HANDOFF_QUANTUM=os.getenv('FLEET_FACTORY_QUANTUM','10'))
            own['HELICS_TIMEOUT_SECONDS'] = '600'
    password = secrets.token_hex(24)
    fleet_url = f'postgresql://fleet:{password}@fleet-db:5432/fleet'
    fleet_env = {'DATABASE_URL': fleet_url, 'FLEET_RUN_ID': fleet_run, 'FLEET_EPOCH': fleet_epoch,
                 'FLEET_SCOPE': json.dumps(scopes), 'FLEET_SOURCES': json.dumps(sources),
                 'FLEET_TOKENS': json.dumps(tokens), 'FLEET_SIZE': os.getenv('FLEET_FACTORY_SIZE', '8')}
    services['fleet-db'] = {'image': 'postgres:17-alpine', 'environment': {'POSTGRES_USER': 'fleet', 'POSTGRES_PASSWORD': password, 'POSTGRES_DB': 'fleet'},
                            'healthcheck': {'test': ['CMD-SHELL', 'pg_isready -U fleet -d fleet'], 'interval': '2s', 'timeout': '3s', 'retries': 30},
                            'volumes': ['fleet-data:/var/lib/postgresql/data']}
    value['volumes']['fleet-data'] = {}
    for role in ('initialize', 'api', 'worker'):
        dependencies = {'fleet-db': {'condition': 'service_healthy'}}
        if role != 'initialize':
            dependencies['fleet-initialize'] = {'condition': 'service_completed_successfully'}
        services['fleet-' + role] = {'image': 'logistics-simulator:fleet-v1', 'build': {'context': str(ROOT), 'dockerfile': 'apps/fleet/Dockerfile'},
                                     'environment': {**fleet_env, 'ROLE': role}, 'depends_on': dependencies, 'restart': 'no'}
    verify = services['verify']
    verify['volumes'].append(str(ROOT / 'apps/fleet/backend') + ':/app/fleet:ro')
    fault_only = os.getenv('FLEET_FACTORY_FAULT_ONLY') == '1'
    verify['command'] = ['python', 'scripts/fleet_fault_verify.py' if fault_only else 'scripts/fleet_factory_verify.py']
    verify['mem_limit'] = '512m'
    verify['environment'].update(FLEET_URL='http://fleet-api:8000', FLEET_TOKEN=tokens['observer'], FLEET_DATABASE_URL=fleet_url,
                                 FLEET_RUN_ID=fleet_run, FLEET_EPOCH=fleet_epoch, FLEET_SCOPE=json.dumps(scopes),
                                 FLEET_FACTORY_WITH_TWIN='1' if with_twin else '0', FACTORY_RESTART_WORKERS='0',
                                 FLEET_FACTORY_FAULT_ONLY='1' if fault_only else '0',
                                 FACTORY_HANDOFF_QUANTUM=os.getenv('FLEET_FACTORY_QUANTUM','10'),
                                 FLEET_FACTORY_TIMEOUT=os.getenv('FLEET_FACTORY_TIMEOUT', '1800'))
    if twin:
        twin_services = {name: service for name, service in twin['services'].items() if name in {'twin-db', 'twin-broker', 'twin-api', 'twin-projection'}}
        for role in ('api', 'projection'):
            twin_services['twin-' + role]['environment'].update(TWIN_SOURCES=json.dumps(sources),
                TWIN_FLEET_SOURCE=json.dumps({'url': 'http://fleet-api:8000', 'token': tokens['observer']}))
        services.update(twin_services)
        value['volumes'].update(twin['volumes'])
        own = twin_services['twin-api']['environment']
        verify['environment']['FLEET_FACTORY_TWIN_IDENTITY'] = json.dumps({'username': own['APP_USERNAME'], 'password': own['APP_PASSWORD']})
    private_json(manifest, value)
    return value


def control(manifest, artifacts):
    value = json.loads(manifest.read_text())
    verifier = value['name'] + '-verifier'
    compose = ['compose', '-f', str(manifest)]
    def work(*args):
        subprocess.run([sys.executable, str(ROOT / 'scripts/docker_guard.py'), '--wait', '--label', 'fleet-factory', '--', 'docker', *args], check=True)
    def inspect(identity):
        return json.loads(subprocess.check_output(['docker', 'inspect', identity], text=True))[0]['State']
    work(*compose, 'run', '-d', '--no-deps', '--name', verifier, 'verify')
    deadline = time.monotonic() + int(os.getenv('FLEET_FACTORY_TIMEOUT', '1800'))
    restarted = False
    faulted = False
    fault_only = value['services']['verify']['environment'].get('FLEET_FACTORY_FAULT_ONLY') == '1'
    while True:
        state = inspect(verifier)
        if not state['Running']:
            private_json(artifacts / 'verifier-state.json', state)
            subprocess.run(['docker', 'logs', verifier], check=True)
            if state['ExitCode'] != 0:
                raise RuntimeError(f'Fleet verifier failed: {state["ExitCode"]}')
            if fault_only and not faulted:
                raise RuntimeError('Native adapter fault checkpoint was never exercised')
            if not fault_only and not restarted:
                raise RuntimeError('Fleet restart checkpoint was never exercised')
            return
        if time.monotonic() >= deadline:
            private_json(artifacts / 'verifier-state.json', {**state, 'DeadlineExceeded': True})
            raise TimeoutError('Fleet factory acceptance exceeded its explicit wall deadline')
        request = artifacts / 'fleet-restart.request'
        if request.exists() and not restarted:
            worker = subprocess.check_output(['docker', *compose, 'ps', '-q', 'fleet-worker'], text=True).strip()
            before = inspect(worker)['StartedAt']
            work(*compose, 'restart', 'fleet-worker')
            after = inspect(worker)
            if not after['Running'] or after['StartedAt'] == before:
                raise RuntimeError('Fleet worker did not restart')
            private_json(request.with_suffix('.ack'), {'before': before, 'after': after['StartedAt'], 'running': True})
            restarted = True
        loss = artifacts / 'native-adapter-loss.request'
        if loss.exists() and not faulted:
            work(*compose, 'kill', '--signal', 'SIGKILL', 'storage-adapter')
            private_json(loss.with_suffix('.ack'), {'service': 'storage-adapter', 'signal': 'SIGKILL'})
            faulted = True
        time.sleep(.2)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--control', nargs=2, metavar=('MANIFEST', 'ARTIFACTS'))
    args = parser.parse_args()
    if args.control:
        control(*(Path(value).resolve() for value in args.control))
        return
    suffix = uuid4().hex[:10]
    manifest = ROOT / 'deploy/generated' / f'fleet-factory-{suffix}.json'
    artifacts = ROOT / '.superpowers/sdd/simu75-fleet-factory' / suffix
    artifacts.mkdir(parents=True, exist_ok=True)
    generate(manifest, artifacts, os.getenv('FLEET_FACTORY_WITH_TWIN', '0') == '1')
    print(manifest)


if __name__ == '__main__':
    main()

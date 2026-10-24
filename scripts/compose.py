#!/usr/bin/env python3
"""Render independent Compose manifests; JSON is valid Compose YAML.

No cross-application runtime service is shared. Credentials are per-app,
randomly generated once into git-ignored files. Never print the secrets.
"""
import argparse
import json
from pathlib import Path
import secrets

APPS = ['manufacturing', 'storage', 'logistics', 'shipping', 'twin']
ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'deploy' / 'generated'


def credentials(app):
    path = OUT / f'{app}.secrets.json'
    result=json.loads(path.read_text()) if path.exists() else {}
    for name in ('database','broker','application','employee','observer'):
        result.setdefault(name,secrets.token_hex(24))
    path.write_text(json.dumps(result))
    path.chmod(0o600)
    return result


def stack(app, suite=False):
    secret = credentials(app)
    prefix = app + '-'
    service = lambda role: prefix + role
    database_url = f"postgresql://{app}:{secret['database']}@{service('db')}:5432/{app}"
    amqp_url = f"amqp://{app}:{secret['broker']}@{service('broker')}:5672/{app}"
    env = {
        'SIMULATOR': app, 'CLOCK_MODE': 'standalone', 'DATABASE_URL': database_url,
        'AMQP_URL': amqp_url, 'APP_USERNAME': app + '-operator', 'APP_PASSWORD': secret['application'],
        'HANDOFF_QUANTUM': '1', 'AUTONOMOUS_SAMPLE': 'true',
    }
    # External URLs override local container addresses without rebuilding images.
    # Compose does not publish database or broker ports by default.
    env = {key: '${' + app.upper() + '_' + key + ':-' + value + '}' for key, value in env.items()}
    env['APP_IDENTITIES']=json.dumps([
        {'username':app+'-employee','password':secret['employee'],'role':'employee'},
        {'username':app+'-observer','password':secret['observer'],'role':'service','scopes':['status:read']},
    ],separators=(',',':'))
    if app == 'twin':
        source_list = []
        if suite:
            for peer in APPS[:-1]:
                peer_secret = credentials(peer)
                source_list.append({'name': peer, 'url': f'http://{peer}-api:8000', 'username': peer+'-observer', 'password': peer_secret['observer']})
        env['TWIN_SOURCES'] = '${TWIN_SOURCES:-' + json.dumps(source_list, separators=(',', ':')) + '}'
    services = {
        service('db'): {'image': 'postgres:17-alpine', 'environment': {'POSTGRES_USER': app, 'POSTGRES_PASSWORD': secret['database'], 'POSTGRES_DB': app}, 'volumes': [service('data') + ':/var/lib/postgresql/data'], 'healthcheck': {'test': ['CMD-SHELL', f'pg_isready -h 127.0.0.1 -U {app} -d {app}'], 'interval': '2s', 'timeout': '3s', 'retries': 40}},
        service('broker'): {'image': 'rabbitmq:4.1-alpine', 'environment': {'RABBITMQ_DEFAULT_USER': app, 'RABBITMQ_DEFAULT_PASS': secret['broker'], 'RABBITMQ_DEFAULT_VHOST': app}, 'volumes': [service('broker-data') + ':/var/lib/rabbitmq'], 'healthcheck': {'test': ['CMD', 'nc', '-z', '-w', '2', '127.0.0.1', '5672'], 'interval': '5s', 'timeout': '3s', 'start_period': '45s', 'retries': 30}},
    }
    depends = {service('db'): {'condition': 'service_healthy'}, service('broker'): {'condition': 'service_healthy'}}
    roles = ['api', 'projection'] if app == 'twin' else ['api', 'worker', 'controller']
    for role in roles:
        services[service(role)] = {
            'build': {'context': str(ROOT), 'dockerfile': 'Dockerfile'}, 'image': 'logistics-simulator:bootstrap',
            'environment': env.copy(), 'depends_on': depends,
            'init': True, 'restart': 'unless-stopped',
        }
        if role != 'api':
            services[service(role)]['command'] = ['python', '-m', 'simulator.'+role]
    services[service('api')]['healthcheck'] = {
        'test': ['CMD', 'python', '-c', "import urllib.request; urllib.request.urlopen('http://localhost:8000/api/health/ready',timeout=6)"],
        'interval': '5s', 'timeout': '8s', 'retries': 30,
    }
    services[service('web')] = {
        'build': {'context': str(ROOT), 'dockerfile': 'apps/web/Dockerfile', 'args': {'SIMULATOR': app}},
        'image': 'logistics-simulator-'+app+'-web:bootstrap',
        'environment': {'API_UPSTREAM': '${'+app.upper()+'_API_UPSTREAM:-http://'+service('api')+':8000}'},
        'ports': [f'127.0.0.1:{8181+APPS.index(app)}:8080'],
        'depends_on': {service('api'): {'condition': 'service_healthy'}},
        'healthcheck': {'test': ['CMD', 'wget', '-q', '--spider', 'http://127.0.0.1:8080/api/health/live'], 'interval': '5s', 'timeout': '5s', 'retries': 20},
    }
    for value in services.values():
        value.setdefault('restart', 'unless-stopped')
    return {'services': services, 'volumes': {service('data'): {}, service('broker-data'): {}}}


def generate():
    OUT.mkdir(parents=True, exist_ok=True)
    for app in APPS:
        (OUT / f'{app}.json').write_text(json.dumps({'name': 'simu-'+app, **stack(app)}, indent=2))
        (OUT / f'{app}.json').chmod(0o600)
    suite = {'name': 'simu-suite', 'services': {}, 'volumes': {}}
    for app in APPS:
        part = stack(app, suite=True)
        suite['services'].update(part['services'])
        suite['volumes'].update(part['volumes'])
    (OUT / 'suite.json').write_text(json.dumps(suite, indent=2))
    (OUT / 'suite.json').chmod(0o600)
    print('Generated standalone and suite manifests in deploy/generated/ (credentials retained).')


if __name__ == '__main__':
    generate()

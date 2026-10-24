"""Generate an isolated shipping/native HELICS controlled-peer acceptance stack."""
import base64
import json
import os
from pathlib import Path
import secrets
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]


def main():
    out = ROOT / 'deploy/generated'
    out.mkdir(parents=True, exist_ok=True)
    identity = {
        'run_id': str(uuid4()), 'epoch': str(uuid4()),
        'federation_id': 'simu5-shipping-controlled-peer',
        'password': secrets.token_hex(20), 'adapter_token': secrets.token_hex(32),
        'app_key': 'base64:' + base64.b64encode(secrets.token_bytes(32)).decode(),
    }
    context = {key: identity[value] for key, value in (
        ('FEDERATION_ID', 'federation_id'), ('FEDERATION_RUN_ID', 'run_id'), ('FEDERATION_EPOCH', 'epoch'))}
    outputs = [{'endpoint': 'shipping-peer/events', 'destination': destination, 'boundary': boundary}
               for destination, boundary in [('storage', 'requests'), ('manufacturing', 'demand'), ('logistics', 'transport')]]
    peers = {'orders': {'source': 'external-orders', 'endpoint': 'shipping-peer/events'},
             'goods': [{'source': source, 'endpoint': 'shipping-peer/events'} for source in ('storage', 'manufacturing')],
             'carrier': {'source': 'logistics', 'endpoint': 'shipping-peer/events'}}
    env = {**context, 'SIMULATOR': 'shipping', 'CLOCK_MODE': 'helics',
           'DATABASE_URL': f"postgresql://shipping:{identity['password']}@shipping-db:5432/shipping",
           'AMQP_URL': f"amqp://shipping:{identity['password']}@shipping-broker:5672/%2f",
           'APP_USERNAME': 'shipping-operator', 'APP_PASSWORD': identity['password'],
           'APP_KEY': identity['app_key'], 'APP_ENV': 'testing', 'APP_DEBUG': 'false',
           'APP_URL': 'http://shipping-api:8000', 'AUTONOMOUS_SAMPLE': 'false', 'AUTONOMOUS_SHIPPING': 'false',
           'BOUNDARY_PROVIDERS': json.dumps(dict.fromkeys(('orders', 'goods', 'carrier'), 'helics')),
           'HELICS_PEERS': json.dumps(peers), 'HELICS_OUTPUTS': json.dumps(outputs),
           'HELICS_ADAPTER_URL': 'http://shipping-adapter:8010', 'HELICS_ADAPTER_TOKEN': identity['adapter_token'],
           'HELICS_TIMEOUT_SECONDS': '600'}
    adapter_image = 'logistics-simulator:simu5-shipping-adapter'
    def config(name, rogue=False):
        endpoints = [{'name': name + '/events', 'global': True, 'type': 'application/json'}]
        if rogue:
            endpoints.append({'name': 'shipping-rogue/events', 'global': True, 'type': 'application/json'})
        return json.dumps({'name': name, 'coreType': 'tcp_ss', 'coreInit': '--federates=1',
                           'broker': 'tcp://shipping-helics-broker:24900', 'period': 1.0, 'timeDelta': 1.0,
                           'endpoints': endpoints, 'publications': [{'key': 'completed_items', 'type': 'double', 'unit': 'item'}]})
    services = {
        'shipping-db': {'image': 'postgres:16.15-alpine',
                        'environment': {'POSTGRES_USER': 'shipping', 'POSTGRES_DB': 'shipping', 'POSTGRES_PASSWORD': identity['password']},
                        'healthcheck': {'test': ['CMD-SHELL', 'pg_isready -U shipping'], 'interval': '2s', 'timeout': '3s', 'retries': 30},
                        'volumes': ['shipping-data:/var/lib/postgresql/data']},
        'shipping-broker': {'image': 'rabbitmq:4.3.6-alpine', 'user': 'rabbitmq',
                            'environment': {'RABBITMQ_DEFAULT_USER': 'shipping', 'RABBITMQ_DEFAULT_PASS': identity['password'],
                                            'RABBITMQ_SERVER_ADDITIONAL_ERL_ARGS': '+S 2:2 +A 4'},
                            'healthcheck': {'test': ['CMD', 'nc', '-z', '-w', '2', '127.0.0.1', '5672'],
                                            'interval': '3s', 'timeout': '3s', 'start_period': '45s', 'retries': 30}},
        'shipping-helics-broker': {'image': adapter_image,
                                  'entrypoint': ['helics_broker', '-t', 'tcp_ss', '-f2', '--port=24900', '--ipv4', '--loglevel=warning']},
        'shipping-adapter': {'image': adapter_image,
                             'environment': {**context, 'SIMULATOR': 'shipping', 'HELICS_CONFIG': config('shipping'),
                                             'HELICS_ADAPTER_TOKEN': identity['adapter_token'], 'HELICS_OUTPUTS': json.dumps(outputs),
                                             'ADAPTER_JOURNAL': '/journal/adapter.sqlite'},
                             'volumes': ['shipping-adapter-journal:/journal'],
                             'depends_on': {'shipping-helics-broker': {'condition': 'service_started'}}},
        'shipping-peer': {'image': adapter_image, 'user': '0:0',
                          'entrypoint': ['python', '/app/scripts/shipping_peer.py'],
                          'volumes': [str(ROOT / 'scripts') + ':/app/scripts:ro', 'shipping-peer-control:/control'],
                          'environment': {**context, 'HELICS_CONFIG': config('shipping-peer', True)},
                          'depends_on': {'shipping-helics-broker': {'condition': 'service_started'}}},
        'shipping-verify': {'image': 'logistics-simulator:bootstrap', 'profiles': ['test'], 'user': '0:0',
                            'working_dir': '/app', 'entrypoint': ['python', 'scripts/shipping_connected_verify.py'],
                            'environment': env,
                            'volumes': [str(ROOT / 'scripts') + ':/app/scripts:ro', 'shipping-peer-control:/control']},
    }
    for role in ('api', 'worker', 'controller'):
        services['shipping-' + role] = {
            'image': os.environ.get('SHIPPING_CONNECTED_IMAGE', 'logistics-simulator:simu5-shipping'),
            'environment': {**env, 'ROLE': role},
            'depends_on': {'shipping-db': {'condition': 'service_healthy'},
                           'shipping-broker': {'condition': 'service_healthy'},
                           'shipping-adapter': {'condition': 'service_started'}}}
    manifest = {'name': 'simu5-shipping-connected', 'services': services,
                'volumes': {name: {} for name in ('shipping-data', 'shipping-adapter-journal', 'shipping-peer-control')}}
    path = out / 'simu5-shipping-connected.json'
    path.write_text(json.dumps(manifest, indent=2))
    path.chmod(0o600)
    print(path)


if __name__ == '__main__':
    main()

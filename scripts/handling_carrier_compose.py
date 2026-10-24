"""Disposable real PHP/Go HELICS pair; no controlled business peer."""
import json
from pathlib import Path
from uuid import uuid4
from stacks_compose import generate, ROOT


def main():
    value = generate(['shipping', 'logistics'], write=False)
    value['name'] = 'simu-handling-carrier-' + uuid4().hex[:8]
    services = value['services']
    run, epoch = str(uuid4()), str(uuid4())
    federation = 'handling-carrier-native'
    token = uuid4().hex + uuid4().hex
    image = 'logistics-simulator:handling-carrier-adapter'
    services.pop('browser-check', None)
    services.pop('logistics-web', None)
    services['handoff-helics-broker'] = {
        'image': image, 'entrypoint': ['helics_broker', '-t', 'tcp_ss', '-f2', '--port=24900', '--ipv4', '--loglevel=warning'],
        'healthcheck': {'test': ['CMD', 'python', '-c', "import socket; socket.create_connection(('127.0.0.1',24900),2).close()"], 'interval': '2s', 'timeout': '3s', 'retries': 30}}
    credentials = {}
    for app in ('shipping', 'logistics'):
        other = 'logistics' if app == 'shipping' else 'shipping'
        boundary = 'transport' if app == 'shipping' else 'carrier'
        outputs = [{'endpoint': other + '/events', 'destination': other, 'boundary': boundary}]
        providers = {'orders': 'synthetic', 'goods': 'synthetic', 'carrier': 'helics'} if app == 'shipping' else {'transport': 'helics', 'destinations': 'synthetic'}
        peers = {'carrier' if app == 'shipping' else 'transport': {'source': other, 'endpoint': other + '/events'}}
        context = {'FEDERATION_ID': federation, 'FEDERATION_RUN_ID': run, 'FEDERATION_EPOCH': epoch}
        for role in ('api', 'worker', 'controller'):
            service = services[app + '-' + role]
            service['image'] = 'logistics-simulator:handling-carrier-' + app
            env = service['environment']
            env.update(context, CLOCK_MODE='helics', BOUNDARY_PROVIDERS=json.dumps(providers), HELICS_PEERS=json.dumps(peers), HELICS_OUTPUTS=json.dumps(outputs),
                       HELICS_ADAPTER_URL='http://' + app + '-adapter:8010', HELICS_ADAPTER_TOKEN=token, HELICS_TIMEOUT_SECONDS='180',
                       AUTONOMOUS_SAMPLE='false' if app == 'shipping' else 'true', AUTONOMOUS_SHIPPING='false')
            if role == 'api':
                credentials[app] = {'username': env['APP_USERNAME'], 'password': env['APP_PASSWORD'], 'identities': json.loads(env['APP_IDENTITIES'])}
            if role == 'controller':
                service['depends_on'][app + '-adapter'] = {'condition': 'service_started'}
        config = {'name': app, 'coreType': 'tcp_ss', 'coreInit': '--federates=1', 'broker': 'tcp://handoff-helics-broker:24900', 'period': 1.0, 'timeDelta': 1.0,
                  'endpoints': [{'name': app + '/events', 'global': True, 'type': 'application/json'}], 'publications': [{'key': 'completed_items', 'type': 'double', 'unit': 'item'}]}
        services[app + '-adapter'] = {'image': image, 'environment': {**context, 'SIMULATOR': app, 'HELICS_CONFIG': json.dumps(config), 'HELICS_OUTPUTS': json.dumps(outputs),
                'HELICS_ADAPTER_TOKEN': token, 'ADAPTER_JOURNAL': '/journal/adapter.sqlite'}, 'volumes': [app + '-journal:/journal'],
                'depends_on': {'handoff-helics-broker': {'condition': 'service_healthy'}}, 'restart': 'no'}
        value['volumes'][app + '-journal'] = {}
        services.pop(app + '-verify', None)
    services['verify'] = {'image': 'logistics-simulator:bootstrap', 'profiles': ['test'], 'working_dir': '/app',
                          'command': ['python', 'scripts/handling_carrier_verify.py'], 'environment': {'CARRIER_IDENTITIES': json.dumps(credentials), 'EXPECTED_RUN_ID': run, 'EXPECTED_EPOCH': epoch, 'CARRIER_TEST_PROJECT':value['name'],'CARRIER_EVIDENCE_DIR':'/evidence'},'user':'0:0',
                          'volumes': [str(ROOT / 'scripts') + ':/app/scripts:ro', str(ROOT / 'contracts') + ':/app/contracts:ro',str(ROOT / '.superpowers/sdd/2026-10-25-simu64-implementation/carrier-native')+':/evidence']}
    path = ROOT / 'deploy/generated/handling-carrier.json'
    path.write_text(json.dumps(value, indent=2)); path.chmod(0o600)
    print(path)


if __name__ == '__main__':
    main()

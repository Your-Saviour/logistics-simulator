#!/usr/bin/env python3
"""Render the optional connected suite into its own project/volume namespace."""
import json
from pathlib import Path
import sys
from uuid import uuid4

from compose import APPS, OUT, ROOT, stack
sys.path.insert(0,str(ROOT/'src'))
from simulator.federation_config import config, peers_for, PROVIDERS, ROUTES


def generate():
    identity_path=OUT/'federation.identity.json'
    if identity_path.exists():
        identity=json.loads(identity_path.read_text())
    else:
        identity={'run_id':str(uuid4()),'epoch':str(uuid4()),'federation_id':'bootstrap-example-v1'}
        identity_path.write_text(json.dumps(identity))
    result={'name':'simu-federation','services':{},'volumes':{}}
    for app in APPS:
        part=stack(app,suite=True)
        for name,service in part['services'].items():
            env=service.get('environment',{})
            if 'CLOCK_MODE' in env and app!='twin':
                destination,boundary=ROUTES[app]
                env.update({'CLOCK_MODE':'helics','FEDERATION_ID':identity['federation_id'],
                            'FEDERATION_RUN_ID':identity['run_id'],'FEDERATION_EPOCH':identity['epoch'],
                            'BOUNDARY_PROVIDERS':json.dumps(PROVIDERS[app]),
                            'HELICS_CONFIG':config(app,'tcp://helics-broker:24900'),
                            'HELICS_PEERS':json.dumps(peers_for(app)),
                            'HELICS_OUTPUTS':json.dumps([{'endpoint':destination+'/events','destination':destination,'boundary':boundary}])})
                if name.endswith('-controller'):
                    service['depends_on']['helics-broker']={'condition':'service_healthy'}
                    service['depends_on']['external-power']={'condition':'service_started'}
                    # A connected process is never automatically restarted into
                    # a live federation after losing its native time state.
                    service['restart']='no'
        result['services'].update(part['services'])
        result['volumes'].update(part['volumes'])
    result['services']['helics-broker']={'image':'logistics-simulator:bootstrap','command':['helics_broker','-t','tcp_ss','-f5','--port=24900','--ipv4','--loglevel=warning'],'restart':'no','healthcheck':{'test':['CMD','python','-c',"import socket; socket.create_connection(('127.0.0.1',24900),2).close()"],'interval':'2s','timeout':'3s','retries':30}}
    result['services']['external-power']={'image':'logistics-simulator:bootstrap','command':['python','examples/helics/external_peer.py'],'environment':{'HELICS_BROKER':'tcp://helics-broker:24900'},'depends_on':{'helics-broker':{'condition':'service_healthy'}},'restart':'no'}
    path=OUT/'federation.json'
    path.write_text(json.dumps(result,indent=2))
    path.chmod(0o600)
    print('Generated connected federation manifest; identity retained.')


if __name__=='__main__':
    generate()

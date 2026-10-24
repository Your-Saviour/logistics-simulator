#!/usr/bin/env python3
"""Disposable mixed-stack verification manifests, never CyberLab packaging.

Generation/orchestration can run on the host; service checks run in containers.
No host ports or existing deployment volumes are referenced.
"""
import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import secrets
import sys
from uuid import uuid4

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from simulator.federation_config import config,peers_for,PROVIDERS,ROUTES
APPS=('storage','manufacturing','logistics','shipping','twin')
BUILDS={
 'storage':('apps/storage','Dockerfile','apps/storage/frontend','Dockerfile'),
 'manufacturing':('.','apps/manufacturing/backend/Dockerfile','.','apps/manufacturing/frontend/Dockerfile'),
 'logistics':('apps/logistics/backend','Dockerfile','apps/logistics/frontend','Dockerfile'),
 'shipping':('.','apps/shipping/Dockerfile',None,None),
 'twin':('.','apps/twin/Dockerfile','.','apps/twin/web/Dockerfile'),
}


def generate(apps,connected=False,write=True):
    if connected and set(apps)!=set(APPS): raise ValueError('Mixed federation verification requires all five migrated images')
    out=ROOT/'deploy'/'generated';out.mkdir(parents=True,exist_ok=True)
    label='mixed' if connected else (apps[0] if len(apps)==1 else 'standalone-suite')
    prefix='migration-'+label
    identity_path=out/(prefix+'.identity.json')
    if identity_path.exists(): identity=json.loads(identity_path.read_text())
    else:
        identity={'run_id':str(uuid4()),'epoch':str(uuid4()),'federation_id':'mixed-stack-reference',
                  'passwords':{app:secrets.token_hex(20) for app in APPS},'adapter_token':secrets.token_hex(32)}
        identity_path.write_text(json.dumps(identity));identity_path.chmod(0o600)
    if 'shipping_key' not in identity:
        identity['shipping_key']='base64:'+base64.b64encode(secrets.token_bytes(32)).decode()
        identity_path.write_text(json.dumps(identity));identity_path.chmod(0o600)
    checkout=hashlib.sha256(str(ROOT).encode()).hexdigest()[:8]
    result={'name':'simu-'+prefix+'-'+checkout,'services':{},'volumes':{}}
    services=result['services']
    for app in apps:
        password=identity['passwords'][app]
        accounts=[{'username':app+'-employee','password':password+'-employee','role':'employee'},
                  {'username':app+'-observer','password':password+'-observer','role':'service','scopes':['status:read']}]
        env={'SIMULATOR':app,'ROLE':'api','CLOCK_MODE':'standalone',
             'DATABASE_URL':f'postgresql://{app}:{password}@{app}-db:5432/{app}',
             'AMQP_URL':f'amqp://{app}:{password}@{app}-broker:5672/%2f',
             'APP_USERNAME':app+'-operator','APP_PASSWORD':password,'APP_IDENTITIES':json.dumps(accounts),
             'AUTONOMOUS_SAMPLE':'false','JAVA_TOOL_OPTIONS':'-Xmx256m -XX:ActiveProcessorCount=2','GOMAXPROCS':'2','DOTNET_PROCESSOR_COUNT':'2'}
        if app=='shipping':
            env.update(APP_KEY=identity['shipping_key'],APP_ENV='testing',APP_DEBUG='false',APP_URL='http://shipping-api:8000')
        services[app+'-db']={'image':'postgres:16.15-alpine',
            'environment':{'POSTGRES_USER':app,'POSTGRES_PASSWORD':password,'POSTGRES_DB':app},
            'healthcheck':{'test':['CMD-SHELL','pg_isready -U '+app],'interval':'2s','timeout':'3s','retries':30},
            'volumes':[app+'-data:/var/lib/postgresql/data']}
        services[app+'-broker']={'image':'rabbitmq:4.3.6-alpine','user':'rabbitmq',
            'environment':{'RABBITMQ_DEFAULT_USER':app,'RABBITMQ_DEFAULT_PASS':password,'RABBITMQ_SERVER_ADDITIONAL_ERL_ARGS':'+S 2:2 +A 4'},
            'healthcheck':{'test':['CMD','nc','-z','-w','2','127.0.0.1','5672'],'interval':'5s','timeout':'3s','start_period':'45s','retries':30}}
        result['volumes'][app+'-data']={}
        context,dockerfile,web_context,web_dockerfile=BUILDS[app]
        dependencies={app+'-db':{'condition':'service_healthy'},app+'-broker':{'condition':'service_healthy'}}
        if connected and app!='twin':
            destination,boundary=ROUTES[app]
            env.update(CLOCK_MODE='helics',FEDERATION_ID=identity['federation_id'],FEDERATION_RUN_ID=identity['run_id'],
                FEDERATION_EPOCH=identity['epoch'],BOUNDARY_PROVIDERS=json.dumps(PROVIDERS[app]),HELICS_PEERS=json.dumps(peers_for(app)),
                HELICS_OUTPUTS=json.dumps([{'endpoint':destination+'/events','destination':destination,'boundary':boundary}]),
                HELICS_ADAPTER_URL=f'http://{app}-adapter:8010',HELICS_ADAPTER_TOKEN=identity['adapter_token'])
            env['HELICS_TIMEOUT_SECONDS']='180'
            adapter_env={key:env[key] for key in ('SIMULATOR','FEDERATION_ID','FEDERATION_RUN_ID','FEDERATION_EPOCH','HELICS_OUTPUTS','HELICS_ADAPTER_TOKEN')}
            adapter_env.update(HELICS_CONFIG=config(app,'tcp://helics-broker:24900'),ADAPTER_JOURNAL='/journal/adapter.sqlite')
            services[app+'-adapter']={'image':'logistics-simulator:adapter',
                'build':{'context':str(ROOT),'dockerfile':'apps/adapter/Dockerfile'},
                'environment':adapter_env,'volumes':[app+'-adapter-journal:/journal'],
                'depends_on':{'helics-broker':{'condition':'service_healthy'}},'restart':'no'}
            result['volumes'][app+'-adapter-journal']={}
        if app=='twin':
            env['TWIN_SOURCES']=json.dumps([{'name':source,'url':f'http://{source}-api:8000','username':source+'-observer',
                'password':identity['passwords'][source]+'-observer'} for source in apps if source!='twin'])
        for role in (('api','projection') if app=='twin' else ('api','worker','controller')):
            own_deps=dict(dependencies)
            if connected and app!='twin' and role=='controller':
                own_deps[app+'-adapter']={'condition':'service_started'}
            service={'image':'logistics-simulator:'+app+'-migrated',
                     'build':{'context':str(ROOT/context),'dockerfile':dockerfile},
                     'environment':{**env,'ROLE':role},'depends_on':own_deps,'restart':'no'}
            services[app+'-'+role]=service
        if web_context is not None and not connected:
            services[app+'-web']={'image':'logistics-simulator:'+app+'-web-migrated',
                'build':{'context':str(ROOT/web_context),'dockerfile':web_dockerfile},
                'environment':{'API_UPSTREAM':('http://' if app=='twin' else '')+app+'-api:8000'},
                'depends_on':[app+'-api']}
        services[app+'-verify']={'image':'logistics-simulator:bootstrap','profiles':['test'],
            'command':['python','scripts/stack_acceptance.py','--app',app,'--url','http://'+app+'-api:8000'],
            'environment':env,'working_dir':'/app',
            'volumes':[str(ROOT/'scripts')+':/app/scripts:ro',str(ROOT/'contracts')+':/app/contracts:ro']}
    artifacts=ROOT/'.superpowers'/'sdd'/'simu-framework-migration'/'browser-artifacts'
    artifacts.mkdir(parents=True,exist_ok=True)
    browser_apps=[]
    for app in apps:
        password=identity['passwords'][app]
        url=f'http://{app}-api:8000' if app=='shipping' else f'http://{app}-web:'+('8080' if app=='twin' else '80')
        browser_apps.append({'name':app,'url':url,'username':app+'-operator','password':password,
                             'employee':app+'-employee','employeePassword':password+'-employee'})
    services['browser-check']={'image':os.environ.get('BROWSER_CHECK_IMAGE','logistics-simulator:browser-check'),
        'build':{'context':str(ROOT),'dockerfile':'apps/browser-check/Dockerfile'},'profiles':['test'],
        'environment':{'STACK_APPS':json.dumps(browser_apps)},'shm_size':'512m','volumes':[str(artifacts)+':/artifacts']}
    if connected:
        services['helics-broker']={'image':'logistics-simulator:adapter',
            'entrypoint':['helics_broker','-t','tcp_ss','-f5','--port=24900','--ipv4','--loglevel=warning'],
            'healthcheck':{'test':['CMD','python','-c',"import socket; socket.create_connection(('127.0.0.1',24900),2).close()"],
                           'interval':'2s','timeout':'3s','retries':30},'restart':'no'}
        services['external-power']={'image':'logistics-simulator:adapter','entrypoint':['python','examples/helics/external_peer.py'],
            'environment':{'HELICS_BROKER':'tcp://helics-broker:24900','PEER_GATE_FILE':'/control/release'},
            'volumes':['power-gate:/control'],'depends_on':{'helics-broker':{'condition':'service_healthy'}},'restart':'no'}
        result['volumes']['power-gate']={}
        # The verifier controls when the deliberate delayed power peer requests time.
        services['federation-verify']={'image':'logistics-simulator:bootstrap','profiles':['test'],
            'command':['python','scripts/mixed_federation_check.py'],
            'environment':{'STACK_IDENTITIES':json.dumps(identity)},'working_dir':'/app','user':'0:0',
            'volumes':[str(ROOT/'scripts')+':/app/scripts:ro','power-gate:/control']}
    if write:
        path=out/(prefix+'.json');path.write_text(json.dumps(result,indent=2));path.chmod(0o600)
        print(path)
    return result

if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--app',choices=[*APPS,'all'],default='all')
    parser.add_argument('--connected',action='store_true')
    args=parser.parse_args()
    generate(list(APPS) if args.app=='all' else [args.app],args.connected)

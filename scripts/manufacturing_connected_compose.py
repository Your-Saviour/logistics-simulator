"""Disposable manufacturing + native storage/power reference peer; no other app."""
import json
from uuid import uuid4
from stacks_compose import generate,ROOT


def main():
    manifest=generate(['manufacturing'],write=False);manifest['name']='simu3-manufacturing-connected'
    identity=json.loads((ROOT/'deploy/generated/migration-manufacturing.identity.json').read_text())
    context={'FEDERATION_ID':'manufacturing-domain-reference','FEDERATION_RUN_ID':str(uuid4()),'FEDERATION_EPOCH':str(uuid4())}
    routes=[{'endpoint':'storage/events','destination':'storage','boundary':boundary} for boundary in ('requests','supply')]
    def config(name):
        cfg={'name':name,'coreType':'tcp_ss','coreInit':'--federates=1','broker':'tcp://factory-broker:24900','period':1.0,'timeDelta':1.0,
             'endpoints':[{'name':name+'/events','global':True,'type':'application/json'}]}
        if name=='manufacturing':
            cfg.update(publications=[{'key':'completed_items','type':'double','unit':'item'}],subscriptions=[{'key':'external-power/available_power_kw','type':'double','unit':'kW'}])
        else:
            cfg['publications']=[{'key':'external-power/available_power_kw','global':True,'type':'double','unit':'kW'}]
        return json.dumps(cfg)
    services=manifest['services'];peer={'source':'storage','endpoint':'storage/events'}
    for role in ('api','worker','controller'):
        services['manufacturing-'+role]['environment'].update(context,CLOCK_MODE='helics',AUTONOMOUS_PRODUCTION='true',
            BOUNDARY_PROVIDERS=json.dumps({'materials':'helics','demand':'helics','power':'helics'}),
            HELICS_PEERS=json.dumps({'materials':peer,'demand':peer,'power':{**peer,'value_target':'external-power/available_power_kw'}}),
            HELICS_OUTPUTS=json.dumps(routes),HELICS_ADAPTER_URL='http://manufacturing-adapter:8010',HELICS_ADAPTER_TOKEN=identity['adapter_token'],HELICS_TIMEOUT_SECONDS='120')
    services['manufacturing-adapter']={'image':'logistics-simulator:adapter','environment':{**context,'SIMULATOR':'manufacturing','HELICS_CONFIG':config('manufacturing'),'HELICS_OUTPUTS':json.dumps(routes),'HELICS_ADAPTER_TOKEN':identity['adapter_token']},'depends_on':['factory-broker']}
    services['factory-broker']={'image':'logistics-simulator:adapter','entrypoint':['helics_broker','-t','tcp_ss','-f2','--port=24900','--ipv4','--loglevel=warning']}
    services['factory-peer']={'user':'0:0','image':'logistics-simulator:adapter','entrypoint':['python','/app/scripts/manufacturing_peer.py'],
        'environment':{**context,'HELICS_CONFIG':config('storage')},'volumes':[str(ROOT/'scripts')+':/app/scripts:ro','factory-evidence:/evidence'], 'depends_on':['factory-broker']}
    manifest['volumes']['factory-evidence']={}
    services['manufacturing-verify'].update(command=['python','scripts/manufacturing_connected_verify.py'],volumes=[str(ROOT/'scripts')+':/app/scripts:ro','factory-evidence:/evidence'])
    path=ROOT/'deploy/generated/manufacturing-v1-connected.json';path.write_text(json.dumps(manifest,indent=2));path.chmod(0o600);print(path)


if __name__=='__main__': main()

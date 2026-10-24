"""Disposable Logistics + native HELICS reference peer; no other department required."""
import json
import os
from stacks_compose import generate, ROOT

def main():
    manifest=generate(['logistics'],write=False);identity=json.loads((ROOT/'deploy/generated/migration-logistics.identity.json').read_text())
    services=manifest['services'];manifest['name']='simu-logistics-v1-connected-check'
    loss=os.environ.get('LOGISTICS_PEER_LOSS','false')=='true'
    context={'FEDERATION_ID':'logistics-domain-reference','FEDERATION_RUN_ID':identity['run_id'],'FEDERATION_EPOCH':identity['epoch']}
    def config(name):
        return json.dumps({'name':name,'coreType':'tcp_ss','coreInit':'--federates=1','broker':'tcp://transport-broker:24900','period':1.0,'timeDelta':1.0,
            'endpoints':[{'name':name+'/events','global':True,'type':'application/json'}], 'publications':[{'key':'completed_items','type':'double','unit':'item'}]})
    outputs=[{'endpoint':'transport-peer/events','destination':'transport-peer','boundary':'transport'},
             {'endpoint':'transport-peer/events','destination':'storage','boundary':'requests'}]
    for role in ('api','worker','controller'):
        services['logistics-'+role]['environment'].update(context,CLOCK_MODE='helics',AUTONOMOUS_SAMPLE='true',
            BOUNDARY_PROVIDERS=json.dumps({'transport':'helics','destinations':'helics'}),
            HELICS_PEERS=json.dumps({'transport':{'source':'storage','endpoint':'transport-peer/events'},'destinations':{'source':'shipping','endpoint':'transport-peer/events'}}),
            HELICS_OUTPUTS=json.dumps(outputs),HELICS_ADAPTER_URL='http://logistics-adapter:8010',HELICS_ADAPTER_TOKEN=identity['adapter_token'],HELICS_TIMEOUT_SECONDS='8' if loss else '120')
    services['logistics-adapter']={'image':'logistics-simulator:logistics-v1-adapter','environment':{**context,'SIMULATOR':'logistics',
        'HELICS_CONFIG':config('logistics'),'HELICS_ADAPTER_TOKEN':identity['adapter_token'],'HELICS_OUTPUTS':json.dumps(outputs)},'depends_on':['transport-broker']}
    services['transport-peer']={'image':'logistics-simulator:logistics-v1-adapter','entrypoint':['python','/app/scripts/logistics_peer.py'],
        'volumes':[str(ROOT/'scripts')+':/app/scripts:ro'],'environment':{**context,'HELICS_CONFIG':config('transport-peer'),'LOGISTICS_PEER_LOSS':str(loss).lower()},'depends_on':['transport-broker']}
    services['transport-broker']={'image':'logistics-simulator:logistics-v1-adapter','entrypoint':['helics_broker','-t','tcp_ss','-f2','--port=24900','--ipv4','--loglevel=warning']}
    services['logistics-verify']['command']=['python','scripts/logistics_connected_verify.py']
    services['logistics-verify']['environment']['LOGISTICS_PEER_LOSS']=str(loss).lower()
    path=ROOT/'deploy/generated/logistics-v1-connected.json';path.write_text(json.dumps(manifest,indent=2));path.chmod(0o600);print(path)
if __name__=='__main__':main()

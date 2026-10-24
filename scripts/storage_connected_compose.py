"""Generate a disposable two-federate warehouse domain contract check."""
import json
from pathlib import Path
from stacks_compose import generate,ROOT


def main():
    manifest=generate(['storage'])
    identity=json.loads((ROOT/'deploy/generated/migration-storage.identity.json').read_text())
    services=manifest['services'];manifest['name']='simu-storage-v1-connected-check'
    federation='storage-domain-reference'
    def config(name):
        return json.dumps({'name':name,'coreType':'tcp_ss','coreInit':'--federates=1','broker':'tcp://warehouse-broker:24900',
                          'period':1.0,'timeDelta':1.0,'endpoints':[{'name':name+'/events','global':True,'type':'application/json'}],
                          'publications':[{'key':'completed_items','type':'double','unit':'item'}]})
    peer={'source':'warehouse-peer','endpoint':'warehouse-peer/events'}
    context={'FEDERATION_ID':federation,'FEDERATION_RUN_ID':identity['run_id'],'FEDERATION_EPOCH':identity['epoch']}
    for role in ('api','worker','controller'):
        env=services['storage-'+role]['environment']
        env.update(context,CLOCK_MODE='helics',AUTONOMOUS_WAREHOUSE='true',BOUNDARY_PROVIDERS=json.dumps({'supply':'helics','requests':'helics'}),
                   HELICS_PEERS=json.dumps({'supply':peer,'requests':peer}),HELICS_OUTPUTS=json.dumps([{'endpoint':'warehouse-peer/events','destination':'warehouse-peer','boundary':'warehouse'}]),
                   HELICS_ADAPTER_URL='http://storage-adapter:8010',HELICS_ADAPTER_TOKEN=identity['adapter_token'],HELICS_TIMEOUT_SECONDS='120')
    services['storage-adapter']={'image':'logistics-simulator:adapter','environment':{**context,'SIMULATOR':'storage',
        'HELICS_CONFIG':config('storage'),'HELICS_ADAPTER_TOKEN':identity['adapter_token'],
        'HELICS_OUTPUTS':json.dumps([{'endpoint':'warehouse-peer/events','destination':'warehouse-peer','boundary':'warehouse'}])},
        'depends_on':{'warehouse-broker':{'condition':'service_started'}}}
    services['warehouse-peer']={'image':'logistics-simulator:adapter','entrypoint':['python','/app/scripts/storage_peer.py'],
        'volumes':[str(ROOT/'scripts')+':/app/scripts:ro'],'environment':{**context,'HELICS_CONFIG':config('warehouse-peer')},
        'depends_on':{'warehouse-broker':{'condition':'service_started'}}}
    services['warehouse-broker']={'image':'logistics-simulator:adapter','entrypoint':['helics_broker','-t','tcp_ss','-f2','--port=24900','--ipv4','--loglevel=warning']}
    services['storage-verify']['command']=['python','scripts/storage_connected_verify.py']
    path=ROOT/'deploy/generated/storage-v1-connected.json';path.write_text(json.dumps(manifest,indent=2));path.chmod(0o600)
    print(path)


if __name__=='__main__':main()

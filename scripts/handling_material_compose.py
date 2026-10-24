"""Real C#/Java material custody, with two private adapters and no Twin/peer stub."""
import json
from uuid import uuid4
from stacks_compose import generate, ROOT


def main():
    value=generate(['storage','manufacturing'],write=False)
    value['name']='simu-handling-material-'+uuid4().hex[:8]
    services=value['services'];services.pop('browser-check',None)
    run,epoch=str(uuid4()),str(uuid4());federation='handling-material-native';token=uuid4().hex+uuid4().hex
    image='logistics-simulator:handling-material-adapter'
    services['material-helics-broker']={'image':image,'entrypoint':['helics_broker','-t','tcp_ss','-f2','--port=24900','--ipv4','--loglevel=warning'],
        'healthcheck':{'test':['CMD','python','-c',"import socket; socket.create_connection(('127.0.0.1',24900),2).close()"],'interval':'2s','timeout':'3s','retries':30}}
    identities={};databases={}
    for app in ('storage','manufacturing'):
        other='manufacturing' if app=='storage' else 'storage'
        outputs=[{'endpoint':other+'/events','destination':other,'boundary':'materials' if app=='storage' else 'requests'}]
        providers={'supply':'synthetic','requests':'helics'} if app=='storage' else {'materials':'helics','demand':'synthetic','power':'synthetic'}
        peers={'requests' if app=='storage' else 'materials':{'source':other,'endpoint':other+'/events'}}
        context={'FEDERATION_ID':federation,'FEDERATION_RUN_ID':run,'FEDERATION_EPOCH':epoch}
        for role in ('api','worker','controller'):
            service=services[app+'-'+role];service['image']='logistics-simulator:handling-material-'+app
            env=service['environment'];env.update(context,CLOCK_MODE='helics',BOUNDARY_PROVIDERS=json.dumps(providers),HELICS_PEERS=json.dumps(peers),HELICS_OUTPUTS=json.dumps(outputs),
                HELICS_ADAPTER_URL='http://'+app+'-adapter:8010',HELICS_ADAPTER_TOKEN=token,HELICS_TIMEOUT_SECONDS='180',AUTONOMOUS_SAMPLE='false',AUTONOMOUS_WAREHOUSE='false',AUTONOMOUS_PRODUCTION='false')
            if app=='manufacturing':env['SCENARIO']=json.dumps({'manufacturing':{'products':[{'sku':'PRODUCT','bom':{'COMPONENT':2},'duration_seconds':86400,'scrap_percent':0}], 'lines':[{'code':'LINE-1','capacity':1,'products':['PRODUCT']}]}})
            if role=='api':identities[app]={'username':env['APP_USERNAME'],'password':env['APP_PASSWORD']};databases[app]=env['DATABASE_URL']
            if role=='controller':service['depends_on'][app+'-adapter']={'condition':'service_started'}
        config={'name':app,'coreType':'tcp_ss','coreInit':'--federates=1','broker':'tcp://material-helics-broker:24900','period':1.0,'timeDelta':1.0,
            'endpoints':[{'name':app+'/events','global':True,'type':'application/json'}],'publications':[{'key':'completed_items','type':'double','unit':'item'}]}
        services[app+'-adapter']={'image':image,'environment':{**context,'SIMULATOR':app,'HELICS_CONFIG':json.dumps(config),'HELICS_OUTPUTS':json.dumps(outputs),'HELICS_ADAPTER_TOKEN':token,'ADAPTER_JOURNAL':'/journal/adapter.sqlite'},
            'volumes':[app+'-journal:/journal'],'depends_on':{'material-helics-broker':{'condition':'service_healthy'}},'restart':'no'}
        value['volumes'][app+'-journal']={};services.pop(app+'-verify',None);services.pop(app+'-web',None)
    artifacts=ROOT/'.superpowers/sdd/2026-10-25-simu64-implementation/material-native';artifacts.mkdir(parents=True,exist_ok=True)
    services['verify']={'image':'logistics-simulator:bootstrap','profiles':['test'],'working_dir':'/app','user':'0:0','command':['python','scripts/handling_material_verify.py'],
        'environment':{'MATERIAL_IDENTITIES':json.dumps(identities),'MATERIAL_DATABASES':json.dumps(databases),'EXPECTED_RUN_ID':run,'EXPECTED_EPOCH':epoch},
        'volumes':[str(ROOT/'scripts')+':/app/scripts:ro',str(ROOT/'contracts')+':/app/contracts:ro',str(artifacts)+':/evidence']}
    path=ROOT/'deploy/generated/handling-material.json';path.write_text(json.dumps(value,indent=2));path.chmod(0o600);print(path)


if __name__=='__main__':main()

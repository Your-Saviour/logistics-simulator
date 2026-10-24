"""Four native departments and private HELICS adapters; Twin is absent."""
import json
from uuid import uuid4
from stacks_compose import generate, ROOT


def main():
    apps=('storage','manufacturing','shipping','logistics')
    value=generate(list(apps),write=False);value['name']='simu-handling-factory-'+uuid4().hex[:8]
    services=value['services'];services.pop('browser-check',None)
    run,epoch=str(uuid4()),str(uuid4());context={'FEDERATION_ID':'handling-factory-native','FEDERATION_RUN_ID':run,'FEDERATION_EPOCH':epoch}
    token=uuid4().hex+uuid4().hex;image='logistics-simulator:handling-factory-adapter'
    services['factory-helics-broker']={'image':image,'entrypoint':['helics_broker','-t','tcp_ss','-f4','--port=24900','--ipv4','--loglevel=warning'],
        'healthcheck':{'test':['CMD','python','-c',"import socket; socket.create_connection(('127.0.0.1',24900),2).close()"],'interval':'2s','timeout':'3s','retries':30}}
    providers={'storage':{'supply':'helics','requests':'helics'},'manufacturing':{'materials':'helics','demand':'helics','power':'synthetic'},'shipping':{'orders':'synthetic','goods':'helics','carrier':'helics'},'logistics':{'transport':'helics','destinations':'synthetic'}}
    peer=lambda app:{'source':app,'endpoint':app+'/events'}
    peers={'storage':{'supply':peer('manufacturing'),'requests':[peer('manufacturing'),peer('shipping')]},'manufacturing':{'materials':peer('storage'),'demand':peer('shipping')},'shipping':{'goods':[peer('storage'),peer('manufacturing')],'carrier':peer('logistics')},'logistics':{'transport':peer('shipping')}}
    routes={'storage':[('manufacturing','materials'),('shipping','goods')],'manufacturing':[('storage','requests'),('storage','supply')],'shipping':[('storage','requests'),('manufacturing','demand'),('logistics','transport')],'logistics':[('shipping','carrier')]}
    identities={};databases={}
    for app in apps:
        outputs=[{'endpoint':target+'/events','destination':target,'boundary':boundary} for target,boundary in routes[app]]
        for role in ('api','worker','controller'):
            service=services[app+'-'+role];service['image']='logistics-simulator:handling-factory-'+app
            env=service['environment'];env.update(context,CLOCK_MODE='helics',BOUNDARY_PROVIDERS=json.dumps(providers[app]),HELICS_PEERS=json.dumps(peers[app]),HELICS_OUTPUTS=json.dumps(outputs),HELICS_ADAPTER_URL='http://'+app+'-adapter:8010',HELICS_ADAPTER_TOKEN=token,HELICS_TIMEOUT_SECONDS='240',AUTONOMOUS_SAMPLE='true' if app=='logistics' else 'false',AUTONOMOUS_WAREHOUSE='false',AUTONOMOUS_SHIPPING='false',AUTONOMOUS_PRODUCTION='true' if app=='manufacturing' else 'false')
            if app=='manufacturing':env.update(MATERIAL_RETRY_QUANTA='60',SCENARIO=json.dumps({'manufacturing':{'products':[{'sku':'PRODUCT','bom':{'COMPONENT':2},'duration_seconds':60,'scrap_percent':0}],'lines':[{'code':'LINE-1','capacity':1,'products':['PRODUCT']}]}}))
            if role=='api':identities[app]={'username':env['APP_USERNAME'],'password':env['APP_PASSWORD']};databases[app]=env['DATABASE_URL']
            if role=='controller':service['depends_on'][app+'-adapter']={'condition':'service_started'}
        config={'name':app,'coreType':'tcp_ss','coreInit':'--federates=1','broker':'tcp://factory-helics-broker:24900','period':1.0,'timeDelta':1.0,'endpoints':[{'name':app+'/events','global':True,'type':'application/json'}],'publications':[{'key':'completed_items','type':'double','unit':'item'}]}
        services[app+'-adapter']={'image':image,'environment':{**context,'SIMULATOR':app,'HELICS_CONFIG':json.dumps(config),'HELICS_OUTPUTS':json.dumps(outputs),'HELICS_ADAPTER_TOKEN':token,'ADAPTER_JOURNAL':'/journal/adapter.sqlite'},'volumes':[app+'-journal:/journal'],'depends_on':{'factory-helics-broker':{'condition':'service_healthy'}},'restart':'no'}
        value['volumes'][app+'-journal']={};services.pop(app+'-verify',None);services.pop(app+'-web',None)
    artifacts=ROOT/'.superpowers/sdd/2026-10-25-simu64-implementation/factory-native';artifacts.mkdir(parents=True,exist_ok=True)
    services['verify']={'image':'logistics-simulator:bootstrap','profiles':['test'],'working_dir':'/app','user':'0:0','command':['python','scripts/handling_factory_verify.py'],
        'environment':{'FACTORY_IDENTITIES':json.dumps(identities),'FACTORY_DATABASES':json.dumps(databases),'EXPECTED_RUN_ID':run,'EXPECTED_EPOCH':epoch},'volumes':[str(ROOT/'scripts')+':/app/scripts:ro',str(ROOT/'contracts')+':/app/contracts:ro',str(artifacts)+':/evidence']}
    path=ROOT/'deploy/generated/handling-factory.json';path.write_text(json.dumps(value,indent=2));path.chmod(0o600);print(path)


if __name__=='__main__':main()

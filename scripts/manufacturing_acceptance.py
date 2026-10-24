"""Production lifecycle/recovery against disposable Java deployment containers."""
import argparse
import json
import os
import time
from uuid import uuid4
import httpx
import pika
import psycopg
from stack_acceptance import wait_for
from simulator.handling_contracts import validate_snapshot, validate_movement, validate_lineage


def main(phase):
    with httpx.Client(base_url='http://manufacturing-api:8000',auth=(os.environ['APP_USERNAME'],os.environ['APP_PASSWORD']),timeout=10) as c:
        employee=next(a for a in json.loads(os.environ['APP_IDENTITIES']) if a['role']=='employee')
        auth=(employee['username'],employee['password'])
        def submit(action,key=None,**fields):
            s=c.get('/api/status').json();r=s['run']
            if action=='supply' and 'units' not in fields:
                fields['units']=[{'id':str(uuid4()),'quantity':fields['quantity']}]
            body={'run_id':r['id'],'epoch':r['epoch'],'due_at':max(r['granted'],r['requested'])+2*s['quantum']+2*r['speed'],'action':action,**fields}
            headers={'Idempotency-Key':key or uuid4().hex};response=c.post('/api/production/commands',json=body,headers=headers,auth=auth);response.raise_for_status();command=response.json()
            assert c.post('/api/production/commands',json=body,headers=headers,auth=auth).json()['id']==command['id']
            snap=wait_for(c,'/api/production',lambda p:any(x['id']==command['id'] and x['status']!='pending' for x in p['commands']))
            result=next(x for x in snap['commands'] if x['id']==command['id']);assert result['status']=='completed',result
            return command['id']
        def validate_handling(snapshot):
            run=c.get('/api/status').json()['run']
            handling=snapshot['handling']
            validate_snapshot(handling['units'],run['id'],run['epoch'])
            for movement in handling['movements']:
                validate_movement(movement,run['id'],run['epoch'])
            for lineage in handling['lineage']:
                validate_lineage(lineage,handling['units'],run['id'],run['epoch'])
        if phase=='verify':
            s=wait_for(c,'/api/status',lambda s:bool(s['run']));c.post('/api/control/reset',json={'confirm_run_id':s['run']['id'],'scenario':{}}).raise_for_status();c.post('/api/control/speed',json={'speed':20}).raise_for_status()
            order=submit('create',product='PRODUCT',line='LINE-1',quantity=4)
            submit('release',reference=order)
            wait_for(c,'/api/production',lambda p:any(o['id']==order and o['blocked_reason'] and 'COMPONENT' in o['blocked_reason'] for o in p['orders']))
            submit('hold',reference=order);submit('supply',sku='COMPONENT',quantity=8)
            p=c.get('/api/production').json();assert next(o for o in p['orders'] if o['id']==order)['status']=='held';assert p['materials'][0]['quantity']==8
            submit('release',reference=order)
            p=wait_for(c,'/api/production',lambda p:any(o['id']==order and o['status']=='completed' for o in p['orders']))
            assert p['orders'][0]['output_quantity']==4 and p['materials'][0]['quantity']==0,p
            validate_handling(p)
            assert len(p['handling']['lineage'])==1
            assert c.post('/api/control/hold',json={},auth=auth).status_code==403
            assert c.get('/api/audit',auth=auth).status_code==403
            assert c.post('/api/production/commands',json={},auth=auth).status_code==422
            # A 600-second batch leaves time for the guarded orchestrator to stop workers.
            current=c.get('/api/status').json()['run']
            scenario={'manufacturing':{'products':[{'sku':'PRODUCT','bom':{'COMPONENT':2},'duration_seconds':600,'scrap_percent':0}], 'lines':[{'code':'LINE-1','capacity':1,'products':['PRODUCT']}]}}
            c.post('/api/control/reset',json={'confirm_run_id':current['id'],'scenario':scenario}).raise_for_status()
            c.post('/api/control/speed',json={'speed':60}).raise_for_status()
            submit('supply',sku='COMPONENT',quantity=8);first=submit('create',product='PRODUCT',line='LINE-1',quantity=4)
            submit('release',reference=first)
            wait_for(c,'/api/production',lambda p:any(o['id']==first and o['status']=='completed' for o in p['orders']),timeout=90)
            submit('supply',sku='COMPONENT',quantity=8);order=submit('create',product='PRODUCT',line='LINE-1',quantity=4)
            submit('release',reference=order)
            wait_for(c,'/api/production',lambda p:any(o['id']==order and o['status']=='running' for o in p['orders']))
            c.post('/api/control/hold',json={}).raise_for_status()
            print('manufacturing V1: employee shortage, hold, supply, release and finite completion passed',flush=True)
        elif phase=='workers-down':
            p=c.get('/api/production').json();running=[o for o in p['orders'] if o['status']=='running'];assert len(running)==1,p
            order=running[0];c.post('/api/control/resume',json={}).raise_for_status();status=wait_for(c,'/api/status',lambda s:s['run']['granted']>=order['finish_due'],timeout=90);time.sleep(.5)
            after=c.get('/api/production').json();assert next(o for o in after['orders'] if o['id']==order['id'])['status']=='running'
            assert c.get('/api/status').json()['run']['granted']==status['run']['granted']
            print('manufacturing V1: stopped workers retain running batch and current-time barrier',flush=True)
        elif phase=='workers-up':
            p=wait_for(c,'/api/production',lambda p:len(p['orders'])==2 and all(o['status']=='completed' for o in p['orders']))
            with psycopg.connect(os.environ['DATABASE_URL']) as db:
                run=db.execute('SELECT id FROM runs WHERE current').fetchone()[0]
                ids=db.execute("SELECT j.id FROM jobs j JOIN production_commands p ON p.id=j.id WHERE j.run_id=%s AND p.command->>'action' IN ('start','finish')",(run,)).fetchall()
            connection=pika.BlockingConnection(pika.URLParameters(os.environ['AMQP_URL']));channel=connection.channel()
            for row in ids:
                for _ in range(4):channel.basic_publish('', 'sample.jobs.v1',json.dumps({'job_id':str(row[0])}),properties=pika.BasicProperties(delivery_mode=2))
            connection.close();time.sleep(1)
            p=c.get('/api/production').json();assert sum(o['output_quantity'] for o in p['orders'])==8
            validate_handling(p)
            assert len([m for m in p['movements'] if m['kind']=='output'])==2
            assert len([m for m in p['movements'] if m['kind']=='consume'])==2
            assert p['materials'][0]['quantity']==0
            print('manufacturing V1: worker restart and duplicate deliveries across two workers produce exactly one consumption/output per batch',flush=True)
        elif phase=='broker-down':
            s=c.get('/api/status').json();r=s['run'];due=max(r['granted'],r['requested'])+2*s['quantum']+2*r['speed']
            response=c.post('/api/production/commands',json={'run_id':r['id'],'epoch':r['epoch'],'due_at':due,'action':'supply','sku':'COMPONENT','quantity':2,'units':[{'id':str(uuid4()),'quantity':2}]},headers={'Idempotency-Key':'broker-recovery'});assert response.status_code==200,response.text
            s=wait_for(c,'/api/status',lambda s:s['run']['granted']>=due);time.sleep(.5)
            p=c.get('/api/production').json();assert p['materials'][0]['quantity']==0
            assert c.get('/api/status').json()['run']['granted']==s['run']['granted']
            print('manufacturing V1: broker outage retains pending material receipt without effect',flush=True)
        elif phase=='broker-up':
            p=wait_for(c,'/api/production',lambda p:p['materials'][0]['quantity']==2)
            assert len([m for m in p['movements'] if m['kind']=='supply' and m['quantity']==2])==1
            print('manufacturing V1: broker recovery applies material receipt once',flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--phase',default='verify');main(parser.parse_args().phase)

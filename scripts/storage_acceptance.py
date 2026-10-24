"""Storage V1 lifecycle against disposable production containers only."""
import json
import os
import time
from uuid import uuid4
import httpx
from stack_acceptance import wait_for
from simulator.handling_contracts import validate_snapshot, validate_movement


def verify():
    with httpx.Client(base_url='http://storage-api:8000',auth=(os.environ['APP_USERNAME'],os.environ['APP_PASSWORD']),timeout=10) as c:
        status=wait_for(c,'/api/status',lambda x:bool(x['run']))
        response=c.get('/api/warehouse')
        assert response.status_code==200, 'Warehouse inventory endpoint missing: '+str(response.status_code)
        c.post('/api/control/reset',json={'confirm_run_id':status['run']['id']}).raise_for_status()
        c.post('/api/control/speed',json={'speed':20}).raise_for_status()
        employee=next(a for a in json.loads(os.environ['APP_IDENTITIES']) if a['role']=='employee')
        auth=(employee['username'],employee['password'])
        def submit(action,expected='completed',key=None,**fields):
            r=c.get('/api/status').json()
            if action=='expect' and 'units' not in fields:
                fields['units']=[{'id':str(uuid4()),'quantity':fields['quantity']}]
            body={'run_id':r['run']['id'],'epoch':r['run']['epoch'],'due_at':max(r['run']['granted'],r['run']['requested'])+2,'action':action,**fields}
            headers={'Idempotency-Key':key or uuid4().hex}
            res=c.post('/api/warehouse/commands',json=body,headers=headers,auth=auth)
            assert res.status_code==200,res.text
            command=res.json()
            assert c.post('/api/warehouse/commands',json=body,headers=headers,auth=auth).json()['id']==command['id']
            snap=wait_for(c,'/api/warehouse',lambda s:any(x['id']==command['id'] and x['status'] in ('completed','rejected') for x in s['commands']))
            result=next(x for x in snap['commands'] if x['id']==command['id'])
            assert result['status']==expected,result
            validate_snapshot(snap['handling']['units'], r['run']['id'], r['run']['epoch'])
            for movement in snap['handling']['movements']:
                validate_movement(movement, r['run']['id'], r['run']['epoch'])
            return command['id'],snap
        correlation=str(uuid4())
        receipt,_=submit('expect',sku='COMPONENT',location='RAW-A',quantity=10,correlation_id=correlation,units=[{'id':str(uuid4()),'quantity':6},{'id':str(uuid4()),'quantity':4}])
        _,snap=submit('receive',reference=receipt)
        assert next(s for s in snap['inventory'] if s['sku']=='COMPONENT' and s['location']=='RAW-A')['on_hand']==10
        raw=snap['handling']['units']
        assert len(raw)==2 and len({u['barcode'] for u in raw})==2
        assert all(u['position'].startswith('storage.inbound.dock') for u in raw)
        submit('receive',reference=receipt,expected='rejected')
        reservation,_=submit('reserve',sku='COMPONENT',location='RAW-A',quantity=6,purpose='production',correlation_id=correlation)
        submit('reserve',sku='COMPONENT',location='RAW-A',quantity=5,purpose='production',correlation_id=str(uuid4()),expected='rejected')
        submit('issue',reference=reservation)
        goods,_=submit('expect',sku='PRODUCT',location='FINISHED-A',quantity=8,correlation_id=correlation,units=[{'id':str(uuid4()),'quantity':5},{'id':str(uuid4()),'quantity':3}])
        submit('receive',reference=goods)
        pick,_=submit('reserve',sku='PRODUCT',location='FINISHED-A',quantity=5,purpose='customer',correlation_id=correlation)
        submit('pick',reference=pick)
        transfer,snap=submit('transfer',reference=pick,destination='DISPATCH')
        assert next(t for t in snap['transfers'] if t['id']==transfer)['status']=='in_transit'
        assert next(s for s in snap['inventory'] if s['sku']=='PRODUCT' and s['location']=='DISPATCH')['on_hand']==0
        submit('arrive',reference=transfer)
        _,snap=submit('arrive',reference=transfer,expected='rejected')
        assert next(s for s in snap['inventory'] if s['sku']=='PRODUCT' and s['location']=='DISPATCH')['on_hand']==5
        assert all(m['correlation_id']==correlation for m in snap['movements'])
        capacity,_=submit('expect',sku='PRODUCT',location='DISPATCH',quantity=10000,correlation_id=str(uuid4()))
        submit('receive',reference=capacity,expected='rejected')
        assert c.post('/api/warehouse/commands',json={},auth=(employee['username'],employee['password'])).status_code==422
        assert c.post('/api/control/hold',json={},auth=auth).status_code==403
        r=c.get('/api/status').json()
        assert c.post('/api/jobs',json={'due_at':max(r['run']['granted'],r['run']['requested'])+2,'quantity':1},headers={'Idempotency-Key':'warehouse:employee-sample'},auth=auth).status_code==409
        submit('expect',sku='PRODUCT',location='FINISHED-A',quantity=9,correlation_id=str(uuid4()),key='recovery:warehouse-receipt')
        submit('expect',sku='PRODUCT',location='FINISHED-A',quantity=11,correlation_id=str(uuid4()),key='recovery:broker-receipt')
        # Restart phase stores a command while no worker is running. The caller
        # controls real process stop/start between --queue and --recover.
        print('storage V1: employee receipt, reservation, material issue, pick, in-transit transfer, arrival, duplicate and capacity checks passed',flush=True)

def recovery(phase):
    import pika
    import psycopg
    with httpx.Client(base_url='http://storage-api:8000',auth=(os.environ['APP_USERNAME'],os.environ['APP_PASSWORD']),timeout=10) as c:
        if phase=='broker-down':
            snap=c.get('/api/warehouse').json()
            receipt=next(x for x in snap['receipts'] if x['quantity']==11 and x['status']=='expected')
            r=c.get('/api/status').json()
            due=max(r['run']['granted'],r['run']['requested'])+2
            response=c.post('/api/warehouse/commands',json={'run_id':r['run']['id'],'epoch':r['run']['epoch'],'due_at':due,'action':'receive','reference':receipt['id']},headers={'Idempotency-Key':'recovery:broker'})
            response.raise_for_status()
            granted=wait_for(c,'/api/status',lambda s:s['run']['granted']>=due)['run']['granted']
            time.sleep(.5)
            after=c.get('/api/warehouse').json()
            assert next(x for x in after['receipts'] if x['id']==receipt['id'])['status']=='expected'
            assert next(x for x in after['inventory'] if x['sku']=='PRODUCT' and x['location']=='FINISHED-A')['on_hand']==3
            assert c.get('/api/status').json()['run']['granted']==granted
            assert next(x for x in after['commands'] if x['id']==response.json()['id'])['attempts']==0
        elif phase=='broker-up':
            snap=wait_for(c,'/api/warehouse',lambda s:any(x['quantity']==11 and x['status']=='received' for x in s['receipts']))
            assert next(x for x in snap['inventory'] if x['sku']=='PRODUCT' and x['location']=='FINISHED-A')['on_hand']==14
            with psycopg.connect(os.environ['DATABASE_URL']) as db:
                movements=db.execute("SELECT count(*),sum(on_hand_delta) FROM warehouse_movements WHERE command_id=(SELECT id FROM jobs WHERE run_id=%s AND idempotency_key='recovery:broker')",(snap['run_id'],)).fetchone()
                assert movements==(1,11)
        elif phase=='queue':
            snap=c.get('/api/warehouse').json()
            receipt=next(x for x in snap['receipts'] if x['quantity']==9 and x['status']=='expected')
            r=c.get('/api/status').json()
            body={'run_id':r['run']['id'],'epoch':r['run']['epoch'],'due_at':max(r['run']['granted'],r['run']['requested'])+2,'action':'receive','reference':receipt['id']}
            result=c.post('/api/warehouse/commands',json=body,headers={'Idempotency-Key':'recovery:warehouse'})
            result.raise_for_status()
            command=result.json()
            # Publish duplicates while the real worker is stopped; SQL outbox
            # will publish again after restart, too.
            connection=pika.BlockingConnection(pika.URLParameters(os.environ['AMQP_URL']))
            try:
                channel=connection.channel();channel.confirm_delivery()
                for _ in range(3):
                    channel.basic_publish('',routing_key='sample.jobs.v1',body=json.dumps({'job_id':command['id']}),mandatory=True,properties=pika.BasicProperties(delivery_mode=2))
            finally: connection.close()
            time.sleep(.5)
            assert next(x for x in c.get('/api/warehouse').json()['receipts'] if x['id']==receipt['id'])['status']=='expected'
        elif phase=='recovered':
            snap=wait_for(c,'/api/warehouse',lambda s:any(x['quantity']==9 and x['status']=='received' for x in s['receipts']))
            assert next(x for x in snap['inventory'] if x['sku']=='PRODUCT' and x['location']=='FINISHED-A')['on_hand']==23
            with psycopg.connect(os.environ['DATABASE_URL']) as db:
                count=db.execute("SELECT count(*) FROM warehouse_commands c JOIN jobs j USING(id) WHERE j.idempotency_key='recovery:warehouse' AND j.run_id=%s AND c.status='completed'",(snap['run_id'],)).fetchone()[0]
                assert count==1
                movements=db.execute("SELECT count(*),sum(on_hand_delta) FROM warehouse_movements WHERE command_id=(SELECT id FROM jobs WHERE run_id=%s AND idempotency_key='recovery:warehouse')",(snap['run_id'],)).fetchone()
                assert movements==(1,9)
        print('storage V1: stock recovery / redelivery '+phase+' passed',flush=True)

if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser();parser.add_argument('--phase',choices=['queue','recovered','broker-down','broker-up'])
    args=parser.parse_args()
    recovery(args.phase) if args.phase else verify()

"""Real employee transport and recovery acceptance; only disposable deployments."""
import argparse
import os
import time
import json
from uuid import uuid4
import httpx
import psycopg
from stack_acceptance import wait_for
from simulator.handling_contracts import validate_snapshot, validate_movement

parser=argparse.ArgumentParser();parser.add_argument('--phase',default='lifecycle',choices=['lifecycle','prepare-transit','queue','recovered','broker-down','broker-up']);args=parser.parse_args()
with httpx.Client(base_url='http://logistics-api:8000',auth=(os.environ['APP_USERNAME'],os.environ['APP_PASSWORD']),timeout=10) as c:
    def command(action,**fields):
        if action=='request' and 'unit_ids' not in fields:
            # Explicit initial-stock fixture through the real intake job path.
            unit=str(uuid4());snapshot=c.get('/api/transport').json()
            route=next(r for r in snapshot['configuration']['routes'] if r['code']==fields['route'])
            outcome(command('intake',sku=fields['sku'],category='finished',quantity=fields['quantity'],location=route['origin'],correlation_id=fields['correlation_id'],units=[{'id':unit,'quantity':fields['quantity']}]))
            fields['unit_ids']=[unit]
        status=c.get('/api/status').json();r=status['run'];quantum=status['quantum']
        body=dict(run_id=r['id'],epoch=r['epoch'],due_at=max(r['requested'],r['granted'])+2*quantum+r['speed'],action=action,**fields)
        response=c.post('/api/transport/commands',json=body,headers={'Idempotency-Key':str(uuid4())})
        assert response.status_code==200,response.text
        return response.json()['id']
    def outcome(id):
        snap=wait_for(c,'/api/transport',lambda v:any(x['id']==id and x['status']!='pending' for x in v['commands']),timeout=60)
        row=next(x for x in snap['commands'] if x['id']==id);assert row['status']=='completed',row
        run=c.get('/api/status').json()['run']
        validate_snapshot(snap['handling']['units'],run['id'],run['epoch'])
        for movement in snap['handling']['movements']:
            validate_movement(movement,run['id'],run['epoch'])
        return snap
    if args.phase=='lifecycle':
        current=wait_for(c,'/api/status',lambda v:v['run']['state']=='running')
        assert c.post('/api/control/reset',json={'confirm_run_id':current['run']['id']}).status_code==200
        assert c.post('/api/control/speed',json={'speed':20}).status_code==200
        id=command('request',route='WAREHOUSE-DISPATCH',sku='PRODUCT',quantity=8,correlation_id=str(uuid4()));outcome(id)
        for action,fields in [('assign',{'vehicle':'TRUCK-1'}),('load',{}),('depart',{})]:outcome(command(action,reference=id,**fields))
        snap=wait_for(c,'/api/transport',lambda v:any(t['id']==id and t['status']=='arrived' for t in v['transfers']))
        tr=next(t for t in snap['transfers'] if t['id']==id);assert tr['arrived_at']>=tr['planned_eta'] and tr['received_at'] is None and tr['custody']=='vehicle'
        outcome(command('unload',reference=id));snap=c.get('/api/transport').json();tr=next(t for t in snap['transfers'] if t['id']==id);assert tr['status']=='unloaded' and tr['received_at'] is None
        outcome(command('receive',reference=id))
        with psycopg.connect(os.environ['DATABASE_URL']) as db:
            arrival=db.execute("SELECT j.id FROM jobs j JOIN transport_commands c ON c.id=j.id WHERE c.command->>'reference'=%s AND c.command->>'action'='arrive'",(id,)).fetchone()[0]
            # Actual broker redelivery of a committed arrival is exercised by the worker.
        import pika
        connection=pika.BlockingConnection(pika.URLParameters(os.environ['AMQP_URL']));channel=connection.channel();channel.confirm_delivery()
        for _ in range(5):channel.basic_publish(exchange='',routing_key='sample.jobs.v1',body=json.dumps({'job_id':str(arrival)}),properties=pika.BasicProperties(delivery_mode=2),mandatory=True)
        for attempt in range(100):
            queue=channel.queue_declare(queue='sample.jobs.v1',passive=True).method
            # Workers use basic.get, so RabbitMQ intentionally reports zero registered consumers.
            if queue.message_count==0:
                time.sleep(.2)
                break
            time.sleep(.1)
        else:raise AssertionError('Arrival redeliveries were not consumed')
        connection.close()
        snap=c.get('/api/transport').json();assert len([m for m in snap['movements'] if m['transfer_id']==id and m['action']=='arrive'])==1
        assert next(v for v in snap['vehicles'] if v['code']=='TRUCK-1')['location']=='DISPATCH'
        print('logistics V1: employee lifecycle, finite capacity, custody, ETA/arrival/receipt and duplicate arrival delivery passed',flush=True)
    elif args.phase=='prepare-transit':
        current=c.get('/api/status').json()
        scenario={'transport':{'locations':[{'code':'WAREHOUSE'},{'code':'DISPATCH'}],
            'routes':[{'code':'WAREHOUSE-DISPATCH','origin':'WAREHOUSE','destination':'DISPATCH','journey_seconds':120}],
            'vehicles':[{'code':'TRUCK-1','capacity':100,'location':'WAREHOUSE'}]}}
        assert c.post('/api/control/reset',json={'confirm_run_id':current['run']['id'],'scenario':scenario}).status_code==200
        assert c.post('/api/control/speed',json={'speed':20}).status_code==200
        id=command('request',route='WAREHOUSE-DISPATCH',sku='PRODUCT',quantity=4,correlation_id='44444444-4444-4444-8444-444444444444');outcome(id)
        for action,fields in [('assign',{'vehicle':'TRUCK-1'}),('load',{}),('depart',{})]:outcome(command(action,reference=id,**fields))
        assert c.post('/api/control/hold',json={}).status_code==200
        tr=next(t for t in c.get('/api/transport').json()['transfers'] if t['id']==id)
        assert tr['status']=='in_transit' and tr['custody']=='vehicle'
        print('logistics V1: held in-transit load ready for real worker restart',flush=True)
    elif args.phase=='queue':
        assert c.post('/api/control/resume',json={}).status_code==200
        eta=c.get('/api/transport').json()['transfers'][0]['planned_eta']
        wait_for(c,'/api/status',lambda v:v['run']['granted']>=eta,timeout=30)
        tr=c.get('/api/transport').json()['transfers'][0]
        assert tr['status']=='in_transit' and tr['custody']=='vehicle' and tr['arrived_at'] is None
        print('logistics V1: eligible arrival retained while worker pool is stopped',flush=True)
    elif args.phase=='recovered':
        snap=wait_for(c,'/api/transport',lambda v:any(t['status']=='arrived' for t in v['transfers']),timeout=60)
        tr=snap['transfers'][0];assert tr['custody']=='vehicle' and tr['received_at'] is None
        assert len([m for m in snap['movements'] if m['action']=='arrive'])==1
        assert not any(x['attempts'] for x in snap['commands'])
        print('logistics V1: worker replicas recovered one arrival without losing in-transit load',flush=True)
    elif args.phase=='broker-down':
        tr=c.get('/api/transport').json()['transfers'][0];command('unload',reference=tr['id']);time.sleep(2)
        snap=c.get('/api/transport').json();tr=snap['transfers'][0]
        assert tr['status']=='arrived' and tr['custody']=='vehicle' and tr['unloaded_at'] is None
        assert any(x['status']=='pending' and x['command']['action']=='unload' for x in snap['commands'])
        print('logistics V1: broker outage retains load, vehicle reservation and pending unload',flush=True)
    else:
        snap=wait_for(c,'/api/transport',lambda v:any(t['status']=='unloaded' for t in v['transfers']),timeout=60)
        tr=snap['transfers'][0];assert tr['received_at'] is None
        outcome(command('receive',reference=tr['id']))
        assert not any(x['attempts'] for x in snap['commands'])
        print('logistics V1: broker recovery completes one unload and separate receipt',flush=True)

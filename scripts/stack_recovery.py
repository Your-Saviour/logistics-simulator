"""Real standalone recovery probes, run only inside each stack's verifier container."""
import argparse
import json
import os
import time
from uuid import uuid4

import httpx
import pika
import psycopg

SCENARIO={'seed':19,'time_zone':'UTC','start_at':'2026-01-05T09:00:00Z','business_open':'09:00:00','business_close':'15:00:00','business_weekdays':[0,1,2,3,4],'interval_seconds':30}


def wait(fn,predicate,timeout=60):
    deadline=time.monotonic()+timeout
    last=None
    while time.monotonic()<deadline:
        try:
            last=fn()
            if predicate(last): return last
        except (httpx.HTTPError,psycopg.Error,pika.exceptions.AMQPError): pass
        time.sleep(.2)
    raise AssertionError('Recovery condition timed out: '+str(last))


def run(app,url,phase):
    with httpx.Client(base_url=url,auth=(os.environ['APP_USERNAME'],os.environ['APP_PASSWORD']),timeout=15) as client:
        def status():
            response=client.get('/api/status');response.raise_for_status();return response.json()
        def post(path,body,key=None):
            response=client.post('/api/'+path,json=body,headers={'Idempotency-Key':key} if key else {})
            assert response.status_code==200,(phase,path,response.status_code,response.text)
            return response.json()
        def job(value,key): return next(j for j in value['jobs'] if j['idempotency_key']==key)
        def broker():
            parameters=pika.URLParameters(os.environ['AMQP_URL']);parameters.socket_timeout=3
            connection=pika.BlockingConnection(parameters);channel=connection.channel();channel.confirm_delivery()
            return connection,channel
        if phase=='prepare-broker':
            before=status()
            post('control/reset',{'confirm_run_id':before['run']['id'],'scenario':SCENARIO})
            post('control/hold',{})
            value=status();due=max(value['run']['granted'],value['run']['requested'])+value['quantum']
            post('jobs',{'due_at':due,'quantity':2},'recovery:first')
        elif phase=='broker-down':
            post('control/resume',{})
            value=wait(status,lambda v:v['run']['granted']>=job(v,'recovery:first')['due_at'])
            assert value['effects']==0 and job(value,'recovery:first')['attempts']==0
            grant=value['run']['granted'];time.sleep(.4)
            assert status()['run']['granted']==grant,'SQL due-work barrier advanced during broker outage'
        elif phase=='broker-up':
            value=wait(status,lambda v:job(v,'recovery:first')['status']=='completed')
            assert value['effects']==2 and job(value,'recovery:first')['attempts']==0
        elif phase=='duplicate':
            value=status();job_id=job(value,'recovery:first')['id'];connection,channel=broker()
            try:
                for _ in range(2):
                    channel.basic_publish('',routing_key='sample.jobs.v1',body=json.dumps({'job_id':job_id}),mandatory=True,
                        properties=pika.BasicProperties(delivery_mode=2,message_id=str(uuid4()),content_type='application/json'))
            finally: connection.close()
        elif phase=='worker-up':
            def drained():
                connection,channel=broker()
                try: return channel.queue_declare('sample.jobs.v1',passive=True).method.message_count==0
                finally: connection.close()
            wait(drained,bool)
            value=status();assert value['effects']==2
            with psycopg.connect(os.environ['DATABASE_URL']) as db:
                count,total=db.execute('SELECT count(*),sum(quantity) FROM effects WHERE job_id=%s',(job(value,'recovery:first')['id'],)).fetchone()
                assert count==1 and total==2
        elif phase=='prepare-db':
            post('control/hold',{})
            value=status();due=max(value['run']['granted'],value['run']['requested'])+value['quantum']
            post('jobs',{'due_at':due,'quantity':3},'recovery:second')
        elif phase=='db-down':
            assert client.get('/api/status').status_code==503
            response=client.post('/api/jobs',json={'due_at':100000,'quantity':1},headers={'Idempotency-Key':'database-unaccepted'})
            assert response.status_code==503,(response.status_code,response.text)
        elif phase=='db-up':
            value=wait(status,lambda v:v['run']['state'] in ('held','running'))
            first,second=job(value,'recovery:first'),job(value,'recovery:second')
            assert first['run_id']==second['run_id']==value['run']['id'] and first['epoch']==second['epoch']==value['run']['epoch']
            assert first['status']=='completed' and second['attempts']==0 and value['effects']==2
            scenario=value['run']['scenario']
            assert scenario['seed']==19 and scenario['time_zone']=='UTC' and scenario['business_weekdays']==[0,1,2,3,4]
            assert not any(j['idempotency_key']=='database-unaccepted' for j in value['jobs'])
            post('control/resume',{})
            value=wait(status,lambda v:job(v,'recovery:second')['status']=='completed')
            assert value['effects']==5 and job(value,'recovery:second')['attempts']==0
            with psycopg.connect(os.environ['DATABASE_URL']) as db:
                count,total=db.execute('SELECT count(*),sum(quantity) FROM effects WHERE run_id=%s',(value['run']['id'],)).fetchone()
                assert count==2 and total==5
        print(app+': '+phase+' passed',flush=True)

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--app',required=True);parser.add_argument('--url',required=True)
    parser.add_argument('--phase',required=True,choices=['prepare-broker','broker-down','broker-up','duplicate','worker-up','prepare-db','db-down','db-up'])
    args=parser.parse_args();run(args.app,args.url,args.phase)

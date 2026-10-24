"""Mixed-language federation acceptance; executes only inside its verifier container."""
import argparse
import json
import os
from pathlib import Path
import time
from uuid import uuid4

import httpx
import psycopg
from psycopg.rows import dict_row
from simulator.federation_config import ROUTES

APPS=('storage','manufacturing','logistics','shipping')


def wait(fn,check,timeout=90):
    deadline=time.monotonic()+timeout
    last=None
    while time.monotonic()<deadline:
        try:
            last=fn()
            if check(last): return last
        except (httpx.HTTPError,psycopg.Error): pass
        time.sleep(.2)
    raise AssertionError('Mixed federation condition timed out: '+str(last))


def main(phase):
    identity=json.loads(os.environ['STACK_IDENTITIES'])
    clients={app:httpx.Client(base_url=f'http://{app}-api:8000',auth=(app+'-operator',identity['passwords'][app]),timeout=5) for app in (*APPS,'twin')}
    def status(app):
        response=clients[app].get('/api/status');response.raise_for_status();return response.json()
    def command(app,path,body,headers=None):
        response=clients[app].post('/api/'+path,json=body,headers=headers)
        assert response.status_code==200,(app,path,response.status_code,response.text)
        return response.json()
    try:
        if phase=='finalize':
            # Hold/finalize one participant at a time. Holding all participants
            # at once is not an acknowledged federation-wide pause barrier.
            for app in APPS:
                command(app,'control/hold',{})
                deadline=time.monotonic()+45
                while time.monotonic()<deadline:
                    response=clients[app].post('/api/control/finalize',json={})
                    if response.status_code==200: break
                    assert response.status_code==409,(app,response.status_code,response.text)
                    time.sleep(.2)
                else: raise AssertionError('Could not settle native finalization for '+app)
                final=wait(lambda:status(app),lambda value:value['run']['state']=='finalized',timeout=45)
                assert final['effects']==4
                password=identity['passwords'][app]
                with psycopg.connect(f'postgresql://{app}:{password}@{app}-db/{app}',row_factory=dict_row) as db:
                    metadata=db.execute('SELECT native_state FROM '+app+'_adapter_sessions WHERE run_id=%s',(identity['run_id'],)).fetchone()
                    assert metadata['native_state']=='finalized'
                print(app+': native acknowledgement and durable finalization passed',flush=True)
            return
        if phase in ('subset','zero-sources','all-sources'):
            expected={'storage','logistics'} if phase=='subset' else set() if phase=='zero-sources' else set(APPS)
            sources=wait(lambda:clients['twin'].get('/api/sources').json(),
                         lambda rows:len(rows)==4 and {row['name'] for row in rows if row['connected']}==expected)
            assert all(row['status']['effects']==4 and row['status']['run']['epoch']==identity['epoch'] for row in sources)
            assert all(identity['passwords'][app] not in json.dumps(sources) for app in APPS)
            print('Optional twin source recovery: '+phase+' passed; retained real snapshots and correct connection state.',flush=True)
            return
        if phase=='adapter-loss':
            lost=wait(lambda:status('storage'),lambda v:v['run']['state']=='stalled',timeout=70)
            assert lost['effects']==4
            assert lost['run']['epoch']==identity['epoch']
            assert all(j['status']!='completed' for j in lost['jobs'] if j['idempotency_key']=='mixed-future')
            print('Mixed native adapter loss: storage stalled with committed effects/run/epoch retained; no fallback or future effect.',flush=True)
            return
        for app in APPS:
            value=wait(lambda:status(app),lambda v:v['run']['requested']>=1)
            assert value['run']['granted']==0 and value['effects']==0
            assert value['run']['mode']=='helics' and value['run']['epoch']==identity['epoch']
            # Public commands must target beyond both granted and requested.
            command(app,'jobs',{'due_at':2,'quantity':2},{'Idempotency-Key':'mixed-owned'})
            command(app,'jobs',{'due_at':100000,'quantity':7},{'Idempotency-Key':'mixed-future'})
        command('storage','control/hold',{})
        time.sleep(.4)
        for app in APPS:
            assert status(app)['effects']==0 and status(app)['run']['granted']==0
        Path('/control/release').write_text('release')
        wait(lambda:status('storage'),lambda v:v['run']['granted']==1)
        time.sleep(.4)
        for app in APPS:
            value=status(app)
            assert value['run']['granted']<=1 and value['effects']==0
        command('storage','control/resume',{})
        final={app:wait(lambda:status(app),lambda v:v['effects']==4) for app in APPS}
        for app,value in final.items():
            assert value['run']['committed']<=value['run']['granted']
            future=next(j for j in value['jobs'] if j['idempotency_key']=='mixed-future')
            assert future['status']!='completed'
            destination,_=ROUTES[app]
            password=identity['passwords'][app]
            with psycopg.connect(f'postgresql://{app}:{password}@{app}-db/{app}',row_factory=dict_row) as db:
                outputs=db.execute('SELECT id,envelope,sent_at FROM boundary_outbox WHERE run_id=%s',(identity['run_id'],)).fetchall()
                assert len(outputs)==1 and outputs[0]['sent_at'] is not None
            target_password=identity['passwords'][destination]
            with psycopg.connect(f'postgresql://{destination}:{target_password}@{destination}-db/{destination}',row_factory=dict_row) as db:
                event=outputs[0]
                received=db.execute('SELECT * FROM inbox WHERE event_id=%s',(event['id'],)).fetchone()
                job=db.execute('SELECT * FROM jobs WHERE idempotency_key=%s',('boundary:'+str(event['id']),)).fetchone()
                assert received and job and job['status']=='completed' and job['payload']['quantity']==2
                assert job['original_due_at']>=event['envelope']['time']+1
            print(app+' → '+destination+': stable event ID, inbox, positive handoff and one committed effect verified',flush=True)
        sources=wait(lambda:clients['twin'].get('/api/sources').json(),lambda rows:len(rows)==4 and all(row['connected'] and row['status']['effects']==4 for row in rows))
        assert {row['name'] for row in sources}==set(APPS)
        assert all(row['status']['effects']==4 for row in sources)
        assert all(identity['passwords'][app] not in json.dumps(sources) for app in APPS)
        print('Mixed C#/Java/Go/PHP federation passed delayed and held grants, external power, correlated durable handoffs, future-work barrier and optional Flask twin observing all four sources.',flush=True)
    finally:
        for client in clients.values(): client.close()

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--phase',choices=['connected','adapter-loss','subset','zero-sources','all-sources','finalize'],default='connected')
    main(parser.parse_args().phase)

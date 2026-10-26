"""Common HTTP acceptance against a real app container; run in a verifier container.

No host service, private business clock, or fake implementation is used.
Mutates only disposable test deployment runs configured by the caller.
"""
import argparse
import json
import os
from pathlib import Path
import time
from uuid import UUID,uuid4
import httpx
import psycopg


def wait_for(client,path,condition,timeout=40):
    deadline=time.monotonic()+timeout
    while time.monotonic()<deadline:
        try:
            response=client.get(path)
            if response.status_code==200 and condition(response.json()): return response.json()
        except httpx.HTTPError: pass
        time.sleep(.2)
    raise AssertionError('Timed out waiting for '+path)


def verify_terminal_reset(app,url):
    with httpx.Client(base_url=url,auth=(os.environ['APP_USERNAME'],os.environ['APP_PASSWORD']),timeout=5) as client:
        current=wait_for(client,'/api/status',lambda v:bool(v['run']))
        assert client.post('/api/control/reset',json={'confirm_run_id':current['run']['id']}).status_code==200
        assert client.post('/api/control/hold',json={}).status_code==200
        current=client.get('/api/status').json()
        assert client.post('/api/control/finalize',json={}).status_code==200
        time.sleep(1)  # Let the actual controller observe the terminal run.
        assert client.post('/api/control/reset',json={'confirm_run_id':current['run']['id']}).status_code==200
        reset=client.get('/api/status').json()
        assert reset['run']['epoch']!=current['run']['epoch']
        key='terminal-reset-'+uuid4().hex
        due=max(reset['run']['requested'],reset['run']['granted'])+reset['quantum']
        response=client.post('/api/jobs',json={'due_at':due,'quantity':1},headers={'Idempotency-Key':key})
        assert response.status_code==200,response.text
        completed=wait_for(client,'/api/status',lambda v:any(j['idempotency_key']==key and j['status']=='completed' for j in v['jobs']),timeout=10)
        assert completed['effects']==1
        print(app+': standalone terminal reset reactivates controller and commits new-epoch work',flush=True)
        # Retry-exhaustion and dependency failures persist these terminal states.
        # Existing runtime suites exercise those failure paths; here the fixture
        # isolates whether the actual live controller can observe a later reset.
        for terminal in ('failed','stalled'):
            with psycopg.connect(os.environ['DATABASE_URL']) as db:
                db.execute('UPDATE runs SET state=%s,error=%s WHERE current',(terminal,'terminal recovery fixture'))
            time.sleep(1)
            previous=client.get('/api/status').json()['run']
            assert client.post('/api/control/reset',json={'confirm_run_id':previous['id']}).status_code==200
            reset=client.get('/api/status').json()
            assert reset['run']['epoch']!=previous['epoch']
            key=terminal+'-reset-'+uuid4().hex
            due=max(reset['run']['requested'],reset['run']['granted'])+reset['quantum']
            response=client.post('/api/jobs',json={'due_at':due,'quantity':1},headers={'Idempotency-Key':key})
            assert response.status_code==200,response.text
            completed=wait_for(client,'/api/status',lambda v:any(j['idempotency_key']==key and j['status']=='completed' for j in v['jobs']),timeout=10)
            assert completed['effects']==1
            print(app+': '+terminal+' reset retains live controller and commits new-epoch work',flush=True)


def verify(app,url):
    username=os.environ.get('APP_USERNAME',app+'-operator')
    password=os.environ['APP_PASSWORD']
    identities=json.loads(os.environ['APP_IDENTITIES'])
    employee=next(x for x in identities if x['role']=='employee')
    observer=next(x for x in identities if x['role']=='service' and x.get('scopes')==['status:read'])
    with httpx.Client(base_url=url,auth=(username,password),timeout=5) as client:
        value=wait_for(client,'/api/status',lambda v:v['application']==app)
        assert client.get('/api/health/live').status_code==200
        assert client.get('/api/status',auth=('wrong','wrong')).status_code==401
        run=value['run'];UUID(run['id']);UUID(run['epoch'])
        assert {'requested','granted','committed','scenario'}<=run.keys()
        assert isinstance(run['granted'],(int,float)) and run['committed']<=run['granted']
        expected_scopes={'status:read','jobs:write','runs:control','audit:read'}
        if app=='manufacturing': expected_scopes.add('scenarios:manage')
        assert set(value['identity']['scopes'])==expected_scopes
        assert 'password' not in json.dumps(value)
        employee_auth=(employee['username'],employee['password'])
        observer_auth=(observer['username'],observer['password'])
        assert client.get('/api/status',auth=employee_auth).status_code==200
        assert client.get('/api/status',auth=observer_auth).status_code==200
        assert client.get('/api/audit',auth=employee_auth).status_code==403
        assert client.post('/api/control/hold',json={},auth=employee_auth).status_code==403
        assert client.post('/api/jobs',json={'due_at':1,'quantity':1},headers={'Idempotency-Key':'observer-denied'},auth=observer_auth).status_code==403
        if app=='twin':
            assert client.get('/api/sources').status_code==200
            for path in ('/api/jobs','/api/control/hold','/api/control/reset'):
                assert client.post(path,json={}).status_code==403
            print(app+': independent Flask identities, read model, sources and mutation denials passed',flush=True)
            return
        # This verifier owns only disposable test deployments. Archive any prior
        # failed probe so a repeat does not inherit its unfinished sample jobs.
        assert client.post('/api/control/reset',json={'confirm_run_id':run['id']}).status_code==200
        assert client.post('/api/control/hold',json={}).status_code==200
        current=client.get('/api/status').json()
        due=max(current['run']['granted'],current['run']['requested'])+current['quantum']
        fixture=json.loads(Path('contracts/http/v1/jobs.fixtures.json').read_text())
        for case in fixture['invalid']:
            response=client.post('/api/jobs',content=json.dumps(case['body']),headers={'Content-Type':'application/json','Idempotency-Key':'invalid-'+uuid4().hex})
            assert response.status_code==422,(app,case['name'],response.status_code,response.text)
        for raw in fixture['invalid_json']:
            response=client.post('/api/jobs',content=raw,headers={'Content-Type':'application/json','Idempotency-Key':'malformed-'+uuid4().hex})
            assert response.status_code==422,(app,'malformed JSON',response.status_code,response.text)
        for bad_control in (None,True,1,[],{'unknown':True}):
            response=client.post('/api/control/hold',content=json.dumps(bad_control),headers={'Content-Type':'application/json'})
            assert response.status_code==422,(app,'invalid control',bad_control,response.status_code,response.text)
        for key in ('boundary:external','synthetic:external','synthetic-sample:external'):
            assert client.post('/api/jobs',json={'due_at':due,'quantity':1},headers={'Idempotency-Key':key}).status_code==409
        assert client.post('/api/jobs',json={'due_at':due,'quantity':1}).status_code==422
        key='compatibility-'+uuid4().hex
        headers={'Idempotency-Key':key}
        body={'due_at':due,'quantity':2}
        first=client.post('/api/jobs',json=body,headers=headers,auth=employee_auth)
        assert first.status_code==200,(app,first.text)
        job=first.json();UUID(job['id'])
        assert client.post('/api/jobs',json=body,headers=headers,auth=employee_auth).json()['id']==job['id']
        assert client.post('/api/jobs',json={**body,'quantity':3},headers=headers,auth=employee_auth).status_code==409
        time.sleep(.3)
        held=client.get('/api/status').json()
        assert held['run']['granted']==current['run']['granted'] and held['effects']==current['effects']
        audit=client.get('/api/audit').json()
        accepted=[e for e in audit if e['idempotency_key']==key and e['outcome']=='accepted']
        assert len(accepted)==2 and all(e['target_id']==job['id'] and e['actor']==employee['username'] for e in accepted)
        rejected=next(e for e in audit if e['idempotency_key']==key and e['outcome']=='rejected')
        assert rejected['status_code']==409 and rejected['run_id']==current['run']['id']
        assert all(x['password'] not in json.dumps(audit) for x in identities)
        assert password not in json.dumps(audit)
        assert client.post('/api/control/resume',json={}).status_code==200
        completed=wait_for(client,'/api/status',lambda v:any(j['id']==job['id'] and j['status']=='completed' for j in v['jobs']))
        assert completed['effects']==current['effects']+2
        assert client.post('/api/jobs',json=body,headers=headers,auth=employee_auth).json()['id']==job['id']
        assert client.post('/api/control/reset',json={'confirm_run_id':str(uuid4())}).status_code==409
        assert client.post('/api/control/reset',json={'confirm_run_id':completed['run']['id']}).status_code==200
        reset=client.get('/api/status').json()
        assert reset['run']['id']!=completed['run']['id'] and reset['run']['epoch']!=completed['run']['epoch']
        assert reset['effects']==0
        print(app+': common fixtures, roles, atomic audit, hold, grant-gated execution, replay/conflict and new-epoch reset passed',flush=True)

if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--app',required=True,choices=['storage','manufacturing','logistics','shipping','twin'])
    parser.add_argument('--url',required=True)
    parser.add_argument('--terminal-reset',action='store_true')
    args=parser.parse_args()
    (verify_terminal_reset if args.terminal_reset else verify)(args.app,args.url)

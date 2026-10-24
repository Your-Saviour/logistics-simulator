import json
import os
import pytest
from fastapi.testclient import TestClient
from simulator.config import Settings
from simulator.api import create_app
from simulator.store import Store


@pytest.fixture
def secured():
    settings=Settings(database_url=os.environ['TEST_DATABASE_URL'],amqp_url='amqp://unused',password='operator-secret',identities=[
        {'username':'employee','password':'employee-secret','role':'employee'},
        {'username':'observer','password':'observer-secret','role':'service','scopes':['status:read']},
        {'username':'automation','password':'automation-secret','role':'service','scopes':['jobs:write']},
    ])
    store=Store(settings.database_url)
    store.migrate();store.control('reset')
    with TestClient(create_app(settings,store,broker_check=lambda:True)) as client:
        yield client,store


def test_employee_can_submit_but_cannot_control_or_read_audit(secured):
    client,store=secured
    client.auth=('employee','employee-secret')
    assert client.get('/api/status').status_code==200
    assert client.post('/api/jobs',json={'due_at':1,'quantity':2},headers={'Idempotency-Key':'employee-job'}).status_code==200
    for action in ('hold','resume','speed','reset','finalize'):
        assert client.post('/api/control/'+action,json={}).status_code==403
    assert client.get('/api/audit').status_code==403
    assert store.status()['run']['state']=='running'


def test_service_permissions_are_explicitly_scoped(secured):
    client,_=secured
    client.auth=('observer','observer-secret')
    assert client.get('/api/status').status_code==200
    assert client.post('/api/jobs',json={'due_at':1,'quantity':1},headers={'Idempotency-Key':'observer'}).status_code==403
    client.auth=('automation','automation-secret')
    assert client.get('/api/status').status_code==403
    assert client.post('/api/jobs',json={'due_at':1,'quantity':1},headers={'Idempotency-Key':'auto'}).status_code==200
    assert client.post('/api/control/hold',json={}).status_code==403


def test_commands_audit_validated_actor_run_request_and_rejection_without_secrets(secured):
    client,store=secured
    client.auth=('employee','employee-secret')
    response=client.post('/api/jobs',json={'due_at':1,'quantity':2},headers={'Idempotency-Key':'audited'})
    assert response.status_code==200
    assert client.post('/api/jobs',json={'due_at':1,'quantity':-5},headers={'Idempotency-Key':'invalid'}).status_code==422
    assert client.post('/api/control/reset',json={}).status_code==403
    client.auth=('operator','operator-secret')
    events=[e for e in client.get('/api/audit').json() if e['run_id']==str(store.status()['run']['id'])]
    assert len(events)==3
    accepted=next(e for e in events if e['outcome']=='accepted')
    assert accepted['actor']=='employee' and accepted['role']=='employee'
    assert accepted['run_id']==str(store.status()['run']['id'])
    assert accepted['idempotency_key']=='audited' and accepted['request_id']
    assert sorted(e['status_code'] for e in events)==[200,403,422]
    assert 'employee-secret' not in json.dumps(events)
    assert 'operator-secret' not in json.dumps(events)


def test_identities_cannot_elevate_declared_role():
    with pytest.raises(ValueError):
        Settings(password='operator',identities=[{'username':'evil','password':'secret','role':'employee','scopes':['runs:control']}])


def test_employee_cannot_claim_controller_or_peer_idempotency_namespaces(secured):
    client,store=secured
    client.auth=('employee','employee-secret')
    for key in ('synthetic:known-input','boundary:known-event','synthetic-sample:1'):
        response=client.post('/api/jobs',json={'due_at':1,'quantity':1},headers={'Idempotency-Key':key})
        assert response.status_code==409
    assert store.status()['jobs']==[]

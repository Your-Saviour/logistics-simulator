import os
from uuid import uuid4
import pytest
from simulator.config import Settings
from simulator.store import Store
from twin.api import create_app

@pytest.fixture
def setup():
    settings=Settings(app='twin',database_url=os.environ['TEST_DATABASE_URL'],amqp_url='amqp://unused',password='private-operator',identities=[
        {'username':'employee','password':'employee-secret','role':'employee'},
        {'username':'observer','password':'observer-secret','role':'service','scopes':['status:read']},
    ])
    store=Store(settings.database_url)
    store.migrate()
    with store.transaction() as db:
        db.execute("DELETE FROM heartbeats WHERE role='projection'")
    return create_app(settings,store,broker_check=lambda:True).test_client(),store


def test_independent_roles_zero_sources_and_mutation_denials(setup):
    client,store=setup
    assert client.get('/api/status').status_code==401
    employee={'Authorization':'Basic ZW1wbG95ZWU6ZW1wbG95ZWUtc2VjcmV0'}
    status=client.get('/api/status',headers=employee)
    assert status.status_code==200 and status.json['application']=='twin'
    assert status.json['identity']['role']=='employee'
    assert client.get('/api/sources',headers=employee).json==[]
    assert client.get('/api/audit',headers=employee).status_code==403
    for route in ('/api/jobs','/api/control/hold','/api/control/reset'):
        assert client.post(route,json={},headers=employee).status_code==403
    assert store.status()['effects']==0


def test_operator_mutations_audited_without_secrets(setup):
    client,store=setup
    from base64 import b64encode
    auth={'Authorization':'Basic '+b64encode(b'operator:private-operator').decode()}
    result=client.post('/api/control/reset',json={'confirm_run_id':str(uuid4())},headers=auth)
    assert result.status_code==403 and result.headers['X-Request-ID']
    events=client.get('/api/audit',headers=auth)
    assert events.status_code==200
    last=next(e for e in events.json if e['request_id']==result.headers['X-Request-ID'])
    assert last['outcome']=='rejected' and last['actor']=='operator'
    assert last['run_id']==str(store.status()['run']['id'])
    assert 'private-operator' not in events.get_data(as_text=True)


def test_readiness_requires_supervised_projection_and_broker(setup):
    client,store=setup
    assert client.get('/api/health/live').status_code==200
    assert client.get('/api/health/ready').status_code==503
    store.heartbeat('projection')
    assert client.get('/api/health/ready').status_code==200


def test_status_uses_iso_timestamps_and_source_credentials_never_exposed(setup):
    client,store=setup
    from base64 import b64encode
    headers={'Authorization':'Basic '+b64encode(b'operator:private-operator').decode()}
    status=client.get('/api/status',headers=headers).json
    assert 'T' in status['run']['anchor'] and status['run']['anchor'].endswith('Z')
    assert status['providers']=={} and status['quantum']==1
    assert 'password' not in str(status)


def test_twin_snapshot_cursor_permissions_and_reconnect(setup):
    client, store = setup
    from base64 import b64encode
    headers = {'Authorization': 'Basic ' + b64encode(b'observer:observer-secret').decode()}
    assert client.get('/api/twin').status_code == 401
    first = client.get('/api/twin', headers=headers)
    assert first.status_code == 200 and first.json['mode'] == 'live'
    assert first.json['controls'] == []
    reconnect = client.get('/api/twin/events?after=' + str(first.json['revision']), headers=headers)
    assert reconnect.status_code == 200 and reconnect.json['revision'] == first.json['revision']
    for cursor in ('-1', 'invalid', '1.5'):
        assert client.get('/api/twin/events?after=' + cursor, headers=headers).status_code == 422
    assert client.post('/api/twin/controls/hold', headers=headers).status_code in (403, 404, 405)


def test_twin_process_health_refreshes_after_login(setup):
    client,store=setup
    from base64 import b64encode
    headers={'Authorization':'Basic '+b64encode(b'observer:observer-secret').decode()}
    store.heartbeat('projection')
    assert next(h for h in client.get('/api/twin',headers=headers).json['heartbeats'] if h['role']=='projection')['healthy']
    with store.transaction() as db:
        db.execute("UPDATE heartbeats SET seen_at=clock_timestamp()-interval '30 seconds' WHERE role='projection'")
    assert not next(h for h in client.get('/api/twin',headers=headers).json['heartbeats'] if h['role']=='projection')['healthy']

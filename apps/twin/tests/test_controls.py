"""Opt-in routing never grants observers command authority."""
import json
import os
from base64 import b64encode
from uuid import uuid4
import httpx
import pytest
from simulator.config import Settings
from simulator.store import Store
from twin.api import create_app


def auth(user='operator', password='private'):
    return {'Authorization': 'Basic ' + b64encode(f'{user}:{password}'.encode()).decode(), 'Idempotency-Key': str(uuid4())}


def test_configured_controls_require_operator_and_explicit_owner_ack(monkeypatch):
    targets = [{'name': 'owner', 'label': 'Federation owner', 'scope': 'federation',
                'url': 'http://owner:8000', 'username': 'service', 'password': 'owner-secret',
                'actions': ['pause', 'resume']}]
    monkeypatch.setenv('TWIN_CONTROL_TARGETS', json.dumps(targets))
    settings = Settings(app='twin',database_url=os.environ['TEST_DATABASE_URL'],amqp_url='amqp://unused',password='private',
                        identities=[{'username':'observer','password':'observer','role':'service','scopes':['status:read']}])
    replies = [{'accepted': True}, {'global_pause_acknowledged': True}]
    def owner(request):
        assert request.url.path == '/api/control/pause'
        assert request.headers.get('Idempotency-Key')
        return httpx.Response(200, json=replies.pop(0))
    with httpx.Client(transport=httpx.MockTransport(owner)) as upstream:
        client = create_app(settings, Store(settings.database_url), broker_check=lambda:True, control_client=upstream).test_client()
        assert client.get('/api/twin',headers=auth('observer','observer')).json['controls'] == []
        assert len(client.get('/api/twin',headers=auth()).json['controls']) == 1
        route = '/api/twin/controls/owner/pause'
        assert client.post(route,headers=auth('observer','observer'),json={}).status_code == 403
        first = client.post(route,headers=auth(),json={})
        assert first.status_code == 200 and not first.json['acknowledged']
        assert 'not acknowledged' in first.json['message']
        second = client.post(route,headers=auth(),json={})
        assert second.json['acknowledged'] and second.json['scope'] == 'federation'
        assert 'owner-secret' not in second.get_data(as_text=True)
        assert client.post('/api/twin/controls/owner/reset',headers=auth(),json={}).status_code == 404


def test_controls_are_disabled_by_default_and_invalid_targets_fail_closed(monkeypatch):
    settings = Settings(app='twin',database_url=os.environ['TEST_DATABASE_URL'],amqp_url='amqp://unused',password='private')
    store = Store(settings.database_url)
    client = create_app(settings, store, broker_check=lambda:True).test_client()
    assert client.post('/api/twin/controls/missing/hold',headers=auth(),json={}).status_code == 404
    monkeypatch.setenv('TWIN_CONTROL_TARGETS', '[{"name":"bad","url":"http://user:secret@owner"}]')
    with pytest.raises(ValueError): create_app(settings,store,broker_check=lambda:True)


def test_local_controls_fence_source_identity_and_report_owner_state(monkeypatch):
    from twin.projection import ProjectionStore
    monkeypatch.setenv('TWIN_CONTROL_TARGETS', json.dumps([{'name':'storage','scope':'local','source':'storage',
        'url':'http://storage-api:8000','username':'controller','password':'private-control','actions':['hold','resume']}]))
    config = {'name':'storage','url':'http://storage-api:8000','username':'observer','password':'private-observer'}
    monkeypatch.setenv('TWIN_SOURCES',json.dumps([config]))
    settings=Settings(app='twin',database_url=os.environ['TEST_DATABASE_URL'],amqp_url='amqp://unused',password='private')
    store=Store(settings.database_url)
    run={'id':str(uuid4()),'epoch':str(uuid4()),'granted':5,'requested':6,'committed':5,'state':'running'}
    def owner(request):
        assert json.loads(request.content)=={'run_id':run['id'],'epoch':run['epoch']}
        return httpx.Response(200,json={'run':{**run,'state':'held'}})
    with httpx.Client(transport=httpx.MockTransport(owner)) as upstream:
        client=create_app(settings,store,broker_check=lambda:True,control_client=upstream).test_client()
        projection=ProjectionStore(store)
        # Test database may retain earlier source scopes; use a fresh epoch.
        projection.accept(config,{'version':1,'source':'storage','cursor':'control-fixture','run':run,'snapshot':{},'events':[]})
        route='/api/twin/controls/storage/hold'
        assert client.post(route,headers=auth(),json={'run_id':run['id'],'epoch':str(uuid4())}).status_code==409
        good=client.post(route,headers=auth(),json={'run_id':run['id'],'epoch':run['epoch']})
        assert good.status_code==200 and good.json['acknowledged']
        assert good.json['scope']=='local' and 'other simulators may continue' in good.json['message']
        projection.failure('storage')
        assert client.post(route,headers=auth(),json={'run_id':run['id'],'epoch':run['epoch']}).status_code==409

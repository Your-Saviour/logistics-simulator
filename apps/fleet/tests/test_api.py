from fleet.api import create_app
from psycopg.types.json import Jsonb
from test_store import store, command


def client(store):
    return create_app(store, {'storage': 'storage-secret', 'shipping': 'shipping-secret', 'observer': 'observer-secret'}).test_client()


def auth(name='storage'):
    return {'Authorization': f'Bearer {name}-secret'}


def test_observer_cannot_admit_and_department_cannot_impersonate_owner(store):
    web = client(store)
    body = command(store)
    assert web.post('/v1/jobs', json=body).status_code == 401
    assert web.post('/v1/jobs', json=body, headers=auth('observer')).status_code == 403
    assert web.post('/v1/jobs', json=body, headers=auth('shipping')).status_code == 403
    assert web.post('/v1/jobs', json=body, headers=auth()).status_code == 201
    assert web.post('/v1/jobs', json=body, headers=auth()).status_code == 200
    assert len(store.snapshot()['jobs']) == 1


def test_snapshot_is_authenticated_and_exposes_no_tokens(store):
    web = client(store)
    assert web.get('/v1/snapshot').status_code == 401
    response = web.get('/v1/snapshot', headers=auth('observer'))
    assert response.status_code == 200
    assert response.json['mode'] == 'operational'
    assert not response.json['run']['fresh']
    assert 'secret' not in response.text


def test_job_read_authority_and_malformed_requests(store):
    web = client(store)
    body = command(store)
    assert web.post('/v1/jobs', json=body, headers=auth()).status_code == 201
    assert web.get('/v1/jobs/' + body['id'], headers=auth()).status_code == 200
    assert web.get('/v1/jobs/' + body['id'], headers=auth('shipping')).status_code == 403
    assert web.post('/v1/jobs', json=[], headers=auth()).status_code == 400
    assert web.post('/v1/jobs', json={**body, 'password': 'bad'}, headers=auth()).status_code == 400
    assert web.post('/v1/jobs/' + body['id'] + '/proofs/departure', json={}, headers=auth()).status_code == 400


def test_nonstring_endpoints_return_bad_request_without_creating_jobs(store):
    web = client(store)
    for field in ('origin', 'destination'):
        for value in ([], {}, None, 12):
            assert web.post('/v1/jobs', json=command(store, **{field: value}), headers=auth()).status_code == 400
    assert store.snapshot()['jobs'] == []


def test_completed_route_history_stays_available_without_bloating_live_snapshots(store):
    body=command(store)
    store.admit(body)
    route={'resources':['cell:1:1','cell:1:2'],'poses':[[2,2,0],[2,3,0]]}
    with store.transaction() as db:
        db.execute("UPDATE fleet_jobs SET state='completed',route=%s WHERE id=%s",(Jsonb(route),body['id']))
    live=client(store).get('/v1/snapshot',headers=auth('observer')).json
    assert live['jobs'][0]['route'] is None
    history=client(store).get('/v1/jobs/'+body['id'],headers=auth()).json
    assert history['route']==route

import os

import pytest
from fastapi.testclient import TestClient

from simulator.config import Settings
from simulator.store import Store
from simulator.api import create_app


@pytest.fixture
def client():
    settings = Settings(database_url=os.environ['TEST_DATABASE_URL'], amqp_url='amqp://unused', password='test-password')
    store = Store(settings.database_url)
    store.migrate()
    store.control('reset')
    with TestClient(create_app(settings, store, broker_check=lambda: True)) as client:
        yield client


def test_status_requires_this_application_identity(client):
    assert client.get('/api/status').status_code == 401
    assert client.get('/api/status', auth=('operator', 'wrong')).status_code == 401
    assert client.get('/api/status', auth=('operator', 'test-password')).json()['application'] == 'storage'


def test_commands_validate_and_return_conflicting_keys(client):
    client.auth = ('operator', 'test-password')
    assert client.post('/api/jobs', json={'due_at': 1, 'quantity': 1}).status_code == 422
    body = {'due_at': 1, 'quantity': 2}
    headers = {'Idempotency-Key': 'example'}
    response = client.post('/api/jobs', json=body, headers=headers)
    assert response.status_code == 200
    assert response.json()['payload']['quantity'] == 2
    body['quantity'] = 3
    assert client.post('/api/jobs', json=body, headers=headers).status_code == 409
    assert client.post('/api/jobs', json={'due_at': 1, 'quantity': -1}, headers={'Idempotency-Key': 'bad'}).status_code == 422


def test_twin_has_no_business_control():
    settings = Settings(app='twin', database_url=os.environ['TEST_DATABASE_URL'], amqp_url='amqp://unused', password='test-password')
    with TestClient(create_app(settings, Store(settings.database_url), broker_check=lambda: True)) as client:
        client.auth = ('operator', 'test-password')
        assert client.post('/api/control/hold', json={}).status_code == 403
        assert client.post('/api/jobs', json={'due_at': 1, 'quantity': 1}, headers={'Idempotency-Key': 'x'}).status_code == 403
        assert client.get('/api/sources').json() == []


def test_readiness_fails_when_dependencies_unavailable():
    settings = Settings(database_url=os.environ['TEST_DATABASE_URL'], amqp_url='amqp://unused', password='test-password')
    with TestClient(create_app(settings, Store(settings.database_url), broker_check=lambda: False)) as client:
        assert client.get('/api/health/live').status_code == 200
        assert client.get('/api/health/ready').status_code == 503


def test_idempotency_replay_still_returns_original_after_time_advances(client):
    client.auth = ('operator', 'test-password')
    headers = {'Idempotency-Key': 'replay-after-grant'}
    body = {'due_at': 1, 'quantity': 2}
    first = client.post('/api/jobs', json=body, headers=headers)
    Store(os.environ['TEST_DATABASE_URL']).grant(3)
    replay = client.post('/api/jobs', json=body, headers=headers)
    assert replay.status_code == 200
    assert replay.json()['id'] == first.json()['id']

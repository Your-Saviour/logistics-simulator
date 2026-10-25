import base64
from copy import deepcopy
from uuid import uuid4

import httpx
import pytest

from fleet.sources import poll_sources


def fixture():
    native = {'run_id': str(uuid4()), 'epoch': str(uuid4()), 'offset': 0}
    run = {'id': str(uuid4()), 'epoch': str(uuid4()), 'sources': {'storage': native}}
    config = [{'name': 'storage', 'url': 'http://storage.internal', 'username': 'fleet-reader', 'password': 'private-secret'}]
    unit = {'id': str(uuid4()), 'run_id': native['run_id'], 'epoch': native['epoch'], 'owner': 'storage', 'state': 'available', 'position': 'storage.rack01.level01'}
    body = {'version': 1, 'source': 'storage', 'cursor': 'cursor-1', 'run': {'id': native['run_id'], 'epoch': native['epoch'], 'committed': 12.5, 'granted': 14, 'state': 'running'},
            'snapshot': {'handling': {'fleet': {'mode': 'coordinated', 'run_id': run['id'], 'epoch': run['epoch']}, 'units': [unit]}}}
    return config, run, body


def test_private_authenticated_projection_and_actual_native_observation():
    configurations, run, body = fixture()
    def respond(request):
        assert str(request.url) == 'http://storage.internal/api/projection'
        assert request.headers['authorization'] == 'Basic ' + base64.b64encode(b'fleet-reader:private-secret').decode()
        return httpx.Response(200, json=body)
    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        observations = poll_sources(client, configurations, run, now=100)
    current = observations['storage']
    assert current == {'run_id': body['run']['id'], 'epoch': body['run']['epoch'], 'committed': 12.5, 'granted': 14, 'state': 'running', 'cursor': 'cursor-1', 'received_at': 100,
                       'placed_units': [{'unit_id': body['snapshot']['handling']['units'][0]['id'], 'position': 'storage.rack01.level01'}]}
    assert all(secret not in repr(observations) for secret in ['private-secret', 'fleet-reader', 'storage.internal'])


@pytest.mark.parametrize('change', [
    lambda b: b.update(version=2), lambda b: b.update(source='shipping'),
    lambda b: b['snapshot']['handling']['fleet'].update(mode='disabled'),
    lambda b: b['snapshot']['handling']['fleet'].update(epoch=str(uuid4())),
    lambda b: b['run'].update(epoch=str(uuid4())),
    lambda b: b['snapshot']['handling'].update(units=None),
])
def test_mismatched_or_malformed_sources_are_omitted(change):
    configurations, run, body = fixture()
    change(body)
    with httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, json=body))) as client:
        assert poll_sources(client, configurations, run) == {}


def test_partial_timeout_or_malformed_json_does_not_discard_healthy_source():
    configurations, run, body = fixture()
    for name in ['shipping', 'manufacturing']:
        run['sources'][name] = {'run_id': str(uuid4()), 'epoch': str(uuid4()), 'offset': 0}
        configurations.append({'name': name, 'url': f'http://{name}.internal', 'username': 'reader', 'password': 'secret'})
    def respond(request):
        if request.url.host == 'shipping.internal':
            raise httpx.ReadTimeout('private failure detail', request=request)
        if request.url.host == 'manufacturing.internal':
            return httpx.Response(200, text='{bad')
        return httpx.Response(200, json=body)
    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        assert set(poll_sources(client, configurations, run)) == {'storage'}


def test_only_current_owned_confirmed_units_are_physical_obstacles():
    configurations, run, body = fixture()
    units = body['snapshot']['handling']['units']
    reserved = {**units[0], 'id': str(uuid4()), 'state': 'reserved', 'position': 'storage.outbound.dock01'}
    units.extend([reserved, {**reserved, 'state': 'in_transit', 'position': None},
                  {**reserved, 'epoch': str(uuid4())}, {**reserved, 'owner': 'shipping'},
                  {**reserved, 'state': 'dispatched', 'position': None}])
    body['run']['committed'] = -1  # Numeric clock eligibility belongs to authorized_time.
    with httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, json=body))) as client:
        observation = poll_sources(client, configurations, run)['storage']
    assert observation['committed'] == -1
    assert observation['placed_units'] == [{'unit_id': units[0]['id'], 'position': units[0]['position']}, {'unit_id': reserved['id'], 'position': reserved['position']}]


@pytest.mark.parametrize('url', ['file:///tmp/state', 'http://user:secret@source', 'http://source?token=secret', 'http://source/#secret'])
def test_invalid_configuration_is_rejected_before_http(url):
    configurations, run, _ = fixture()
    configurations[0]['url'] = url
    with httpx.Client(transport=httpx.MockTransport(lambda r: pytest.fail('Invalid configuration made HTTP request'))) as client:
        with pytest.raises(ValueError):
            poll_sources(client, configurations, run)


def test_duplicate_or_missing_participants_are_rejected():
    configurations, run, _ = fixture()
    with httpx.Client() as client:
        for invalid in [configurations * 2, []]:
            with pytest.raises(ValueError):
                poll_sources(client, invalid, run)


def test_stream_limit_omits_oversized_source():
    configurations, run, _ = fixture()
    class Oversized(httpx.SyncByteStream):
        def __iter__(self):
            for _ in range(33):
                yield b' ' * (1024 * 1024)
    with httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, stream=Oversized()))) as client:
        assert poll_sources(client, configurations, run) == {}


def test_four_sources_poll_concurrently_and_redirects_never_receive_credentials():
    from threading import Barrier
    configurations, run, original = fixture()
    barrier = Barrier(4, timeout=2)
    bodies = {'storage': original}
    for name in ['shipping', 'manufacturing', 'logistics']:
        native = {'run_id': str(uuid4()), 'epoch': str(uuid4()), 'offset': 0}
        run['sources'][name] = native
        configurations.append({'name': name, 'url': f'http://{name}.internal', 'username': 'reader', 'password': 'secret'})
        body = deepcopy(original)
        body.update(source=name)
        body['run'].update(id=native['run_id'], epoch=native['epoch'])
        body['snapshot']['handling']['units'] = []
        bodies[name] = body
    def respond(request):
        name = request.url.host.split('.')[0]
        barrier.wait()
        return httpx.Response(200, json=bodies[name])
    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        assert set(poll_sources(client, configurations, run)) == set(run['sources'])
    requests = []
    def redirect(request):
        requests.append(request)
        return httpx.Response(302, headers={'location': 'http://unexpected.internal/private'})
    configurations, run, _ = fixture()
    with httpx.Client(transport=httpx.MockTransport(redirect), follow_redirects=True) as client:
        assert poll_sources(client, configurations, run) == {}
    assert len(requests) == 1


@pytest.mark.parametrize('field,value', [('username', ''), ('password', None), ('name', 'twin')])
def test_invalid_department_credentials_never_make_http(field, value):
    configurations, run, _ = fixture()
    configurations[0][field] = value
    with httpx.Client(transport=httpx.MockTransport(lambda r: pytest.fail('Invalid credentials made HTTP request'))) as client:
        with pytest.raises(ValueError):
            poll_sources(client, configurations, run)

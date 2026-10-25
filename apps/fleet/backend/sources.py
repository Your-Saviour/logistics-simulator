"""Private departmental observations; an absent observation freezes fleet time."""
from concurrent.futures import ThreadPoolExecutor
import json
import time
from urllib.parse import urlsplit
from uuid import UUID

import httpx


MAX_RESPONSE_BYTES = 32 * 1024 * 1024
DEPARTMENTS = frozenset({'storage', 'manufacturing', 'logistics', 'shipping'})


def _uuid(value):
    if not isinstance(value, str):
        raise ValueError('Expected UUID string')
    UUID(value)
    return value


def _configuration(configurations, expected_run):
    if not isinstance(expected_run, dict):
        raise ValueError('Expected fleet run')
    _uuid(expected_run.get('id'))
    _uuid(expected_run.get('epoch'))
    expected = expected_run.get('sources')
    if not isinstance(expected, dict) or not expected or not set(expected) <= DEPARTMENTS:
        raise ValueError('Explicit departmental source mappings required')
    for scope in expected.values():
        if not isinstance(scope, dict):
            raise ValueError('Expected native scope')
        _uuid(scope.get('run_id'))
        _uuid(scope.get('epoch'))
    if not isinstance(configurations, (list, tuple)):
        raise ValueError('Expected source configurations')
    seen = set()
    result = []
    for source in configurations:
        if not isinstance(source, dict):
            raise ValueError('Expected source configuration')
        name = source.get('name')
        if not isinstance(name, str) or name not in expected or name in seen:
            raise ValueError('Unknown or duplicate source')
        if any(not isinstance(source.get(key), str) or not source[key] for key in ('url', 'username', 'password')):
            raise ValueError('Source URL and private reader credentials required')
        url = urlsplit(source['url'])
        if (url.scheme not in ('http', 'https') or not url.hostname or url.username is not None or
                url.password is not None or url.query or url.fragment or '?' in source['url'] or '#' in source['url']):
            raise ValueError('Source URL must be private HTTP(S) without embedded credentials, query or fragment')
        # Access validates malformed ports before any network request.
        if url.port is not None and not 0 < url.port < 65536:
            raise ValueError('Invalid source port')
        seen.add(name)
        result.append(dict(source))
    if seen != set(expected):
        raise ValueError('Source configurations must match all fleet participants')
    return result


def _observation(body, name, expected_run, received_at):
    if not isinstance(body, dict) or type(body.get('version')) is not int or body['version'] != 1 or body.get('source') != name:
        raise ValueError('Mismatched departmental projection')
    run = body['run']
    native = expected_run['sources'][name]
    if not isinstance(run, dict) or _uuid(run['id']) != native['run_id'] or _uuid(run['epoch']) != native['epoch']:
        raise ValueError('Mismatched native scope')
    handling = body['snapshot']['handling']
    fleet = handling['fleet']
    if (not isinstance(fleet, dict) or fleet.get('mode') != 'coordinated' or
            fleet.get('run_id') != expected_run['id'] or fleet.get('epoch') != expected_run['epoch']):
        raise ValueError('Mismatched coordinated fleet scope')
    if not isinstance(body['cursor'], str) or not body['cursor'] or not isinstance(run['state'], str):
        raise ValueError('Malformed source cursor or execution state')
    units = handling['units']
    if not isinstance(units, list):
        raise ValueError('Whole-unit placement list required')
    placed = []
    identities = set()
    for unit in units:
        if not isinstance(unit, dict):
            raise ValueError('Malformed handling unit')
        if unit.get('state') not in ('available', 'reserved'):
            continue
        if any(field not in unit for field in ('run_id', 'epoch', 'owner')):
            raise ValueError('Placed unit requires explicit native scope and owner')
        if unit['run_id'] != run['id'] or unit['epoch'] != run['epoch'] or unit['owner'] != name:
            continue
        identity = _uuid(unit['id'])
        if identity in identities or not isinstance(unit['position'], str) or not unit['position']:
            raise ValueError('Malformed or duplicate confirmed placement')
        identities.add(identity)
        placed.append({'unit_id': identity, 'position': unit['position']})
    # Clock values are preserved exactly. authorized_time owns numeric eligibility,
    # monotonicity, offsets, execution-state and freshness validation.
    return {'run_id': run['id'], 'epoch': run['epoch'], 'committed': run['committed'],
            'granted': run['granted'], 'state': run['state'], 'cursor': body['cursor'],
            'received_at': received_at, 'placed_units': placed}


def poll_sources(client, configurations, expected_run, now=None):
    """Poll all explicit participants concurrently; omit any failed observation.

    Invalid local configuration raises ValueError before HTTP. Dependency failures
    return partial observations, which cannot authorize a fleet clock advance.
    """
    sources = _configuration(configurations, expected_run)

    def poll(source):
        try:
            with client.stream('GET', source['url'].rstrip('/') + '/api/projection',
                               auth=httpx.BasicAuth(source['username'], source['password']),
                               follow_redirects=False) as response:
                response.raise_for_status()
                size = response.headers.get('content-length')
                if size is not None and (int(size) < 0 or int(size) > MAX_RESPONSE_BYTES):
                    return None
                data = bytearray()
                for chunk in response.iter_bytes(chunk_size=64 * 1024):
                    if len(data) + len(chunk) > MAX_RESPONSE_BYTES:
                        return None
                    data.extend(chunk)
                body = json.loads(data)
            return _observation(body, source['name'], expected_run, time.time() if now is None else now)
        except (httpx.HTTPError, ValueError, TypeError, KeyError, AttributeError, RecursionError):
            return None

    with ThreadPoolExecutor(max_workers=4) as executor:
        values = executor.map(poll, sources)
        return {source['name']: value for source, value in zip(sources, values) if value is not None}

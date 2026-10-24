"""Explicit opt-in forwarding; Twin never owns a business or federation clock."""
import re
import httpx
from .projection import safe_url, NAMES


def targets(values):
    if not isinstance(values, list):
        raise ValueError('TWIN_CONTROL_TARGETS must be a list')
    result = {}
    for value in values:
        if not isinstance(value, dict) or not re.fullmatch(r'[a-z][a-z0-9_-]{0,63}', value.get('name', '')):
            raise ValueError('Named control target required')
        scope = value.get('scope')
        allowed = {'hold', 'resume'} if scope == 'local' else {'pause', 'resume'} if scope == 'federation' else set()
        actions = value.get('actions')
        if not allowed or not isinstance(actions, list) or not actions or not set(actions) <= allowed:
            raise ValueError('Explicit control scope and permitted actions required')
        if scope == 'local' and value.get('source') not in NAMES:
            raise ValueError('Local control requires its source')
        if not all(isinstance(value.get(k), str) and value[k] for k in ('username', 'password')) or value['name'] in result:
            raise ValueError('Unique control target and dedicated credentials required')
        result[value['name']] = {**value, 'url': safe_url(value['url'])}
    return result


def public_targets(values):
    return [{key: value.get(key) for key in ('name', 'scope', 'source', 'actions')} |
            {'label': value.get('label', value['name'])} for value in values.values()]


def forward(target, action, body, key, client=None):
    def send(http):
        response = http.post(target['url'] + '/api/control/' + action, json=body,
                             headers={'Idempotency-Key': key},
                             auth=(target['username'], target['password']))
        if not 200 <= response.status_code < 300:
            return {'detail': 'Owner rejected the control; refresh source state before retrying'}, response.status_code if response.status_code in (400, 403, 409, 422) else 502
        value = response.json()
        if not isinstance(value, dict): raise ValueError('Owner response must be an object')
        if target['scope'] == 'federation':
            field = 'global_pause_acknowledged' if action == 'pause' else 'global_resume_acknowledged'
            acknowledged = response.status_code == 200 and value.get(field) is True
            message = ('Federation owner acknowledged global ' + action) if acknowledged else ('Global ' + action + ' requested; not acknowledged by federation owner')
        else:
            run = value.get('run', value)
            expected = 'held' if action == 'hold' else 'running'
            acknowledged = (response.status_code == 200 and run.get('id') == body['run_id'] and
                            run.get('epoch') == body['epoch'] and run.get('state') == expected)
            message = ('Local ' + action + ' acknowledged; other simulators may continue') if acknowledged else ('Local ' + action + ' requested; owner state not acknowledged')
        return {'scope': target['scope'], 'action': action, 'acknowledged': acknowledged, 'message': message}, 200
    try:
        if client is not None: return send(client)
        with httpx.Client(timeout=5, follow_redirects=False) as http: return send(http)
    except (httpx.HTTPError, ValueError, TypeError):
        return {'detail': 'Owner response unavailable; outcome unknown. Retry only with the same idempotency key.'}, 502

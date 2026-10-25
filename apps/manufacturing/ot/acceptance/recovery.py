"""Recovery phases run by the guarded disposable-deployment acceptance script."""
from client import *
from pathlib import Path
import sys

ARTIFACT = Path('/artifacts/old-equipment-command.json')


def equipment(path, body=None, expected=200):
    data = None if body is None else json.dumps(body).encode()
    request = urllib.request.Request('http://manufacturing-equipment:8010' + path, data=data,
        headers={'Authorization': 'Bearer ' + os.environ['OT_EQUIPMENT_TOKEN'], 'Content-Type': 'application/json'})
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            status, result = response.status, json.load(response)
    except urllib.error.HTTPError as error:
        status, result = error.code, json.load(error)
    assert status == expected, (status, result)
    return result


def reset():
    old = scope()
    control('reset', {'confirm_run_id': old['run_id']})
    assert scope()['epoch'] != old['epoch']
    return old


def main(phase):
    if phase == 'replay':
        until(lambda: api('/api/ot')['cell'] and api('/api/ot')['cell']['settled'] > 0, 'initial equipment step')
        control('hold')
        until(lambda: api('/api/ot')['cell']['settled'] == int(api('/api/status')['run']['granted']), 'hold settles admitted steps')
        until(lambda: equipment('/v1/status')['simulation_time'] > 0, 'at least one settled logical step')
        state = equipment('/v1/status')
        assert state['simulation_time'] > 0
        body = {'version': '1.0', **state['scope'], 'command_id': str(uuid.uuid5(uuid.UUID(state['scope']['session_id']), 'step:' + str(state['simulation_time']))),
                'operation': 'step', 'payload': {'simulation_time': state['simulation_time'], 'power_available': True}}
        first = equipment('/v1/commands', body)
        assert equipment('/v1/commands', body) == first
        assert equipment('/v1/status')['simulation_time'] == state['simulation_time']
        equipment('/v1/commands', {**body, 'payload': {**body['payload'], 'power_available': False}}, 409)
        ARTIFACT.write_text(json.dumps(body))
        print('PASS: duplicate physical step replays once; changed-body replay conflicts')
    elif phase == 'disconnected':
        until(lambda: api('/api/ot')['stale'], 'disconnected equipment becomes stale', 45)
        print('PASS: equipment disconnect becomes stale')
    elif phase == 'restarted':
        until(lambda: equipment('/v1/status')['recovery_required'], 'restarted journal requires recovery')
        until(lambda: api('/api/status')['run']['state'] == 'stalled', 'controller fences unknown physical state')
        assert all(item['status'] == 'completed' for item in api('/api/production')['orders'])
        reset()
        print('PASS: restart stalls the old epoch; confirmed reset archives it')
    elif phase == 'new-epoch':
        until(lambda: not api('/api/ot')['stale'], 'fresh epoch initializes stopped cell')
        old = json.loads(ARTIFACT.read_text())
        equipment('/v1/commands', old, 409)
        api('/api/ot/commands', {**old['payload'], 'action': 'start', 'run_id': old['run_id'], 'epoch': old['epoch']}, str(uuid.uuid4()), expected=422)
        api('/api/ot/commands', {'action': 'start', 'run_id': old['run_id'], 'epoch': old['epoch']}, str(uuid.uuid4()), expected=409)
        production = api('/api/production')
        assert not production['orders'] and not production['events']
        control('hold')
        until(lambda: api('/api/ot')['cell']['settled'] == int(api('/api/status')['run']['granted']), 'fresh held settlement')
        control('finalize')
        until(lambda: api('/api/status')['run']['state'] == 'finalized', 'physical stop acknowledgement before finalization')
        state = equipment('/v1/status')
        assert state['finalized'] and not state['cell']['enabled'] and not state['actuators']['conveyor'] and not state['actuators']['cycle']
        reset()
        until(lambda: not api('/api/ot')['stale'], 'live standalone controller handles terminal reset')
        assert not equipment('/v1/status')['cell']['enabled']
        print('PASS: old scopes fenced; fresh epoch starts empty; finalization stops PLC; terminal reset works')
    elif phase == 'controller-restarted':
        until(lambda: api('/api/status')['run']['state'] == 'stalled', 'new controller owner cannot reconstruct active epoch')
        reset()
        print('PASS: controller restart fences the prior session')
    elif phase == 'reset':
        reset()
    else:
        raise ValueError(phase)


if __name__ == '__main__':
    main(sys.argv[1])

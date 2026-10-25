import os
from copy import deepcopy
from uuid import uuid4

import pytest
from simulator.store import Store
from twin.fleet_projection import FleetProjection, validate_fleet


def snapshot():
    return {'version': 1, 'mode': 'operational',
            'run': {'id': str(uuid4()), 'epoch': str(uuid4()), 'revision': 2, 'committed': 10,
                    'state': 'running', 'fresh': True, 'reason': None, 'sources': {}},
            'robots': [{'id': 'robot-01', 'pose': [2, 3, 0], 'parking': [2, 3, 0],
                        'job_id': None, 'carried_unit_id': None, 'fork_height': .15, 'fork_offset': [0, 0]}],
            'jobs': [], 'reservations': [], 'events': []}


def test_fleet_validator_rejects_duplicate_robot_and_nonfinite_or_unknown_pose():
    value = snapshot()
    validate_fleet(value)
    for transform in (lambda v: v['robots'].append(v['robots'][0]),
                      lambda v: v['robots'][0].update(pose=[float('nan'), 3, 0]),
                      lambda v: v['robots'][0].update(pose=[2, 3, 9])):
        broken = deepcopy(value)
        transform(broken)
        with pytest.raises(ValueError):
            validate_fleet(broken)


@pytest.fixture
def fleet():
    store = Store(os.environ['TEST_DATABASE_URL'])
    store.migrate()
    with store.transaction() as db:
        db.execute('TRUNCATE twin_fleet')
    result = FleetProjection(store)
    result.configure({'url': 'http://fleet-api:8000', 'token': 'private-fleet-observer'})
    return result


def test_reversed_revision_or_scope_cannot_replace_reported_poses(fleet):
    value = snapshot()
    fleet.accept(value)
    stale = deepcopy(value)
    stale['run']['revision'] = 1
    stale['robots'][0]['pose'] = [99, 3, 0]
    with pytest.raises(ValueError):
        fleet.accept(stale)
    assert fleet.view()['snapshot']['robots'][0]['pose'] == [2, 3, 0]
    fleet.failure()
    assert fleet.view()['stale'] and fleet.view()['snapshot']['robots'][0]['pose'] == [2, 3, 0]
    assert 'private-fleet-observer' not in str(fleet.view())


def test_equal_revision_cannot_change_physical_snapshot(fleet):
    value = snapshot()
    fleet.accept(value)
    changed = deepcopy(value)
    changed['robots'][0]['pose'] = [4, 3, 0]
    with pytest.raises(ValueError):
        fleet.accept(changed)
    fleet.accept(value)


def test_retired_scope_cannot_return_after_epoch_replacement(fleet):
    value = snapshot()
    fleet.accept(value)
    replacement = deepcopy(value)
    replacement['run']['epoch'] = str(uuid4())
    replacement['run']['revision'] = 3
    fleet.accept(replacement)
    with pytest.raises(ValueError):
        fleet.accept(value)


@pytest.mark.parametrize('field', ['robots','jobs','reservations','events'])
def test_malformed_collection_members_are_contract_errors_not_projection_crashes(field):
    value = snapshot()
    value[field] = [None]
    with pytest.raises(ValueError):
        validate_fleet(value)


@pytest.mark.parametrize('position', [None, [], [1,2], [1,2,3,4], [1,float('nan'),3], ['x',2,3]])
def test_loaded_robot_requires_complete_finite_reported_transform(position):
    value = snapshot()
    job_id, unit_id = str(uuid4()), str(uuid4())
    value['robots'][0].update(job_id=job_id,carried_unit_id=unit_id,load_position=position)
    value['jobs'] = [{'id':job_id,'unit_id':unit_id,'robot_id':'robot-01','state':'carrying','carried':True}]
    with pytest.raises(ValueError):
        validate_fleet(value)

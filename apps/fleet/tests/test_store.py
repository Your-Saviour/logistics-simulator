import os
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import pytest
import psycopg

from fleet.store import FleetStore, Conflict


@pytest.fixture
def store():
    result = FleetStore(os.environ['TEST_DATABASE_URL'])
    result.migrate()
    with result.transaction() as db:
        db.execute('TRUNCATE fleet_runs CASCADE')
    result.initialize(str(uuid4()), str(uuid4()), {'storage': {'run_id': str(uuid4()), 'epoch': str(uuid4()), 'offset': 0}},
                      [{'id': 'robot-01', 'pose': [2, 2, 0]}, {'id': 'robot-02', 'pose': [2, 8, 0]}])
    return result


def command(store, **changes):
    run = store.snapshot()['run']
    return {'version': 1, 'id': str(uuid4()), 'run_id': run['id'], 'epoch': run['epoch'],
            'producer': 'storage', 'source_run_id': run['sources']['storage']['run_id'],
            'source_epoch': run['sources']['storage']['epoch'], 'unit_id': str(uuid4()),
            'origin': 'storage.raw.r01.b01.l01', 'destination': 'storage.raw.r01.b02.l01',
            'custody_generation': 0, 'effective_time': 0, **changes}


def test_exact_retries_return_original_job_but_mutated_body_conflicts(store):
    body = command(store)
    first = store.admit(body)
    assert first['id'] == store.admit(body)['id']
    with pytest.raises(Conflict):
        store.admit({**body, 'destination': 'storage.raw.r01.b03.l01'})
    assert len(store.snapshot()['jobs']) == 1


def test_active_unit_has_one_job_even_under_concurrent_admission(store):
    body = command(store)
    def attempt(index):
        try:
            return store.admit({**body, 'id': str(uuid4())})['id']
        except Conflict:
            return None
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(attempt, range(2)))
    assert sum(r is not None for r in results) == 1


def test_scope_replacement_rejects_old_commands_without_releasing_occupancy(store):
    old = command(store)
    job = store.admit(old)
    generation = store.claim_worker()
    store.assign(job['id'], 'robot-01', {'resources': ['cell:8:8'], 'poses': [[2, 2, 0]]}, generation)
    before = store.snapshot()['reservations']
    store.replace_epoch(str(uuid4()))
    with pytest.raises(Conflict):
        store.admit(old)
    assert store.snapshot()['reservations'] == before
    assert store.snapshot()['jobs'][0]['state'] == 'quarantined'


def test_reservations_and_assignment_are_atomic_and_worker_is_fenced(store):
    a, b = store.admit(command(store)), store.admit(command(store))
    generation = store.claim_worker()
    route = {'resources': ['cell:1:1', 'cell:1:2'], 'poses': [[2, 2, 0]]}
    store.assign(a['id'], 'robot-01', route, generation)
    with pytest.raises(Conflict):
        store.assign(b['id'], 'robot-02', route, generation)
    snapshot = store.snapshot()
    assert snapshot['jobs'][1]['robot_id'] is None
    assert len(snapshot['reservations']) == 2
    replacement = store.claim_worker()
    assert replacement > generation
    with pytest.raises(Conflict):
        store.assign(b['id'], 'robot-02', {'resources': ['cell:7:7'], 'poses': [[2, 8, 0]]}, generation)
    assert len(store.snapshot()['reservations']) == 2


@pytest.mark.parametrize('changes', [{'effective_time': float('nan')}, {'effective_time': True},
                                   {'custody_generation': -1}, {'unit_id': 'bad'},
                                   {'origin': 'unknown'}, {'source_epoch': str(uuid4())}])
def test_invalid_or_stale_admission_cannot_mutate_jobs(store, changes):
    with pytest.raises((ValueError, Conflict)):
        store.admit(command(store, **changes))
    assert store.snapshot()['jobs'] == []

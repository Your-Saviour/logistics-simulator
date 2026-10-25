from copy import deepcopy
from uuid import uuid4

import pytest

from fleet.navigation import Navigation
from fleet.navigation import intersects
from fleet.worker import Worker
from fleet.store import Conflict
from test_store import store, command


@pytest.fixture
def worker(store):
    nav = Navigation({'bounds': [0, 0, 16, 12], 'cell_size': .25, 'obstacles': [], 'lanes': []})
    endpoints = deepcopy(store.catalog)
    endpoints['storage.raw.r01.b01.l01'].update(position=[3.5, .45, 3], access=[5, 0, 3])
    endpoints['storage.raw.r01.b02.l01'].update(position=[10, .45, 3], access=[11.5, 0, 3])
    return Worker(store, nav, endpoints)


def tick(worker, value, state='running', now=100):
    run = worker.store.snapshot()['run']
    source = run['sources']['storage']
    observation = {**source, 'committed': value, 'granted': value, 'state': state,
                   'cursor': str(value), 'received_at': now}
    worker.tick({'storage': observation}, now=now)


def proof(worker, job, kind, effective_time=0):
    request = job['request']
    return worker.store.submit_proof(str(job['id']), kind, {
        'job_id': str(job['id']), 'unit_id': str(job['unit_id']), 'run_id': request['run_id'],
        'epoch': request['epoch'], 'source_run_id': request['source_run_id'], 'source_epoch': request['source_epoch'],
        'custody_generation': request['custody_generation'], 'endpoint': request['origin' if kind == 'departure' else 'destination'],
        'effective_time': effective_time,
    }, 'storage')


def test_future_request_and_departure_proof_cannot_move_early(worker):
    job = worker.store.admit(command(worker.store, effective_time=100))
    proof(worker, job, 'departure', 100)
    tick(worker, 10)
    snapshot = worker.store.snapshot()
    assert snapshot['jobs'][0]['state'] == 'queued'
    assert snapshot['robots'][0]['pose'] == [2, 2, 0]
    tick(worker, 100)
    assert worker.store.snapshot()['jobs'][0]['state'] == 'approaching'


def test_transport_needs_departure_and_receipt_and_restart_keeps_load(worker):
    job = worker.store.admit(command(worker.store))
    tick(worker, 0)
    tick(worker, 30)
    snapshot = worker.store.snapshot()
    assert snapshot['jobs'][0]['state'] == 'awaiting_departure'
    assert not snapshot['jobs'][0]['carried']
    proof(worker, job, 'departure', 30)
    tick(worker, 31)
    tick(worker, 40)
    snapshot = worker.store.snapshot()
    assert snapshot['jobs'][0]['carried']
    robot = snapshot['robots'][0]
    assert robot['carried_unit_id'] == str(job['unit_id'])
    assert robot['load_position'] == [robot['pose'][0], .91, robot['pose'][1]]
    pose = snapshot['robots'][0]['pose']
    replacement = Worker(worker.store, worker.navigation, worker.catalog)
    tick(replacement, 40, state='held')
    assert replacement.store.snapshot()['robots'][0]['pose'] == pose
    assert replacement.store.snapshot()['jobs'][0]['carried']
    with pytest.raises(Conflict):
        tick(worker, 36)
    tick(replacement, 60)
    assert replacement.store.snapshot()['robots'][0]['pose'] == pose
    tick(replacement, 90)
    snapshot = replacement.store.snapshot()
    assert snapshot['jobs'][0]['state'] == 'awaiting_receipt'
    assert snapshot['jobs'][0]['carried'] and snapshot['reservations']
    arrival = next(event for event in snapshot['events'] if event['kind'] == 'arrival')
    assert arrival['body']['effective_time'] >= 30
    proof(replacement, job, 'receipt', 90)
    tick(replacement, 91)
    tick(replacement, 130)
    snapshot = replacement.store.snapshot()
    assert snapshot['jobs'][0]['state'] == 'completed'
    assert snapshot['robots'][0]['pose'] == [2, 2, 0]
    assert not snapshot['jobs'][0]['carried'] and not snapshot['reservations']


def test_same_bay_queues_but_disjoint_work_can_move(worker):
    worker.store.admit(command(worker.store))
    worker.store.admit(command(worker.store))
    tick(worker, 0)
    jobs = worker.store.snapshot()['jobs']
    assert sum(job['robot_id'] is not None for job in jobs) == 1
    assert jobs[1]['waiting_reason'] == 'traffic'
    assert jobs[1]['blockers']


def test_stale_clock_retains_pose_and_all_reservations(worker):
    worker.store.admit(command(worker.store))
    tick(worker, 0)
    before = worker.store.snapshot()
    worker.tick({}, now=110)
    after = worker.store.snapshot()
    assert after['robots'] == before['robots']
    assert after['reservations'] == before['reservations']
    assert after['run']['state'] == 'held'


def test_receipt_without_arrival_or_wrong_identity_is_rejected(worker):
    job = worker.store.admit(command(worker.store))
    with pytest.raises(Conflict):
        proof(worker, job, 'receipt')
    proof(worker, job, 'departure')
    with pytest.raises(Conflict):
        proof(worker, job, 'departure', 1)


def test_disjoint_jobs_run_together_while_same_bay_waits(worker):
    for key, position in [('storage.raw.r02.b01.l01',[3.5,.45,9]),('storage.raw.r02.b02.l01',[10,.45,9])]:
        worker.catalog[key].update(position=position,access=[position[0]+1.5,0,position[2]])
    first = worker.store.admit(command(worker.store))
    blocked = worker.store.admit(command(worker.store))
    separate = worker.store.admit(command(worker.store,origin='storage.raw.r02.b01.l01',destination='storage.raw.r02.b02.l01'))
    tick(worker,0)
    jobs = {str(job['id']):job for job in worker.store.snapshot()['jobs']}
    assert jobs[str(first['id'])]['robot_id'] == 'robot-01'
    assert jobs[str(blocked['id'])]['waiting_reason'] == 'traffic'
    assert jobs[str(separate['id'])]['robot_id'] == 'robot-02'


def test_epoch_replacement_preserves_exact_loaded_pose_and_transform(worker):
    job = worker.store.admit(command(worker.store))
    tick(worker,0)
    proof(worker,job,'departure',0)
    tick(worker,10)
    before = worker.store.snapshot()
    assert before['jobs'][0]['carried']
    worker.store.replace_epoch(str(uuid4()))
    with pytest.raises(Conflict):
        worker.tick({},now=200)
    after = worker.store.snapshot()
    assert after['robots'] == before['robots']
    assert after['reservations'] == before['reservations']
    assert after['run']['state'] == 'quarantined'


def test_confirmed_other_load_blocks_pickup_service_space(worker):
    worker.store.admit(command(worker.store))
    worker.catalog['storage.inbound.dock01'].update(position=[4.5,.3,3],access=[6,0,3])
    run = worker.store.snapshot()['run']
    source = run['sources']['storage']
    worker.tick({'storage': {**source,'committed':0,'granted':0,'state':'running','cursor':'0','received_at':100,
                              'placed_units':[{'unit_id':str(uuid4()),'position':'storage.inbound.dock01'}]}},now=100)
    assert worker.store.snapshot()['jobs'][0]['state'] == 'queued'
    assert worker.store.snapshot()['jobs'][0]['waiting_reason'] == 'traffic'


def test_empty_return_route_cannot_cross_the_just_placed_load(worker):
    worker.store.admit(command(worker.store))
    tick(worker,0)
    route = worker.store.snapshot()['jobs'][0]['route']['returning']
    destination_load = (9.6,2.57,10.4,3.43)
    for pose in route['poses']:
        assert not intersects(worker.navigation._rectangle(tuple(pose)), destination_load)


def test_changed_layout_fences_recovery_without_releasing_physical_claims(worker):
    worker.store.admit(command(worker.store))
    tick(worker,0)
    before=worker.store.snapshot()
    worker.store.layout_digest='a different deployed layout'
    Worker(worker.store,worker.navigation,worker.catalog)
    after=worker.store.snapshot()
    assert after['run']['state']=='quarantined'
    assert after['robots']==before['robots']
    assert after['reservations']==before['reservations']


def test_incomplete_reservation_set_quarantines_recovery_instead_of_moving(worker):
    worker.store.admit(command(worker.store))
    tick(worker,0)
    before=worker.store.snapshot()
    with worker.store.transaction() as db:
        db.execute('DELETE FROM fleet_reservations WHERE resource=(SELECT resource FROM fleet_reservations ORDER BY resource LIMIT 1)')
    restarted=Worker(worker.store,worker.navigation,worker.catalog)
    after=worker.store.snapshot()
    assert after['run']['state']=='quarantined'
    assert after['robots']==before['robots']
    assert len(after['reservations'])==len(before['reservations'])-1
    tick(restarted,100)
    assert worker.store.snapshot()['robots']==before['robots']


def test_unmapped_confirmed_source_placement_holds_active_motion_without_crashing(worker):
    worker.store.admit(command(worker.store))
    tick(worker,0)
    before=worker.store.snapshot()
    source=before['run']['sources']['storage']
    worker.tick({'storage':{**source,'committed':20,'granted':20,'state':'running','cursor':'20','received_at':100,
                            'placed_units':[{'unit_id':str(uuid4()),'position':'unknown.endpoint'}]}},now=100)
    after=worker.store.snapshot()
    assert after['robots']==before['robots']
    assert after['run']['committed']==0
    assert after['run']['state']=='held'
    assert 'unmapped' in after['run']['reason'].lower()


def test_failed_route_is_retried_when_traffic_clears_not_on_every_clock_tick(worker):
    worker.catalog['storage.raw.r01.b01.l02'].update(position=[3.5,1.95,3],access=[5,0,3])
    first=worker.store.admit(command(worker.store))
    waiting=worker.store.admit(command(worker.store,origin='storage.raw.r01.b01.l02'))
    tick(worker,0)
    jobs={str(j['id']):j for j in worker.store.snapshot()['jobs']}
    initial=jobs[str(waiting['id'])]['planning_attempts']
    assert initial>0 and jobs[str(waiting['id'])]['state']=='queued'
    tick(worker,1)
    jobs={str(j['id']):j for j in worker.store.snapshot()['jobs']}
    assert jobs[str(waiting['id'])]['planning_attempts']==initial
    proof(worker,first,'departure',1)
    tick(worker,50)
    proof(worker,first,'receipt',50)
    tick(worker,100)
    jobs={str(j['id']):j for j in worker.store.snapshot()['jobs']}
    assert jobs[str(waiting['id'])]['planning_attempts']>initial
    assert jobs[str(waiting['id'])]['robot_id'] is not None


@pytest.mark.parametrize('phase', ['approaching', 'awaiting_departure', 'picking_up',
                                   'carrying', 'placing', 'awaiting_receipt', 'returning'])
def test_replacement_preserves_physical_state_and_proofs_in_each_active_phase(worker, phase):
    job = worker.store.admit(command(worker.store))
    for current in range(200):
        tick(worker, current)
        snapshot = worker.store.snapshot()
        active = snapshot['jobs'][0]
        if active['state'] == phase:
            break
        if active['state'] == 'awaiting_departure' and 'departure' not in active['proofs']:
            proof(worker, job, 'departure', current)
        if active['state'] == 'awaiting_receipt' and 'receipt' not in active['proofs']:
            proof(worker, job, 'receipt', current)
    else:
        pytest.fail(f'Actual execution never reached {phase}')
    fields = ('state', 'carried', 'robot_id', 'progress', 'proofs', 'route')
    physical = (snapshot['robots'], snapshot['reservations'], {key: active[key] for key in fields})
    replacement = Worker(worker.store, worker.navigation, worker.catalog)
    tick(replacement, current, state='held')
    tick(replacement, current)
    recovered = replacement.store.snapshot()
    assert (recovered['robots'], recovered['reservations'],
            {key: recovered['jobs'][0][key] for key in fields}) == physical
    with pytest.raises(Conflict):
        tick(worker, current)

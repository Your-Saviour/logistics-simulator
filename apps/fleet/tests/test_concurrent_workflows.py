"""Four simultaneous physical workflows; native custody is checked separately."""
import json
import os
from pathlib import Path
from uuid import uuid4

from fleet.initialize import validate_configuration
from fleet.navigation import Navigation
from fleet.store import FleetStore
from fleet.worker import Worker


def test_inbound_shelf_manufacturing_and_outbound_carry_simultaneously():
    store=FleetStore(os.environ['TEST_DATABASE_URL'])
    store.migrate()
    with store.transaction() as db:
        db.execute('TRUNCATE fleet_runs CASCADE')
    run_id,epoch=str(uuid4()),str(uuid4())
    scopes={name:{'run_id':str(uuid4()),'epoch':str(uuid4()),'offset':0}
            for name in ('storage','manufacturing','logistics','shipping')}
    topology=json.loads(Path('/app/contracts/fleet/v1/navigation.json').read_text())
    topology['parking']=[{'id':'robot-01','pose':[-39,26,0]},
                         {'id':'robot-02','pose':[-5.5,-20,0]},
                         {'id':'robot-03','pose':[.75,3,0]},
                         {'id':'robot-04','pose':[23.8,11,0]}]
    robots=validate_configuration(topology,4)
    store.initialize(run_id,epoch,scopes,robots)
    worker=Worker(store,Navigation(topology))
    commands=[]
    for producer,origin,destination in (
        ('logistics','logistics.inbound.truck04.slot01','logistics.inbound.dock04'),
        ('storage','storage.inbound.dock08','storage.raw.r08.b01.l01'),
        ('manufacturing','manufacturing.cell01.output04','storage.finished_receipt.dock08'),
        ('shipping','shipping.outbound.dock03','logistics.outbound.truck03.slot01')):
        body={'version':1,'id':str(uuid4()),'run_id':run_id,'epoch':epoch,'producer':producer,
              'source_run_id':scopes[producer]['run_id'],'source_epoch':scopes[producer]['epoch'],
              'unit_id':str(uuid4()),'origin':origin,'destination':destination,
              'custody_generation':0,'effective_time':0}
        store.admit(body);commands.append(body)
    def tick(value):
        worker.tick({name:{**scope,'committed':value,'granted':value,'state':'running',
                            'cursor':str(value),'received_at':100} for name,scope in scopes.items()},now=100)
    for _ in range(4):
        tick(0)  # Scheduling work is bounded independently of simulation progress.
    tick(31)
    snapshot=store.snapshot()
    assert all(job['state']=='awaiting_departure' for job in snapshot['jobs']), snapshot['jobs']
    for body in commands:
        store.submit_proof(body['id'],'departure',{'job_id':body['id'],'unit_id':body['unit_id'],
            'run_id':run_id,'epoch':epoch,'source_run_id':body['source_run_id'],'source_epoch':body['source_epoch'],
            'custody_generation':0,'endpoint':body['origin'],'effective_time':50},body['producer'])
    tick(50)
    tick(61)
    snapshot=store.snapshot()
    assert len({job['robot_id'] for job in snapshot['jobs']})==4
    assert all(job['state']=='carrying' and job['carried'] for job in snapshot['jobs']), snapshot['jobs']
    assert all(robot['carried_unit_id'] for robot in snapshot['robots'])
    resources=[row['resource'] for row in snapshot['reservations']]
    assert len(resources)==len(set(resources))

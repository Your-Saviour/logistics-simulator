"""Acceptance evidence must retain physical checks without unbounded snapshots."""
import importlib.util
import json
from pathlib import Path


def helper():
    spec=importlib.util.spec_from_file_location('fleet_factory_evidence',Path('/app/scripts/fleet_factory_evidence.py'))
    module=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def frame(resources):
    return {'run':{'revision':9,'committed':12,'state':'running'},
            'robots':[{'id':'robot-01','pose':[0,0,0],'carried_unit_id':'unit-01'}],
            'reservations':resources}


def test_large_claim_set_is_archived_once_outside_sample():
    value=frame([{'resource':f'cell:{i}:0','job_id':'job-01'} for i in range(10000)])
    sample,claims=helper().sample_frame(value)
    assert sample['reservation_count']==10000 and len(claims)==10000
    assert len(json.dumps(sample))<1000
    assert sample['robots']==value['robots']
    assert 'reservations' not in sample


def test_claim_digest_is_order_independent_and_fences_owner_changes():
    resources=[{'resource':'cell:1:0','job_id':'job-01'},{'resource':'cell:0:0','job_id':'job-02'}]
    collect=helper().sample_frame
    first,claims=collect(frame(resources))
    second,_=collect(frame(list(reversed(resources))))
    changed,_=collect(frame([{**resources[0],'job_id':'job-03'},resources[1]]))
    assert first['reservation_digest']==second['reservation_digest']
    assert first['reservation_digest']!=changed['reservation_digest']
    assert claims==[('cell:0:0','job-02'),('cell:1:0','job-01')]

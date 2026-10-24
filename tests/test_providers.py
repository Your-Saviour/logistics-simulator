import os
from datetime import datetime, timezone
from uuid import uuid4

import pytest
from simulator.scenario import Scenario, next_business_due
from simulator.providers import seeded_inputs
from simulator.config import Settings
from simulator.store import Store


def test_each_business_app_has_explicit_seeded_boundary_interfaces():
    expected={'manufacturing':{'supply','demand'},'storage':{'receiving','demand'},'logistics':{'demand','carrier'},'shipping':{'demand','receiving','carrier'}}
    for app,kinds in expected.items():
        settings=Settings(app=app)
        values=seeded_inputs(settings.providers,app,Scenario(),uuid4(),uuid4(),1,30)
        assert {value.kind for value in values}==kinds
        assert all(1<=value.quantity<=10 and value.provider=='synthetic' for value in values)


def test_seed_is_reproducible_and_helics_boundaries_never_generate_synthetic_work():
    run,epoch=uuid4(),uuid4()
    providers={'orders':'synthetic','goods':'helics','carrier':'helics'}
    first=seeded_inputs(providers,'shipping',Scenario(seed=41),run,epoch,1,30)
    again=seeded_inputs(providers,'shipping',Scenario(seed=41),run,epoch,1,30)
    assert first==again
    assert [v.boundary for v in first]==['orders']
    assert first[0].input_id!=seeded_inputs(providers,'shipping',Scenario(seed=41),run,uuid4(),1,30)[0].input_id


def test_business_hours_skip_weekend_and_use_timezone_across_dst():
    scenario=Scenario(start_at='2026-10-02T16:59:50+09:30',time_zone='Australia/Adelaide')
    due=next_business_due(scenario,after_seconds=0,minimum_delay=30)
    # DST begins on the intervening Sunday: Friday 16:59:50 +09:30 to
    # Monday 08:00 +10:30 is 62 hours and ten seconds in elapsed UTC time.
    assert due==223210
    instant=scenario.instant(due)
    assert instant.isoformat()=='2026-10-05T08:00:00+10:30'


def test_scenario_survives_restart_and_new_epoch():
    store=Store(os.environ['TEST_DATABASE_URL'])
    store.migrate();store.control('reset')
    custom=Scenario(seed=19,time_zone='UTC',start_at='2026-01-05T09:00:00Z',business_open='09:00',business_close='15:00')
    store.control('reset',scenario=custom.model_dump(mode='json'))
    previous=store.status()['run']
    restarted=Store(store.url)
    restarted.migrate()
    assert restarted.status()['run']['scenario']==custom.model_dump(mode='json')
    restarted.control('reset')
    current=restarted.status()['run']
    assert current['scenario']==previous['scenario'] and current['epoch']!=previous['epoch']


def test_invalid_scenario_is_rejected():
    with pytest.raises(ValueError): Scenario(time_zone='missing/zone')
    with pytest.raises(ValueError): Scenario(business_open='17:00',business_close='08:00')
    with pytest.raises(ValueError): Scenario(start_at='2026-01-01T08:00:00')


def test_seeded_job_rejects_old_epoch_even_if_reset_happens_before_submission():
    store=Store(os.environ['TEST_DATABASE_URL']);store.migrate();store.control('reset')
    run=store.status()['run']
    old=seeded_inputs(Settings(app='shipping').providers,'shipping',Scenario(),run['id'],run['epoch'],1,30)[0]
    store.control('reset')
    from simulator.store import Conflict
    with pytest.raises(Conflict):
        store.schedule('old-seed',30,{'quantity':old.quantity},boundary_input=old.model_dump(mode='json'))
    assert store.status()['jobs']==[]


def test_controller_seeds_only_one_batch_per_boundary_and_persists_metadata():
    store=Store(os.environ['TEST_DATABASE_URL']);store.migrate();store.control('reset')
    settings=Settings(app='shipping',mode='helics',providers={'orders':'synthetic','goods':'helics','carrier':'synthetic'})
    first=store.seed_boundaries(settings)
    assert {j['boundary_input']['kind'] for j in first}=={'demand','carrier'}
    assert store.seed_boundaries(settings)==[]
    assert len(store.status()['jobs'])==2


def test_fallback_uses_the_next_valid_repeated_business_window():
    scenario=Scenario(start_at='2026-11-01T01:44:00-04:00',time_zone='America/New_York',business_open='01:00',business_close='01:30',business_weekdays=[6])
    due=next_business_due(scenario,0,1)
    assert due==960
    assert scenario.instant(due).isoformat()=='2026-11-01T01:00:00-05:00'

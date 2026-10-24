import os
from simulator.store import Store


def test_unavailable_power_defers_sample_work_until_a_later_grant():
    store = Store(os.environ['TEST_DATABASE_URL'])
    store.migrate()
    store.control('reset')
    job = store.schedule('power-limited', 1, {'quantity': 3})
    store.grant(1, blocked_reason='External power unavailable')
    assert store.execute(job['id']) == 'waiting'
    assert store.status()['effects'] == 0
    assert store.prepare_request(2)
    store.grant(2)
    assert store.execute(job['id']) == 'completed'
    assert store.status()['effects'] == 3


def test_deferred_job_remembers_original_idempotent_request():
    store = Store(os.environ['TEST_DATABASE_URL'])
    store.migrate()
    store.control('reset')
    job = store.schedule('deferred-replay', 1, {'quantity': 3})
    store.grant(1, blocked_reason='External power unavailable')
    replay = store.schedule('deferred-replay', 1, {'quantity': 3})
    assert replay['id'] == job['id']

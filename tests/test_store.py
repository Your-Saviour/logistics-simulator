import os
from concurrent.futures import ThreadPoolExecutor

import pytest

from simulator.config import Settings
from simulator.store import Store, Conflict


@pytest.fixture
def store():
    value = Store(os.environ['TEST_DATABASE_URL'])
    value.migrate()
    value.control('reset')
    return value


def test_schedule_is_idempotent_and_payload_conflicts(store):
    first = store.schedule('one', 5, {'quantity': 2})
    assert store.schedule('one', 5, {'quantity': 2})['id'] == first['id']
    with pytest.raises(Conflict):
        store.schedule('one', 6, {'quantity': 3})


def test_grant_and_hold_prevent_early_effects(store):
    job = store.schedule('future', 5, {'quantity': 2})
    assert store.execute(job['id']) == 'waiting'
    store.grant(5)
    store.control('hold')
    assert store.execute(job['id']) == 'waiting'
    store.control('resume')
    assert store.execute(job['id']) == 'completed'
    assert store.status()['effects'] == 2


def test_restart_redelivery_and_concurrency_have_one_effect(store):
    job = store.schedule('duplicate', 1, {'quantity': 3})
    store.grant(1)
    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(lambda _: Store(store.url).execute(job['id']), range(8)))
    restarted = Store(store.url)
    assert restarted.execute(job['id']) == 'duplicate'
    assert restarted.status()['effects'] == 3
    assert restarted.status()['run']['granted'] == 1


def test_reset_fences_old_epoch(store):
    job = store.schedule('old', 1, {'quantity': 7})
    previous = store.status()['run']
    store.control('reset')
    store.grant(1)
    assert store.execute(job['id']) == 'fenced'
    assert store.status()['effects'] == 0
    assert store.status()['run']['epoch'] != previous['epoch']


def test_outstanding_work_prevents_advance_and_grants_never_reverse(store):
    job = store.schedule('blocking', 1, {'quantity': 1})
    store.grant(1)
    assert store.prepare_request(2) is False
    store.execute(job['id'])
    assert store.prepare_request(2) is True
    with pytest.raises(Conflict):
        store.grant(0)


def test_retries_are_bounded_and_terminal_failure_is_visible(store):
    job = store.schedule('bad', 1, {'quantity': 1})
    store.grant(1)
    for _ in range(3):
        store.fail_job(job['id'], 'sample failure')
    assert store.execute(job['id']) == 'dead'
    assert store.status()['jobs'][0]['status'] == 'dead'
    assert store.status()['run']['state'] == 'failed'


def test_provider_validation_has_no_silent_fallback():
    with pytest.raises(ValueError):
        Settings(app='storage', mode='helics', providers={'supply': ['synthetic', 'helics']})
    with pytest.raises(ValueError):
        Settings(app='storage', mode='helics', providers={'supply': 'synthetic'})

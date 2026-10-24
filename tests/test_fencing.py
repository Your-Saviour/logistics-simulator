import os
import pytest
from simulator.store import Store, Conflict


def test_stale_controller_cannot_grant_new_epoch():
    store = Store(os.environ['TEST_DATABASE_URL'])
    store.migrate()
    store.control('reset')
    epoch = store.status()['run']['epoch']
    store.control('reset')
    with pytest.raises(Conflict):
        store.grant(50, expected_epoch=epoch)
    assert store.status()['run']['granted'] == 0


def test_dead_controller_fails_worker_closed():
    store = Store(os.environ['TEST_DATABASE_URL'])
    store.migrate()
    store.control('reset')
    job = store.schedule('clock-down', 1, {'quantity': 2})
    store.grant(1)
    with store.connect() as db:
        db.execute("UPDATE heartbeats SET seen_at=clock_timestamp()-interval '1 minute' WHERE role='controller'")
    assert store.execute(job['id']) == 'waiting'
    assert store.status()['effects'] == 0


def test_waiting_transaction_observes_replacement_run_after_reset():
    import threading
    import time
    from concurrent.futures import ThreadPoolExecutor
    from uuid import uuid4
    store=Store(os.environ['TEST_DATABASE_URL'])
    store.migrate()
    store.control('reset')
    with store.connect() as resetting:
        previous=store._run(resetting)
        with ThreadPoolExecutor(max_workers=1) as pool:
            future=pool.submit(store.status)
            time.sleep(.1)
            resetting.execute('UPDATE runs SET current=false WHERE id=%s',(previous['id'],))
            new_id=uuid4()
            resetting.execute('INSERT INTO runs(id,epoch,mode) VALUES (%s,%s,%s)',(new_id,uuid4(),'standalone'))
            resetting.commit()
            assert future.result()['run']['id']==new_id


def test_local_hold_between_request_and_grant_prevents_advancement():
    store=Store(os.environ['TEST_DATABASE_URL'])
    store.migrate()
    store.control('reset')
    assert store.prepare_request(1)
    store.control('hold')
    store.grant(1)
    assert store.status()['run']['granted']==0

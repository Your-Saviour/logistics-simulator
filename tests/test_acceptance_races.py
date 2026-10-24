import os
from uuid import uuid4
import pytest
from simulator.config import Settings
from simulator.store import Store


@pytest.fixture
def store():
    value=Store(os.environ['TEST_DATABASE_URL']);value.migrate();value.control('reset');return value


def test_finalizing_between_seed_snapshot_and_insert_is_not_a_controller_failure(store,monkeypatch):
    original=store.schedule
    def interleave(*args,**kwargs):
        store.control('finalize')
        return original(*args,**kwargs)
    monkeypatch.setattr(store,'schedule',interleave)
    assert store.seed_boundaries(Settings(app='shipping'))==[]
    assert store.status()['run']['state']=='finalized'


def test_late_failure_does_not_overwrite_a_finalized_run(store):
    previous=store.status()['run']
    store.control('finalize')
    store.stall('A finalization raced the controller',expected_epoch=previous['epoch'])
    assert store.status()['run']['state']=='finalized'


def test_rejected_command_keeps_its_original_run_after_reset(store):
    previous=store.status()['run']
    context={'actor':'employee','role':'employee','request_id':uuid4(),'action':'POST /api/control/reset','run_id':previous['id']}
    store.control('reset')
    store.rejected_command(context,403)
    event=next(e for e in store.audit_events() if e['request_id']==context['request_id'])
    assert event['run_id']==previous['id']

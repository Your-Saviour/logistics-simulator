import os
from uuid import uuid4
import pytest
from simulator.config import Settings
from simulator.contracts import Envelope
from simulator.store import Store, Conflict
from simulator.worker import process_delivery


@pytest.fixture
def store():
    value=Store(os.environ['TEST_DATABASE_URL'])
    value.migrate()
    value.control('reset')
    return value


def test_stale_local_controller_resumes_new_run_without_stalling(store):
    from simulator.controller import grant_local
    run=store.status()['run']
    assert store.prepare_request(1,expected_epoch=run['epoch'])
    store.control('reset')
    assert grant_local(store,1,run['epoch']) is False
    assert store.status()['run']['state']=='running'


def test_reset_confirmation_is_checked_under_run_lock(store):
    run=store.status()['run']
    store.control('reset',expected_run_id=run['id'])
    with pytest.raises(Conflict):
        store.control('reset',expected_run_id=run['id'])


def test_terminal_retry_reports_dead_to_the_consumer(store):
    job=store.schedule('broken',1,{'quantity':1})
    assert store.fail_job(job['id'],'broken')=='retry'
    assert store.fail_job(job['id'],'broken')=='retry'
    assert store.fail_job(job['id'],'broken')=='dead'


def test_new_boundary_job_is_deferred_when_power_is_unavailable(store):
    store.grant(1,blocked_reason='Power unavailable')
    run=store.status()['run']
    incoming=Envelope(federation_id='test',run_id=run['id'],epoch=run['epoch'],correlation_id=uuid4(),causation_id=uuid4(),aggregate_id=uuid4(),aggregate_version=1,source='shipping',destination='manufacturing',boundary='demand',effective_time=1,payload={'quantity':3})
    store.ingest(incoming,'shipping','demand','manufacturing')
    assert store.execute(store.status()['jobs'][0]['id'])=='waiting'
    assert store.prepare_request(2)
    store.grant(2)
    assert store.execute(store.status()['jobs'][0]['id'])=='completed'


def test_partial_connected_peers_are_explicit():
    settings=Settings(app='storage',mode='helics',providers={'supply':'helics','requests':'synthetic'})
    assert settings.providers['requests']=='synthetic'


def test_malformed_job_identifier_is_rejected_without_worker_crash():
    # The broker channel is the external transport boundary. No DB call may
    # occur for malformed input; verify the consumer's disposition on it.
    class Channel:
        rejected=False
        def basic_nack(self, tag, requeue):
            assert tag==7 and requeue is False
            self.rejected=True
    class Delivery:
        delivery_tag=7
    channel=Channel()
    process_delivery(None,channel,Delivery(),b'{"job_id":123}')
    assert channel.rejected

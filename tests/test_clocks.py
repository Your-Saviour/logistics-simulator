import os
from uuid import uuid4

import pytest

from simulator.clocks import advance_once
from simulator.store import Store
from simulator.contracts import Envelope


def test_delayed_grant_does_not_execute_future_jobs():
    store = Store(os.environ['TEST_DATABASE_URL'])
    store.migrate()
    store.control('reset')
    job = store.schedule('future', 5, {'quantity': 4})

    class DelayedPeer:
        def request(self, target):
            return None
        def poll(self):
            return None

    assert advance_once(store, DelayedPeer(), 5) is False
    assert store.execute(job['id']) == 'waiting'
    assert store.status()['run']['requested'] == 5
    assert store.status()['run']['granted'] == 0


def test_boundary_messages_deduplicate_and_fence():
    store = Store(os.environ['TEST_DATABASE_URL'])
    store.migrate()
    store.control('reset')
    run = store.status()['run']
    envelope = Envelope(federation_id='test', run_id=run['id'], epoch=run['epoch'], correlation_id=uuid4(), causation_id=uuid4(), aggregate_id=uuid4(), aggregate_version=1, source='manufacturing', destination='storage', boundary='supply', effective_time=1, payload={'quantity': 3})
    assert store.ingest(envelope, 'manufacturing', 'supply', 'storage') == 'accepted'
    assert store.ingest(envelope, 'manufacturing', 'supply', 'storage') == 'duplicate'
    store.grant(1)
    job = store.status()['jobs'][0]
    store.execute(job['id'])
    assert store.status()['effects'] == 3
    store.control('reset')
    assert store.ingest(envelope, 'manufacturing', 'supply', 'storage') == 'fenced'

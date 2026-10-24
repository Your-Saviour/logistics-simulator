import json
import os
from pathlib import Path
from pydantic import ValidationError
import pytest
from simulator.config import Settings
from simulator.controller import ingest_boundaries
from simulator.store import Store


def test_analytics_envelope_never_reaches_business_inbox():
    store=Store(os.environ['TEST_DATABASE_URL']);store.migrate();store.control('reset')
    raw=json.loads(Path('contracts/v1/fixtures/sample.completed.json').read_text())
    run=store.status()['run']
    raw.update(run_id=str(run['id']),epoch=str(run['epoch']),type='analytics.sample.v1')
    class ExternalTransport:
        def receive(self): return [('manufacturing/events',raw)]
    with pytest.raises(ValidationError):
        ingest_boundaries(store,ExternalTransport(),Settings(app='storage',federation_id='bootstrap-fixture'),{'supply':{'source':'manufacturing','endpoint':'manufacturing/events'}})
    assert store.status()['effects']==0 and store.status()['jobs']==[]
    with store.connect() as db:
        assert db.execute('SELECT count(*) AS n FROM inbox WHERE run_id=%s',(run['id'],)).fetchone()['n']==0


def test_accepted_command_rolls_back_when_its_audit_cannot_commit():
    import psycopg
    from uuid import uuid4
    store=Store(os.environ['TEST_DATABASE_URL']);store.migrate();store.control('reset')
    invalid_context={'actor':'operator','role':None,'request_id':uuid4(),'action':'POST /api/jobs'}
    with pytest.raises(psycopg.errors.NotNullViolation):
        store.schedule('audit-atomic',1,{'quantity':3},audit_context=invalid_context)
    assert store.status()['jobs']==[]

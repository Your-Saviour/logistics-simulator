import os
import subprocess
import sys
from simulator.store import Store


def test_competing_controller_does_not_stall_current_owner():
    store=Store(os.environ['TEST_DATABASE_URL'])
    store.migrate()
    store.control('reset')
    with store.connect() as lease:
        lease.autocommit=True
        lease.execute('SELECT pg_advisory_lock(8192102)')
        env={**os.environ,'DATABASE_URL':store.url,'AMQP_URL':'amqp://unused','APP_PASSWORD':'test','AUTONOMOUS_SAMPLE':'false'}
        result=subprocess.run([sys.executable,'-m','simulator.controller'],env=env,capture_output=True,timeout=15)
        assert result.returncode==0
    assert store.status()['run']['state']=='running'


def test_failure_from_replaced_controller_cannot_stall_new_owner():
    store=Store(os.environ['TEST_DATABASE_URL'])
    store.migrate()
    store.control('reset')
    with store.connect() as lease:
        lease.autocommit=True
        lease.execute('SELECT pg_advisory_lock(8192102)')
        store.stall('Old controller failed')
    assert store.status()['run']['state']=='running'

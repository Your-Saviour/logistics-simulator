import os
from concurrent.futures import ThreadPoolExecutor
import time
from simulator.store import Store


def test_restart_migration_does_not_repeat_ddl_against_active_work():
    store=Store(os.environ['TEST_DATABASE_URL']);store.migrate();store.control('reset')
    with ThreadPoolExecutor(max_workers=1) as pool:
        with store.connect() as active:
            store._run(active)
            future=pool.submit(store.migrate)
            time.sleep(.3)
            finished=future.done()
        future.result(timeout=10)
    assert finished, 'Already-applied migrations blocked on live business state'


def test_runtime_transaction_waits_for_schema_change_gate():
    store=Store(os.environ['TEST_DATABASE_URL']);store.migrate()
    with ThreadPoolExecutor(max_workers=1) as pool:
        with store.connect() as schema:
            schema.execute('SELECT pg_advisory_xact_lock(8192103)')
            future=pool.submit(store.status)
            time.sleep(.2)
            blocked=not future.done()
        future.result(timeout=10)
    assert blocked, 'Business work ran while a schema migration owned the gate'


def test_new_schema_change_waits_before_taking_business_table_locks(tmp_path,monkeypatch):
    import shutil
    from pathlib import Path
    from uuid import uuid4
    from psycopg import sql
    from psycopg.conninfo import make_conninfo
    admin=Store(os.environ['TEST_DATABASE_URL'])
    name='simu_schema_'+uuid4().hex[:12]
    with admin.connect() as db:
        db.autocommit=True
        db.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(name)))
    try:
        store=Store(make_conninfo(admin.url,dbname=name));store.migrate()
        shutil.copytree(Path('migrations'),tmp_path/'migrations')
        (tmp_path/'migrations/004_test.sql').write_text('ALTER TABLE runs ADD COLUMN schema_gate_probe boolean NOT NULL DEFAULT true;')
        monkeypatch.chdir(tmp_path)
        with ThreadPoolExecutor(max_workers=1) as pool:
            with store.transaction() as active:
                run=store._run(active)
                future=pool.submit(store.migrate)
                time.sleep(.2)
                assert not future.done()
                active.execute('UPDATE runs SET speed=5 WHERE id=%s',(run['id'],))
            future.result(timeout=10)
        assert store.status()['run']['speed']==5
        with store.transaction() as db:
            assert db.execute('SELECT schema_gate_probe FROM runs WHERE current').fetchone()['schema_gate_probe']
    finally:
        with admin.connect() as db:
            db.autocommit=True
            db.execute(sql.SQL('DROP DATABASE {} WITH (FORCE)').format(sql.Identifier(name)))

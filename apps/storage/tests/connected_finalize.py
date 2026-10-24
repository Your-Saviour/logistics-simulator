"""Native barrier API race against real PostgreSQL; no adapter/native time fake.

Run in verifier container with API up and worker/controller stopped. The fixture
installs additive metadata columns and restores its run mode/state on exit.
"""
import concurrent.futures, json, os, time, uuid
import psycopg
from psycopg.rows import dict_row
from smoke import request
url=os.environ['DATABASE_URL']
with psycopg.connect(url,row_factory=dict_row) as db:
    original=db.execute('SELECT * FROM runs WHERE current').fetchone()
    run=original['id']; session=uuid.uuid4()
    db.execute("ALTER TABLE storage_adapter_sessions ADD COLUMN IF NOT EXISTS native_pending boolean NOT NULL DEFAULT true")
    db.execute("ALTER TABLE storage_adapter_sessions ADD COLUMN IF NOT EXISTS native_state text NOT NULL DEFAULT 'initializing'")
    db.execute("UPDATE runs SET mode='helics',state='running' WHERE id=%s",(run,))
    db.execute("INSERT INTO storage_adapter_sessions(run_id,epoch,session_id,native_pending,native_state) VALUES (%s,%s,%s,true,'initializing') ON CONFLICT(run_id) DO UPDATE SET native_pending=true,native_state='initializing'",(run,original['epoch'],session))
    db.commit()
    job=uuid.uuid4()
    try:
        code,value=request('control/finalize',{});assert code==409,('initializing native session accepted finalize',code,value)
        db.execute("UPDATE storage_adapter_sessions SET native_state='executing' WHERE run_id=%s",(run,));db.commit()
        # Hold the run transition lock while the pending request intent commits.
        db.execute('SELECT id FROM runs WHERE id=%s FOR UPDATE',(run,))
        db.execute("UPDATE storage_adapter_sessions SET native_pending=true WHERE run_id=%s",(run,))
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            response=pool.submit(request,'control/finalize',{})
            time.sleep(.15);assert not response.done(),'finalize bypassed run transaction lock'
            db.commit()
            code,value=response.result();assert code==409,('pending native request accepted finalize',code,value)
        db.execute("UPDATE storage_adapter_sessions SET native_pending=false,native_state='polling' WHERE run_id=%s",(run,));db.commit()
        assert request('control/finalize',{})[0]==409,'unsettled native receive accepted finalize'
        db.execute("UPDATE storage_adapter_sessions SET native_state='executing' WHERE run_id=%s",(run,))
        db.execute("INSERT INTO jobs(id,run_id,epoch,idempotency_key,due_at,original_due_at,payload) VALUES (%s,%s,%s,%s,%s,%s,'{\"quantity\":1}')",(job,run,original['epoch'],'native-finalize-fixture:'+str(job),original['granted'],original['granted']))
        db.commit();assert request('control/finalize',{})[0]==409,'due work bypassed finalize barrier'
        db.execute('DELETE FROM jobs WHERE id=%s',(job,));db.commit()
        assert request('control/finalize',{})[0]==200,'settled native session cannot finalize'
        print('PASS API finalize rejects initialization, concurrent pending intent, unsettled receive and due work; settled session finalizes')
    finally:
        db.execute('DELETE FROM jobs WHERE id=%s',(job,))
        db.execute('DELETE FROM storage_adapter_sessions WHERE session_id=%s',(session,))
        db.execute('UPDATE runs SET mode=%s,state=%s WHERE id=%s',(original['mode'],original['state'],run));db.commit()

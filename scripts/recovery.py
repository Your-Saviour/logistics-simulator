#!/usr/bin/env python3
"""Run against the local suite; verifies real broker/worker recovery."""
import json
import subprocess
import time
from uuid import uuid4

from smoke import call

COMPOSE = ['docker','compose','-f','deploy/generated/suite.json']


def compose(*args, script=None):
    return subprocess.run(COMPOSE+list(args), input=script, text=True, check=True, capture_output=True).stdout


def publish(job_id=None, malformed=False):
    script = """import os,json,pika
from simulator.messaging import connect,channel_for,QUEUE
c=connect(os.environ['AMQP_URL']);ch=channel_for(c)
body=BODY
for _ in range(8):
    ch.basic_publish('',QUEUE,body,pika.BasicProperties(delivery_mode=2),mandatory=True)
c.close()
""".replace('BODY', repr('invalid-json' if malformed else json.dumps({'job_id':job_id})))
    compose('exec','-T','storage-api','python','-',script=script)


def wait_job(job_id, status='completed'):
    deadline=time.monotonic()+45
    while time.monotonic()<deadline:
        found=next(j for j in call('storage','status')['jobs'] if j['id']==job_id)
        if found['status']==status:
            return
        time.sleep(.3)
    raise AssertionError('Durable job did not recover')


def main():
    compose('up','-d','--scale','storage-worker=2','--no-recreate')
    call('storage','control/hold',{})
    run=call('storage','status')['run']
    job=call('storage','jobs',{'due_at':max(run['requested'],run['granted'])+2,'quantity':11},'recovery-'+uuid4().hex)
    compose('stop','storage-worker')
    publish(job['id'])
    call('storage','control/resume',{})
    time.sleep(1)
    assert next(j for j in call('storage','status')['jobs'] if j['id']==job['id'])['status']=='pending'
    compose('start','storage-worker')
    wait_job(job['id'])
    publish(job['id'])
    compose('restart','storage-worker')
    wait_job(job['id'])
    output=compose('exec','-T','storage-api','python','-',script=f"""import os
from simulator.store import Store
with Store(os.environ['DATABASE_URL']).connect() as db:
    row=db.execute('SELECT count(*) AS n, sum(quantity) AS quantity FROM effects WHERE job_id=%s',('{job['id']}',)).fetchone()
    assert row['n']==1 and row['quantity']==11, row
print('one effect after redelivery and worker restart')
""")
    print(output.strip())
    compose('stop','storage-broker')
    run=call('storage','status')['run']
    queued=call('storage','jobs',{'due_at':max(run['requested'],run['granted'])+2,'quantity':5},'broker-recovery-'+uuid4().hex)
    time.sleep(3)
    assert next(j for j in call('storage','status')['jobs'] if j['id']==queued['id'])['status']=='pending'
    compose('start','storage-broker')
    wait_job(queued['id'])
    print('broker outage retained outbox work and recovered')
    publish(malformed=True)
    time.sleep(2)
    output=compose('exec','-T','storage-api','python','-',script="""import os
from simulator.messaging import connect,channel_for,DEAD_QUEUE
c=connect(os.environ['AMQP_URL']);ch=channel_for(c)
result=ch.queue_declare(DEAD_QUEUE,passive=True)
assert result.method.message_count>=8
print('malformed deliveries reached durable dead-letter queue')
c.close()
""")
    print(output.strip())
    # New run must fence a message that was queued before reset.
    call('storage','control/hold',{})
    run=call('storage','status')['run']
    old=call('storage','jobs',{'due_at':max(run['requested'],run['granted'])+10,'quantity':9},'old-'+uuid4().hex)
    call('storage','control/reset',{'confirm_run_id':run['id']})
    publish(old['id'])
    time.sleep(1)
    assert call('storage','status')['effects']==0
    print('old-epoch queue deliveries fenced after reset')
    # Corrupt only this deliberately created sample payload to exercise a real
    # processing exception and the terminal nack, without test flags in workers.
    call('storage','control/hold',{})
    run=call('storage','status')['run']
    broken=call('storage','jobs',{'due_at':max(run['requested'],run['granted'])+2,'quantity':1},'broken-'+uuid4().hex)
    compose('exec','-T','storage-api','python','-',script=f"""import os
from simulator.store import Store
with Store(os.environ['DATABASE_URL']).connect() as db:
    db.execute("UPDATE jobs SET payload='{{}}'::jsonb WHERE id=%s",('{broken['id']}',))
""")
    call('storage','control/resume',{})
    wait_job(broken['id'],'dead')
    time.sleep(1)
    output=compose('exec','-T','storage-api','python','-',script=f"""import os,json
from simulator.messaging import connect,channel_for,DEAD_QUEUE
from simulator.store import Store
with Store(os.environ['DATABASE_URL']).connect() as db:
    row=db.execute('SELECT attempts,status FROM jobs WHERE id=%s',('{broken['id']}',)).fetchone()
    assert row['attempts']==3 and row['status']=='dead'
c=connect(os.environ['AMQP_URL']);ch=channel_for(c);found=False
while True:
    method,_,body=ch.basic_get(DEAD_QUEUE,auto_ack=True)
    if method is None: break
    try:
        if json.loads(body).get('job_id')=='{broken['id']}': found=True
    except (ValueError,AttributeError): pass
assert found, 'Terminal failed sample was not dead-lettered'
c.close()
print('three processing failures reached durable dead-letter queue')
""")
    print(output.strip())
    failed=call('storage','status')['run']
    call('storage','control/reset',{'confirm_run_id':failed['id']})
    compose('start','storage-controller')



if __name__=='__main__':
    main()

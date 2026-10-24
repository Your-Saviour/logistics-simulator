"""Runs only in the isolated compose smoke container against actual HTTP services."""
import base64,json,time,urllib.request,urllib.error,uuid
BASE='http://manufacturing-web'
def request(path,body=None,key=None,user='operator'):
    password={'operator':'smoke-operator-only','employee':'smoke-employee-only','observer':'smoke-observer-only'}[user]
    headers={'Authorization':'Basic '+base64.b64encode(f'{user}:{password}'.encode()).decode(),'Content-Type':'application/json'}
    if key: headers['Idempotency-Key']=key
    req=urllib.request.Request(BASE+'/api'+path,headers=headers,data=json.dumps(body).encode() if body is not None else None)
    try:
        with urllib.request.urlopen(req,timeout=6) as response:return response.status,json.load(response)
    except urllib.error.HTTPError as error:return error.code,json.load(error)
for _ in range(120):
    try:
        code,status=request('/status')
        if code==200 and request('/health/ready')[0]==200:break
    except (OSError,ValueError):pass
    time.sleep(1)
else:raise AssertionError('Manufacturing services did not become ready')
assert request('/control/hold',{},user='employee')[0]==403
assert request('/jobs',{'due_at':10000,'quantity':1},str(uuid.uuid4()),'observer')[0]==403
assert request('/jobs',{'due_at':10000,'quantity':True},str(uuid.uuid4()),'employee')[0]==422
assert request('/control/hold',{})[0]==200
status=request('/status')[1]
job={'due_at':max(status['run']['requested'],status['run']['granted'])+2,'quantity':7}
key=str(uuid.uuid4())
code,accepted=request('/jobs',job,key,'employee');assert code==200,(code,accepted)
assert request('/jobs',job,key,'employee')[1]['id']==accepted['id']
assert request('/jobs',{**job,'quantity':8},key,'employee')[0]==409
assert request('/control/speed',{'speed':60})[0]==200
assert request('/control/resume',{})[0]==200
for _ in range(60):
    status=request('/status')[1]
    if status['effects']==7:break
    time.sleep(.5)
else:raise AssertionError(status)
assert request('/jobs',job,key,'employee')[1]['id']==accepted['id'],'Replay survives time advance'
audit=request('/audit')[1]
assert any(row['target_id']==accepted['id'] and row['actor']=='employee' for row in audit)
assert any(row['outcome']=='rejected' and row['actor']=='observer' for row in audit)
with urllib.request.urlopen(BASE,timeout=5) as response:assert b'<app-root>' in response.read()
print('Manufacturing actual HTTP smoke passed: readiness, roles, strict validation, replay/conflict, execution, audits, Angular artifact.')

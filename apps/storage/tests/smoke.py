"""HTTP contract and real durable sample smoke; standard library only."""
import base64, concurrent.futures, json, os, time, urllib.request, urllib.error, uuid
base=os.getenv('STORAGE_URL','http://localhost:18148')
def request(path,body=None,user='operator',password='storage-smoke',key=None):
    headers={'Content-Type':'application/json'}
    if user: headers['Authorization']='Basic '+base64.b64encode(f'{user}:{password}'.encode()).decode()
    if key: headers['Idempotency-Key']=key
    req=urllib.request.Request(base+'/api/'+path,data=json.dumps(body).encode() if body is not None else None,headers=headers)
    try:
        with urllib.request.urlopen(req,timeout=10) as res: return res.status,json.load(res)
    except urllib.error.HTTPError as e: return e.code,json.load(e)
def check(path,body=None,code=200,**kw):
    actual,value=request(path,body,**kw)
    assert actual==code,(path,actual,code,value)
    return value
def main():
    assert check('health/live',user=None)=={'application':'storage','alive':True}
    check('status',user=None,code=401)
    check('projection',user=None,code=401)
    projection=check('projection',user='service',password='service-smoke')
    assert projection['version']==1 and projection['source']=='storage' and isinstance(projection['snapshot'],dict) and isinstance(projection['events'],list)
    status=check('status'); assert status['application']=='storage'
    check('control/hold',{},user='employee',password='employee-smoke',code=403)
    check('control/hold',{},user='service',password='service-smoke',code=403)
    check('control/hold',{})
    for quantity in (True,'1',1.1,0,10001): check('jobs',{'due_at':2,'quantity':quantity},code=422,key=str(uuid.uuid4()))
    check('jobs',{'due_at':2,'quantity':1,'unknown':True},code=422,key=str(uuid.uuid4()))
    check('jobs',{'due_at':2,'quantity':1},code=422)
    check('jobs',{'due_at':2,'quantity':1},code=409,key='synthetic:reserved')
    run=check('status')['run']; due=max(run['granted'],run['requested'])+2
    key=str(uuid.uuid4()); command={'due_at':due,'quantity':7}
    job=check('jobs',command,key=key,user='employee',password='employee-smoke')
    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
        replies=list(pool.map(lambda _:check('jobs',command,key=key),range(6)))
    assert all(x['id']==job['id'] for x in replies)
    check('jobs',dict(command,quantity=8),key=key,code=409)
    check('control/reset',{},code=409)
    check('control/reset',{'confirm_run_id':str(uuid.uuid4())},code=409)
    check('control/speed',{'speed':60}); check('control/resume',{})
    for _ in range(100):
        value=check('status')
        if any(j['id']==job['id'] and j['status']=='completed' for j in value['jobs']): break
        time.sleep(.2)
    else: raise AssertionError(('job did not complete',value))
    assert value['effects']==7,value
    check('control/hold',{}); audits=check('audit')
    assert any(a['actor']=='employee' and a['outcome']=='accepted' and a['target_id']==job['id'] for a in audits)
    assert any(a['actor']=='service' and a['outcome']=='rejected' and a['status_code']==403 for a in audits)
    old=check('status')['run']['id']
    reset=check('control/reset',{'confirm_run_id':old}); assert reset['run']['id']!=old and reset['effects']==0
    assert check('sources')==[]
    check('audit',user='employee',password='employee-smoke',code=403)
    print('PASS HTTP strict validation, role isolation, concurrent idempotency, audit, durable completion, reset')

if __name__=='__main__': main()

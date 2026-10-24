"""Behavior at the department/adapter boundary, with native IO isolated."""
from uuid import uuid4
import pytest
from simulator.adapter import Adapter, create_app


class Native:
    def __init__(self):
        self.pending = False
        self.ready = False
        self.next_grant = None
        self.incoming = []
        self.sent = []
        self.closed = False
        self.fail_send = False
    def initialize(self): pass
    def initialized(self): return self.ready
    def request(self, target): self.pending = True
    def poll(self):
        value = self.next_grant
        self.next_grant = None
        if value is not None: self.pending = False
        return value
    def receive(self):
        rows, self.incoming = self.incoming, []
        return rows
    def values(self): return {'external-power/available_power_kw': 25.0}
    def send(self, envelope, endpoint):
        if self.fail_send: raise OSError('native publication uncertain')
        self.sent.append((envelope, endpoint))
    def publish_value(self, value): pass
    def finalize(self): self.closed = True


@pytest.fixture
def setup(tmp_path):
    native = Native()
    run, epoch, session = (str(uuid4()) for _ in range(3))
    options = dict(journal=tmp_path/'journal.sqlite', run_id=run, epoch=epoch,
                   factory=lambda: native, application='storage', federation_id='test',
                   outputs=[{'endpoint':'shipping/events','destination':'shipping','boundary':'goods'}])
    engine = Adapter(**options)
    client = create_app(engine, 'private-token').test_client()
    def command(operation, payload=None, **changes):
        value = dict(version='1.0', request_id=str(uuid4()), run_id=run, epoch=epoch,
                     session_id=session, operation=operation, payload=payload or {})
        value.update(changes)
        return value
    def post(body):
        return client.post('/v1/commands', json=body, headers={'Authorization':'Bearer private-token'})
    yield engine,native,client,command,post,options
    engine.close()


def execute(setup):
    engine,native,client,command,post,_=setup
    assert post(command('initialize')).status_code == 200
    native.ready=True
    response=post(command('poll'))
    assert response.json['result']['state']=='executing'


def envelope(setup):
    _,_,_,command,_,_=setup
    ctx=command('poll')
    return dict(schema_version='1.0',type='sample.completed.v1',event_id=str(uuid4()),
                federation_id='test',run_id=ctx['run_id'],epoch=ctx['epoch'],
                correlation_id=str(uuid4()),causation_id=str(uuid4()),aggregate_id=str(uuid4()),
                aggregate_version=1,source='storage',destination='shipping',boundary='goods',
                effective_time=1,wall_time='2026-10-24T00:00:00Z',quantity_unit='item',payload={'quantity':2})


def test_authentication_and_strict_versioned_payload(setup):
    _,_,client,command,post,_=setup
    assert client.get('/v1/health').status_code==401
    assert client.post('/v1/commands',json=command('initialize')).status_code==401
    assert post(command('initialize',unexpected=True)).status_code==422
    assert post(command('initialize',version='2.0')).status_code==422
    assert post(command('request_time',{'target':float('inf'),'committed':0,'pending_work':0,'pending_outputs':0})).status_code==422
    assert post(command('initialize',{'secret':'unknown'})).status_code==422
    for target in (True,'1'):
        assert post(command('request_time',{'target':target,'committed':0,'pending_work':0,'pending_outputs':0})).status_code==422


def test_delayed_and_earlier_grant_never_authorizes_requested_time(setup):
    execute(setup)
    _,native,_,command,post,_=setup
    request=command('request_time',{'target':5,'committed':0,'pending_work':0,'pending_outputs':0})
    assert post(request).status_code==200
    pending=post(command('poll')).json['result']
    assert pending['pending'] is True and pending['granted']==0 and pending['requested']==5
    native.next_grant=2
    granted=post(command('poll')).json['result']
    assert granted['granted']==2 and granted['pending'] is False
    assert post(command('request_time',{'target':8,'committed':5,'pending_work':0,'pending_outputs':0})).status_code==409


def test_durable_completion_and_receive_ack_block_advances(setup):
    execute(setup)
    _,native,_,command,post,_=setup
    event=envelope(setup)
    event.update(source='shipping',destination='storage')
    native.incoming=[('shipping/events',event)]
    first=post(command('poll')).json['result']['messages']
    assert len(first)==1
    assert post(command('poll')).json['result']['messages']==first
    payload={'target':1,'committed':0,'pending_work':0,'pending_outputs':0}
    assert post(command('request_time',payload)).status_code==409
    assert post(command('receive_ack',{'event_ids':[event['event_id']]})).status_code==200
    assert post(command('request_time',{**payload,'pending_work':1})).status_code==409
    assert post(command('request_time',{**payload,'pending_outputs':1})).status_code==409
    assert post(command('request_time',payload)).status_code==200


def test_reply_loss_replays_publication_once_and_body_conflicts(setup):
    execute(setup)
    _,native,_,command,post,_=setup
    request=command('publish',{'endpoint':'shipping/events','envelope':envelope(setup)})
    first=post(request)
    assert first.status_code==200
    assert post(request).json==first.json
    assert len(native.sent)==1
    changed={**request,'payload':{**request['payload'],'endpoint':'unknown/events'}}
    assert post(changed).status_code==409
    assert len(native.sent)==1


def test_pending_grant_stale_epoch_and_unconfigured_route_rejected(setup):
    execute(setup)
    _,native,_,command,post,_=setup
    assert post(command('poll',epoch=str(uuid4()))).status_code==409
    assert post(command('poll',session_id=str(uuid4()))).status_code==409
    assert post(command('publish',{'endpoint':'unknown/events','envelope':envelope(setup)})).status_code==409
    assert post(command('request_time',{'target':1,'committed':0,'pending_work':0,'pending_outputs':0})).status_code==200
    assert post(command('publish',{'endpoint':'shipping/events','envelope':envelope(setup)})).status_code==409
    assert native.sent==[]


def test_adapter_restart_and_uncertain_publication_fail_closed(setup):
    execute(setup)
    engine,native,_,command,post,options=setup
    native.fail_send=True
    assert post(command('publish',{'endpoint':'shipping/events','envelope':envelope(setup)})).status_code==503
    assert engine.health()['state']=='stalled'
    engine.close()
    replacement=Adapter(**options)
    try:
        assert replacement.health()['state']=='stalled'
        response=create_app(replacement,'private-token').test_client().post('/v1/commands',json=command('initialize'),headers={'Authorization':'Bearer private-token'})
        assert response.status_code==409
    finally: replacement.close()


def test_checkpoint_is_not_native_recovery_and_second_owner_rejected(setup):
    execute(setup)
    _,_,_,command,post,options=setup
    state=post(command('checkpoint')).json['result']
    assert state['recoverable'] is False and state['granted']==0
    with pytest.raises(RuntimeError,match='owner'):
        Adapter(**options)


def test_finalize_waits_for_initialization_and_then_disconnects_once(setup):
    engine,native,_,command,post,_=setup
    assert post(command('initialize')).status_code==200
    assert post(command('finalize')).status_code==409
    assert not native.closed
    native.ready=True
    assert post(command('poll')).json['result']['state']=='executing'
    final=command('finalize')
    assert post(final).json['result']['state']=='finalized'
    assert native.closed and post(final).status_code==200


def test_typed_publication_rejects_boolean_and_string_numbers(setup):
    execute(setup)
    _,native,_,command,post,_=setup
    for value in (True,'2'):
        assert post(command('publish_value',{'value':value,'unit':'item'})).status_code==422
    for field,value in (('effective_time',True),('effective_time','1'),('aggregate_version',True),('aggregate_version','1'),('wall_time',0),('wall_time','2026-10-24T08:00:00')):
        body=envelope(setup)
        body[field]=value
        assert post(command('publish',{'endpoint':'shipping/events','envelope':body})).status_code==422
    assert native.sent==[]


def test_read_only_journal_returns_json_unavailable_without_native_send(setup):
    import sqlite3
    execute(setup)
    engine,native,_,command,post,options=setup
    engine.db.close()
    engine.db=sqlite3.connect('file:'+str(options['journal'])+'?mode=ro',uri=True,check_same_thread=False,isolation_level=None)
    response=post(command('publish',{'endpoint':'shipping/events','envelope':envelope(setup)}))
    assert response.status_code==503
    assert isinstance(response.json['detail'],str)
    assert native.sent==[]


def test_journal_failure_after_native_send_fences_retry(setup):
    execute(setup)
    engine,native,_,command,post,_=setup
    engine.db.execute("CREATE TRIGGER fail_checkpoint BEFORE UPDATE ON metadata BEGIN SELECT RAISE(FAIL,'journal unavailable'); END")
    body=command('publish',{'endpoint':'shipping/events','envelope':envelope(setup)})
    response=post(body)
    assert response.status_code==503 and response.is_json
    assert engine.health()['state']=='stalled' and len(native.sent)==1
    assert post(body).status_code==409 and len(native.sent)==1


def test_checkpoint_reports_recovery_metadata_after_native_loss(setup):
    execute(setup)
    engine,_,_,command,_,options=setup
    engine.close()
    replacement=Adapter(**options)
    try:
        client=create_app(replacement,'private-token').test_client()
        response=client.post('/v1/commands',json=command('checkpoint'),headers={'Authorization':'Bearer private-token'})
        assert response.status_code==200
        assert response.json['result']['state']=='stalled'
        assert response.json['result']['recoverable'] is False
        assert response.json['result']['granted']==0
    finally: replacement.close()

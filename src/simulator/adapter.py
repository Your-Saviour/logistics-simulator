"""Single-owner native HELICS adapter. Durable SQL/business work stays in its client.

The SQLite journal is an operation log and native-loss fence, not a HELICS
checkpoint. A process restart cannot recreate a live native epoch.
"""
import fcntl
import hashlib
import json
import math
import os
from pathlib import Path
import secrets
import sqlite3
import threading
from uuid import UUID

from flask import Flask, jsonify, request
from pydantic import ValidationError
from .adapter_protocol import Command, PAYLOADS
from .contracts import Envelope


class ProtocolConflict(Exception): pass
class NativeUnavailable(Exception): pass


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False)


class Adapter:
    def __init__(self, journal, run_id, epoch, factory, application, federation_id, outputs=()):
        self.run_id, self.epoch = str(UUID(run_id)), str(UUID(epoch))
        if application not in ('manufacturing','storage','logistics','shipping') or not federation_id:
            raise ValueError('Business application and federation identity required')
        self.application, self.federation_id = application, federation_id
        self.outputs = list(outputs)
        self.factory, self.native = factory, None
        self.lock = threading.RLock()
        path = Path(journal)
        path.parent.mkdir(parents=True, exist_ok=True)
        self.owner = path.with_suffix('.owner').open('a+')
        try:
            fcntl.flock(self.owner.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            self.owner.close()
            raise RuntimeError('Another adapter owner holds this journal') from exc
        self.db = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
        self.db.execute('PRAGMA journal_mode=WAL')
        self.db.execute('PRAGMA synchronous=FULL')
        self.db.execute('CREATE TABLE IF NOT EXISTS metadata(id INTEGER PRIMARY KEY CHECK(id=1),body TEXT NOT NULL)')
        self.db.execute('CREATE TABLE IF NOT EXISTS operations(request_id TEXT PRIMARY KEY,hash TEXT NOT NULL,response TEXT)')
        row = self.db.execute('SELECT body FROM metadata WHERE id=1').fetchone()
        self.session_id = None
        self.state = 'new'
        self.granted = self.requested = 0.0
        self.pending = False
        self.messages, self.values = {}, {}
        if row:
            prior = json.loads(row[0])
            if (prior['run_id'], prior['epoch']) != (self.run_id,self.epoch):
                self.close()
                raise RuntimeError('Archive the old journal before changing federation run/epoch')
            self.session_id = prior['session_id']
            self.granted, self.requested = prior['granted'], prior['requested']
            self.state = 'finalized' if prior['state']=='finalized' else 'stalled'
            self._save()

    def health(self):
        with self.lock:
            return {'version':'1.0','state':self.state,'session_id':self.session_id}

    def _snapshot(self):
        return {'state':self.state,'granted':self.granted,'requested':self.requested,
                'pending':self.pending,'messages':list(self.messages.values()),'values':self.values}

    def _save(self):
        body = {'run_id':self.run_id,'epoch':self.epoch,'session_id':self.session_id,
                'state':self.state,'granted':self.granted,'requested':self.requested}
        self.db.execute('INSERT INTO metadata(id,body) VALUES (1,?) ON CONFLICT(id) DO UPDATE SET body=excluded.body',(canonical(body),))

    def command(self, raw):
        command = Command.model_validate(raw)
        payload = PAYLOADS[command.operation].model_validate(command.payload)
        body = command.model_dump(mode='json')
        digest = hashlib.sha256(canonical(body).encode()).hexdigest()
        key = str(command.request_id)
        with self.lock:
            if (str(command.run_id),str(command.epoch)) != (self.run_id,self.epoch):
                raise ProtocolConflict('Stale adapter run or epoch')
            if self.session_id and self.session_id != str(command.session_id):
                raise ProtocolConflict('Another controller session owns this native epoch')
            if self.state=='stalled' and command.operation!='checkpoint':
                raise ProtocolConflict('Native session lost or uncertain; coordinated new federation epoch required')
            old = self.db.execute('SELECT hash,response FROM operations WHERE request_id=?',(key,)).fetchone()
            if old:
                if old[0]!=digest:
                    raise ProtocolConflict('Request ID already used with a different command')
                if old[1] is None:
                    raise ProtocolConflict('Ambiguous native operation; coordinated recovery required')
                return json.loads(old[1])
            # Validate every precondition BEFORE journaling native intent.
            self._validate(command.operation,payload)
            self.db.execute('INSERT INTO operations(request_id,hash) VALUES (?,?)',(key,digest))
            try:
                result = self._apply(command.operation,payload,str(command.session_id))
                response = {'version':'1.0','request_id':key,'result':result}
                self._save()
                self.db.execute('UPDATE operations SET response=? WHERE request_id=?',(canonical(response),key))
                return response
            except Exception as exc:
                self.state='stalled'
                self._save()
                raise NativeUnavailable('Native operation failed; epoch stalled, coordinated recovery required') from exc

    def _validate(self, operation, payload):
        if operation=='initialize':
            if self.state!='new': raise ProtocolConflict('Adapter already initialized')
            return
        if self.state=='new': raise ProtocolConflict('Initialize the adapter first')
        if operation in ('poll','checkpoint'): return
        if operation=='finalize':
            if self.state not in ('executing','finalized'):
                raise ProtocolConflict('Complete native initialization before finalization')
            if self.pending or self.messages: raise ProtocolConflict('Settle native requests and persist received inputs before finalization')
            return
        if self.state!='executing': raise ProtocolConflict('Adapter is not executing')
        if operation=='receive_ack':
            # Repeating an ACK with a new ID is harmless; unknown IDs cannot
            # clear a different input or bypass a barrier.
            return
        if self.pending: raise ProtocolConflict('A native time request is outstanding')
        if operation=='request_time':
            if self.messages or payload.pending_work or payload.pending_outputs:
                raise ProtocolConflict('Persist inputs and settle current-time work and outputs before requesting time')
            if payload.committed!=self.granted or payload.target<=self.granted:
                raise ProtocolConflict('Commit the last grant before requesting a later time')
        if operation=='publish':
            e=payload.envelope
            if (str(e.run_id),str(e.epoch),e.federation_id,e.source)!=(self.run_id,self.epoch,self.federation_id,self.application):
                raise ProtocolConflict('Publication identity does not match this adapter')
            if e.effective_time < self.granted+1:
                raise ProtocolConflict('Boundary publication requires a positive handoff quantum')
            if not any(r['endpoint']==payload.endpoint and r['destination']==e.destination and r['boundary']==e.boundary for r in self.outputs):
                raise ProtocolConflict('Publication route is not configured')

    def _apply(self, operation, payload, session):
        if operation=='initialize':
            self.session_id=session
            self.state='initializing'
            self._save()  # Fence a crash during native construction/initialization.
            self.native=self.factory()
            self.native.initialize()
            return {'state':self.state}
        if operation=='poll':
            if self.state=='initializing' and self.native.initialized():
                self.state='executing'
            if self.state=='executing':
                granted=self.native.poll()
                if granted is not None:
                    if not math.isfinite(granted) or not self.granted<=granted<=self.requested or granted>1e20:
                        raise ValueError('Invalid native grant')
                    self.granted=float(granted)
                    self.pending=False
                if not self.pending:
                    self.values=self.native.values()
                    for source,raw in self.native.receive():
                        e=Envelope.model_validate(raw)
                        if (str(e.run_id),str(e.epoch),e.federation_id,e.destination)!=(self.run_id,self.epoch,self.federation_id,self.application):
                            raise ValueError('Native input identity mismatch')
                        if e.effective_time<self.granted:
                            raise ValueError('Late native input cannot rewrite committed history')
                        message={'source':source,'envelope':e.model_dump(mode='json')}
                        existing=self.messages.get(str(e.event_id))
                        if existing and existing!=message: raise ValueError('Conflicting duplicate event ID')
                        self.messages[str(e.event_id)]=message
            return self._snapshot()
        if operation=='receive_ack':
            for event in payload.event_ids: self.messages.pop(str(event),None)
            return {'acknowledged':[str(x) for x in payload.event_ids]}
        if operation=='request_time':
            self.native.request(payload.target)
            self.requested=payload.target
            self.pending=True
            return {'requested':self.requested}
        if operation=='publish':
            self.native.send(payload.envelope.model_dump(mode='json'),payload.endpoint)
            return {'published':str(payload.envelope.event_id)}
        if operation=='publish_value':
            self.native.publish_value(payload.value)
            return {'published':True}
        if operation=='checkpoint':
            return {**self._snapshot(),'recoverable':False,'session_id':self.session_id}
        if operation=='finalize':
            if self.native: self.native.finalize()
            self.state='finalized'
            return {'state':'finalized'}
        raise ValueError('Unknown operation')

    def close(self):
        with self.lock:
            if getattr(self,'db',None):
                self.db.close()
                self.db=None
            if getattr(self,'owner',None):
                self.owner.close()
                self.owner=None


def create_app(adapter, token):
    if not isinstance(token,str) or not token:
        raise ValueError('Private adapter token required')
    app=Flask(__name__)
    app.config['MAX_CONTENT_LENGTH']=1024*1024

    @app.before_request
    def authenticate():
        supplied=request.headers.get('Authorization','')
        if not secrets.compare_digest(supplied.encode(),('Bearer '+token).encode()):
            return jsonify(detail='Invalid adapter credential'),401

    @app.get('/v1/health')
    def health(): return jsonify(adapter.health())

    @app.post('/v1/commands')
    def command():
        try:
            return jsonify(adapter.command(request.get_json()))
        except ValidationError:
            return jsonify(detail='Invalid versioned adapter command'),422
        except ProtocolConflict as exc:
            return jsonify(detail=str(exc)),409
        except NativeUnavailable as exc:
            return jsonify(detail=str(exc)),503

    @app.errorhandler(400)
    @app.errorhandler(415)
    def malformed(_): return jsonify(detail='JSON command required'),422

    @app.errorhandler(sqlite3.Error)
    def journal_unavailable(_):
        return jsonify(detail='Adapter journal unavailable; coordinated recovery may be required'),503
    return app


def from_env():
    from .clocks import HelicsClock
    adapter=Adapter(journal=os.environ['ADAPTER_JOURNAL'],run_id=os.environ['FEDERATION_RUN_ID'],
                    epoch=os.environ['FEDERATION_EPOCH'],factory=lambda:HelicsClock(os.environ['HELICS_CONFIG']),
                    application=os.environ['SIMULATOR'],federation_id=os.environ['FEDERATION_ID'],
                    outputs=json.loads(os.getenv('HELICS_OUTPUTS','[]')))
    return create_app(adapter,os.environ['HELICS_ADAPTER_TOKEN'])

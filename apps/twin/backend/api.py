"""Flask API for the optional, independently authenticated twin read model."""
from datetime import date, datetime, timezone
from uuid import UUID, uuid4
import logging
import math
import os
import json

from .projection import ProjectionStore
from .controls import targets, public_targets, forward
from simulator.audit import write_audit

from flask import Flask, g, jsonify, request
from flask.json.provider import DefaultJSONProvider
import psycopg
from simulator.config import Settings
from simulator.scenario import Scenario
from simulator.security import identify
from simulator.store import Store, Conflict


class ContractJSON(DefaultJSONProvider):
    @staticmethod
    def default(value):
        if isinstance(value,datetime):
            return value.isoformat().replace('+00:00','Z')
        if isinstance(value,date): return value.isoformat()
        if isinstance(value,UUID): return str(value)
        return DefaultJSONProvider.default(value)


def create_app(settings,store,broker_check=None,control_client=None):
    if settings.app!='twin': raise ValueError('This Flask entry point serves only the digital twin')
    if not settings.password: raise ValueError('Independent twin credentials required')
    if broker_check is None:
        from simulator.messaging import broker_ready
        broker_check=lambda:broker_ready(settings.amqp_url)
    store.migrate()
    projection=ProjectionStore(store)
    projection.configure(json.loads(os.getenv('TWIN_SOURCES', '[]')))
    control_targets=targets(json.loads(os.getenv('TWIN_CONTROL_TARGETS', '[]')))
    app=Flask(__name__)
    app.json_provider_class=ContractJSON
    app.json=ContractJSON(app)
    app.config['MAX_CONTENT_LENGTH']=1024*1024

    def permitted(scope):
        from functools import wraps
        def decorate(fn):
            @wraps(fn)
            def authenticated(*args,**kwargs):
                credentials=request.authorization
                principal=identify(settings,credentials.username or '',credentials.password or '') if credentials and credentials.type.lower()=='basic' else None
                if principal is None: return jsonify(detail='Invalid username or password'),401
                g.audit.update(actor=principal.username,role=principal.role)
                if scope not in principal.scopes:
                    return jsonify(detail='This identity cannot perform the requested action'),403
                g.principal=principal
                return fn(*args,**kwargs)
            return authenticated
        return decorate

    @app.before_request
    def audit_context():
        g.audit={'actor':'anonymous','role':'anonymous','request_id':uuid4(),
                 'action':request.method+' '+request.path,'idempotency_key':request.headers.get('Idempotency-Key',''),
                 'peer':request.remote_addr or ''}
        if request.method=='POST' and request.path.startswith('/api/'):
            try: g.audit['run_id']=store.command_scope()
            except psycopg.Error:
                logging.error('Command not accepted: database unavailable request_id=%s',g.audit['request_id'])
                return jsonify(detail='Database unavailable; command was not accepted'),503

    @app.after_request
    def audit_rejection(response):
        response.headers['X-Request-ID']=str(g.audit['request_id'])
        if request.method=='POST' and request.path.startswith('/api/') and response.status_code>=400 and g.audit.get('run_id'):
            try: store.rejected_command(g.audit,response.status_code)
            except psycopg.Error:
                logging.error('Rejected command audit unavailable request_id=%s status=%s',g.audit['request_id'],response.status_code)
        return response

    @app.errorhandler(psycopg.Error)
    def database_error(_): return jsonify(detail='Database unavailable; command was not accepted'),503

    @app.errorhandler(Conflict)
    def conflict(exc): return jsonify(detail=str(exc)),409

    @app.get('/api/health/live')
    def live(): return jsonify(application='twin',alive=True)

    @app.get('/api/health/ready')
    def ready():
        try:
            value=store.status()
            broker=bool(broker_check())
            projection=any(x['role']=='projection' and x['healthy'] for x in value['heartbeats'])
            healthy=broker and projection
            return jsonify(application='twin',database=True,broker=broker,ready=healthy),200 if healthy else 503
        except (psycopg.Error,OSError): return jsonify(application='twin',ready=False),503

    @app.get('/api/status')
    @permitted('status:read')
    def status():
        value=store.status()
        return jsonify(identity=g.principal.public(),application='twin',providers={},quantum=settings.quantum,
                       simulation_time=Scenario.model_validate(value['run']['scenario']).instant(value['run']['granted']).isoformat(),**value)

    @app.get('/api/sources')
    @permitted('status:read')
    def sources(): return jsonify(projection.view()['sources'])

    def visible_twin():
        value=projection.view()
        if 'runs:control' in g.principal.scopes: value['controls']=public_targets(control_targets)
        return value

    @app.get('/api/twin')
    @permitted('status:read')
    def twin_snapshot(): return jsonify(visible_twin())

    @app.get('/api/twin/events')
    @permitted('status:read')
    def twin_events():
        cursor=request.args.get('after', request.headers.get('Last-Event-ID', '0'))
        if not cursor.isdecimal() or len(cursor)>19:
            return jsonify(detail='Nonnegative integer cursor required'),422
        value=visible_twin()
        # Full snapshot polling is the reconnect fallback. SSE returns the same
        # atomic snapshot/cursor and closes, avoiding pinned Gunicorn threads.
        if request.args.get('format')=='sse':
            from flask import Response
            body=app.json.dumps(value)
            return Response(f"retry: 2000\nid: {value['revision']}\nevent: snapshot\ndata: {body}\n\n",
                            mimetype='text/event-stream',
                            headers={'Cache-Control':'no-cache','X-Accel-Buffering':'no'})
        return jsonify(value)

    @app.post('/api/twin/controls/<name>/<action>')
    @permitted('runs:control')
    def route_control(name,action):
        target=control_targets.get(name)
        if target is None or action not in target['actions']:
            return jsonify(detail='Control route not configured'),404
        key=request.headers.get('Idempotency-Key','')
        if not 1<=len(key)<=128: return jsonify(detail='Idempotency-Key required'),422
        body=request.get_json(silent=True)
        if not isinstance(body,dict): return jsonify(detail='JSON object required'),422
        if target['scope']=='local':
            if set(body)!={'run_id','epoch'}: return jsonify(detail='Current source run_id and epoch required'),422
            source=next((s for s in projection.view()['sources'] if s['name']==target['source']),None)
            if not source or not source['connected'] or not source['status']:
                return jsonify(detail='Source unavailable; control was not forwarded'),409
            run=source['status']['run']
            if (body['run_id'],body['epoch'])!=(run['id'],run['epoch']):
                return jsonify(detail='Source run changed; control was not forwarded'),409
        elif body:
            return jsonify(detail='Federation control body must be empty'),422
        # Persist routing intent before any remote side effect. The owner is the
        # authority for command idempotency, fencing and acknowledged state.
        with store.transaction() as db:
            write_audit(db,g.audit['run_id'],g.audit,'accepted',202)
        result,status=forward(target,action,body,key,control_client)
        return jsonify(result),status

    @app.get('/api/audit')
    @permitted('audit:read')
    def audit(): return jsonify(store.audit_events())

    @app.post('/api/jobs')
    @permitted('jobs:write')
    def jobs(): return jsonify(detail='The digital twin observes sources and does not control business runs'),403

    @app.post('/api/control/<action>')
    @permitted('runs:control')
    def control(action): return jsonify(detail='The digital twin observes sources and does not control business runs'),403
    return app


def from_env():
    settings=Settings.from_env()
    return create_app(settings,Store(settings.database_url,scenario=settings.scenario))

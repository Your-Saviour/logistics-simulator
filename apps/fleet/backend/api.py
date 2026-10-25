"""Authenticated private physical-transport API; no browser business commands."""
from functools import wraps
from hmac import compare_digest
import json
import os
from uuid import UUID

from flask import Flask, g, jsonify, request
import psycopg

from .store import FleetStore, Conflict


def create_app(store, credentials):
    names = {'storage', 'manufacturing', 'shipping', 'logistics', 'observer'}
    if (not isinstance(credentials, dict) or not credentials or not set(credentials) <= names
            or any(not isinstance(token, str) or not token for token in credentials.values())
            or len(set(credentials.values())) != len(credentials)):
        raise ValueError('Distinct nonempty server-side department/observer tokens required')
    app = Flask(__name__)
    app.config['MAX_CONTENT_LENGTH'] = 65536

    def authenticated(fn):
        @wraps(fn)
        def wrapped(*args, **kwargs):
            header = request.headers.get('Authorization', '')
            supplied = header.removeprefix('Bearer ') if header.startswith('Bearer ') else ''
            actor = next((name for name, token in credentials.items() if compare_digest(supplied.encode(), token.encode())), None)
            if actor is None:
                return jsonify(detail='Invalid service token'), 401
            g.actor = actor
            return fn(*args, **kwargs)
        return wrapped

    @app.errorhandler(ValueError)
    def invalid(exc):
        return jsonify(detail=str(exc)), 400

    @app.errorhandler(Conflict)
    def conflict(exc):
        return jsonify(detail=str(exc)), 409

    @app.errorhandler(psycopg.Error)
    def unavailable(_):
        return jsonify(detail='Fleet database unavailable; retry durable request'), 503

    @app.get('/v1/health')
    def health():
        with store.transaction() as db:
            db.execute('SELECT 1')
        return jsonify(version=1, status='healthy')

    @app.get('/v1/snapshot')
    @authenticated
    def snapshot():
        return jsonify(store.snapshot())

    @app.post('/v1/jobs')
    @authenticated
    def admit():
        body = request.get_json()
        if g.actor == 'observer' or (isinstance(body, dict) and body.get('producer') != g.actor):
            return jsonify(detail='Department cannot impersonate transport producer'), 403
        store.validate(body)
        with store.transaction() as db:
            exists = db.execute('SELECT 1 FROM fleet_jobs WHERE id=%s', (body['id'],)).fetchone() is not None
        job = store.admit(body)
        return jsonify(job), 200 if exists else 201

    def own_job(job_id):
        UUID(job_id)
        with store.transaction() as db:
            job = db.execute('SELECT * FROM fleet_jobs WHERE id=%s', (job_id,)).fetchone()
            if not job:
                return None
            destination = store.catalog[job['request']['destination']]['owner']
            if g.actor not in {'observer', job['producer'], destination}:
                return False
            job['events'] = db.execute('SELECT * FROM fleet_outbox WHERE job_id=%s ORDER BY kind', (job_id,)).fetchall()
            run = store.run(db)
            job['fleet_scope'] = run['sources'].get(g.actor)
            return job

    @app.get('/v1/jobs/<job_id>')
    @authenticated
    def job(job_id):
        result = own_job(job_id)
        if result is False:
            return jsonify(detail='Department cannot inspect another transport'), 403
        if result is None:
            return jsonify(detail='Unknown transport job'), 404
        return jsonify(result)

    @app.post('/v1/jobs/<job_id>/proofs/<kind>')
    @authenticated
    def proof(job_id, kind):
        UUID(job_id)
        if g.actor == 'observer':
            return jsonify(detail='Observer is read only'), 403
        return jsonify(store.submit_proof(job_id, kind, request.get_json(), g.actor))

    return app


def from_env():
    store = FleetStore(os.environ['DATABASE_URL'])
    store.migrate()
    return create_app(store, json.loads(os.environ['FLEET_TOKENS']))

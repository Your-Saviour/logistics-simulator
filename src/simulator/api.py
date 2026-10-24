"""Same-origin API for one independently deployed website."""
from contextlib import asynccontextmanager
import logging
from uuid import UUID, uuid4

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from pydantic import BaseModel, ConfigDict, Field
import psycopg

from .config import Settings
from .store import Store, Conflict
from .security import identify, Principal
from .scenario import Scenario
from starlette.concurrency import run_in_threadpool


class JobCommand(BaseModel):
    model_config=ConfigDict(extra='forbid')
    due_at: float = Field(ge=0, allow_inf_nan=False)
    quantity: int = Field(strict=True, ge=1, le=10000)


class ControlCommand(BaseModel):
    model_config=ConfigDict(extra='forbid')
    speed: int = 1
    confirm_run_id: UUID | None = None
    scenario: Scenario | None = None


def create_app(settings: Settings, store: Store, broker_check=None):
    if not settings.password:
        raise ValueError('Set an independent APP_PASSWORD for this application')
    if broker_check is None:
        from .messaging import broker_ready
        broker_check = lambda: broker_ready(settings.amqp_url)

    @asynccontextmanager
    async def lifespan(_):
        store.migrate()
        yield

    app = FastAPI(title=f'{settings.app.title()} simulator', lifespan=lifespan, docs_url=None, redoc_url=None)
    basic = HTTPBasic(auto_error=False)

    @app.middleware('http')
    async def command_context(request: Request, call_next):
        request.state.audit = {'actor':'anonymous','role':'anonymous','request_id':uuid4(),
                               'action':request.method+' '+request.url.path,
                               'idempotency_key':request.headers.get('Idempotency-Key',''),
                               'peer':request.client.host if request.client else ''}
        if request.method=='POST' and request.url.path.startswith('/api/'):
            try:
                request.state.audit['run_id']=await run_in_threadpool(store.command_scope)
            except psycopg.Error:
                logging.error('Command rejected: database unavailable request_id=%s',request.state.audit['request_id'])
                return JSONResponse(status_code=503,content={'detail':'Database unavailable; command was not accepted'},headers={'X-Request-ID':str(request.state.audit['request_id'])})
        response = await call_next(request)
        response.headers['X-Request-ID'] = str(request.state.audit['request_id'])
        if request.method == 'POST' and request.url.path.startswith('/api/') and response.status_code >= 400:
            try:
                await run_in_threadpool(store.rejected_command,request.state.audit,response.status_code)
            except psycopg.Error:
                logging.error('Rejected command audit unavailable request_id=%s status=%s',request.state.audit['request_id'],response.status_code)
        return response

    def permitted(scope):
        def authenticate(request: Request, credentials: HTTPBasicCredentials | None = Depends(basic)):
            principal = identify(settings,credentials.username,credentials.password) if credentials else None
            if principal is None:
                raise HTTPException(401,'Invalid username or password')
            request.state.audit.update(actor=principal.username,role=principal.role)
            if scope not in principal.scopes:
                raise HTTPException(403,'This identity cannot perform the requested action')
            return principal
        return authenticate

    def business_only():
        if settings.app == 'twin':
            raise HTTPException(403, 'The digital twin observes sources and does not control business runs')

    @app.exception_handler(Conflict)
    async def conflict_handler(_, exc):
        return JSONResponse(status_code=409, content={'detail': str(exc)})

    @app.exception_handler(psycopg.Error)
    async def database_handler(_, exc):
        return JSONResponse(status_code=503,content={'detail':'Database unavailable; retry with the same idempotency key'})

    @app.get('/api/health/live')
    def live():
        return {'application': settings.app, 'alive': True}

    @app.get('/api/health/ready')
    def ready():
        try:
            status = store.status()
            broker = bool(broker_check())
            roles = {x['role'] for x in status['heartbeats'] if x['healthy']}
            required = {'projection'} if settings.app == 'twin' else {'controller', 'worker'}
            ready = broker and required.issubset(roles) and status['run']['state'] not in ('failed', 'stalled')
            return JSONResponse(status_code=200 if ready else 503,
                                content={'application': settings.app, 'database': True, 'broker': broker, 'ready': ready})
        except (psycopg.Error, OSError):
            return JSONResponse(status_code=503, content={'application': settings.app, 'ready': False})

    @app.get('/api/status')
    def status(principal: Principal = Depends(permitted('status:read'))):
        value=store.status()
        return {'identity': principal.public(), 'application': settings.app, 'providers': settings.providers, 'quantum': settings.quantum,
                'simulation_time':Scenario.model_validate(value['run']['scenario']).instant(value['run']['granted']).isoformat(),**value}

    @app.post('/api/jobs', dependencies=[Depends(permitted('jobs:write')), Depends(business_only)])
    def schedule(request: Request, command: JobCommand, idempotency_key: str = Header(min_length=1, max_length=128)):
        if idempotency_key.startswith(('synthetic:','boundary:','synthetic-sample:')):
            raise Conflict('This idempotency key namespace is reserved for internal providers')
        return store.schedule(idempotency_key, command.due_at, {'quantity': command.quantity}, quantum=settings.quantum, audit_context=request.state.audit)

    @app.post('/api/control/{action}', dependencies=[Depends(permitted('runs:control')), Depends(business_only)])
    def control(request: Request, action: str, command: ControlCommand):
        if action == 'reset' and command.confirm_run_id is None:
            raise Conflict('Reset requires the current run ID as confirmation')
        if command.scenario is not None and action!='reset':
            raise Conflict('Scenario changes require a confirmed new run')
        return store.control(action, command.speed, expected_run_id=command.confirm_run_id, audit_context=request.state.audit,
                             scenario=command.scenario.model_dump(mode='json') if command.scenario else None)

    @app.get('/api/sources', dependencies=[Depends(permitted('status:read'))])
    def sources():
        return store.sources() if settings.app == 'twin' else []

    @app.get('/api/audit', dependencies=[Depends(permitted('audit:read'))])
    def audit():
        return store.audit_events()

    return app


def from_env():
    settings = Settings.from_env()
    return create_app(settings, Store(settings.database_url, settings.mode, settings.run_id, settings.epoch, scenario=settings.scenario))

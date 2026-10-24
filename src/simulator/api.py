"""Same-origin API for one independently deployed website."""
from contextlib import asynccontextmanager
import secrets
from uuid import UUID

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.responses import JSONResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from pydantic import BaseModel, Field
import psycopg

from .config import Settings
from .store import Store, Conflict


class JobCommand(BaseModel):
    due_at: float = Field(ge=0, allow_inf_nan=False)
    quantity: int = Field(strict=True, ge=1, le=10000)


class ControlCommand(BaseModel):
    speed: int = 1
    confirm_run_id: UUID | None = None


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

    def authenticate(credentials: HTTPBasicCredentials | None = Depends(basic)):
        if credentials is None:
            raise HTTPException(401, 'Sign in required')
        valid_user = secrets.compare_digest(credentials.username.encode(), settings.username.encode())
        valid_password = secrets.compare_digest(credentials.password.encode(), settings.password.encode())
        if not (valid_user and valid_password):
            raise HTTPException(401, 'Invalid username or password')

    def business_only():
        if settings.app == 'twin':
            raise HTTPException(403, 'The digital twin observes sources and does not control business runs')

    @app.exception_handler(Conflict)
    async def conflict_handler(_, exc):
        return JSONResponse(status_code=409, content={'detail': str(exc)})

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

    @app.get('/api/status', dependencies=[Depends(authenticate)])
    def status():
        return {'application': settings.app, 'providers': settings.providers, 'quantum': settings.quantum, **store.status()}

    @app.post('/api/jobs', dependencies=[Depends(authenticate), Depends(business_only)])
    def schedule(command: JobCommand, idempotency_key: str = Header(min_length=1, max_length=128)):
        return store.schedule(idempotency_key, command.due_at, {'quantity': command.quantity}, quantum=settings.quantum)

    @app.post('/api/control/{action}', dependencies=[Depends(authenticate), Depends(business_only)])
    def control(action: str, command: ControlCommand):
        if action == 'reset' and command.confirm_run_id is None:
            raise Conflict('Reset requires the current run ID as confirmation')
        return store.control(action, command.speed, expected_run_id=command.confirm_run_id)

    @app.get('/api/sources', dependencies=[Depends(authenticate)])
    def sources():
        return store.sources() if settings.app == 'twin' else []

    return app


def from_env():
    settings = Settings.from_env()
    return create_app(settings, Store(settings.database_url, settings.mode, settings.run_id, settings.epoch))

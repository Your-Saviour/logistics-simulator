# Digital twin foundation — Flask / React

The twin owns a Flask HTTP API and a separately supervised Python projection
consumer, PostgreSQL read model, RabbitMQ dependency and React/TypeScript
website. It never schedules business work or regulates HELICS time. FastAPI
is not used by this application entry point.

All installation, builds and tests run in Docker. From the repository root:

```sh
docker compose -f apps/twin/test.compose.yml run --build --rm tests
docker build -t logistics-simulator:twin-web -f apps/twin/web/Dockerfile .
docker compose -f apps/twin/test.compose.yml down
```

Runtime image: `docker build -t logistics-simulator:twin -f apps/twin/Dockerfile .`.
`ROLE=api` starts Gunicorn on 8000, `ROLE=projection` starts the independent
projection consumer. Configure `DATABASE_URL`, `AMQP_URL`, `SIMULATOR=twin`,
`APP_USERNAME`, `APP_PASSWORD` and JSON `APP_IDENTITIES`. An observer service
identity must explicitly receive `status:read`; employees cannot read audits.
`TWIN_SOURCES` is a JSON list of `{name,url,username,password}`. An empty list
is valid. Source credentials remain server-side; projection failures retain
the last snapshot and mark it disconnected. No source is required for the
API or projection process to start.

The frontend's fixed twin entry point is in `web/src/main.tsx`; its independent
Nginx image listens on 8080 and proxies `/api/` to `API_UPSTREAM` (default
`http://twin-api:8000`). No source credentials are bundled in it.

Runtime/test dependencies are locked in `requirements.lock`; React dependencies
are locked in `web/package-lock.json`. Python 3.12, Flask 3.1.3, Gunicorn 26.2.0,
Node 22 and TypeScript are the tested toolchains. Gunicorn workers supervise
HTTP only; no request starts a projection process.

Preserved-state cutover: stop the old twin API and projection consumer, retain
its PostgreSQL/RabbitMQ volumes and credentials, and start the new image with
the same configuration. The shared numbered/checksummed SQL migrations are
unchanged. No run is reset or data discarded by the Flask migration. Do not
run old and new projection consumers concurrently during cutover.

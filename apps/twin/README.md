# Digital Twin — Flask / React

Twin owns a Flask HTTP API, a separately supervised Python projection consumer,
PostgreSQL read model, RabbitMQ dependency and React/TypeScript website. It
observes departmental HTTP projections and never regulates HELICS time or owns
business work. The website's authoritative data comes from the Twin API.

From the repository root, build and test only inside guarded Docker:

```sh
make stack-unit APP=twin
make twin-deployment-check
make stack-check APP=twin
```

`twin-deployment-check` builds the production images and checks independent
startup, optional sources, stale snapshots, restart and catch-up with explicit
HTTP contract fixtures. For native departmental lifecycle and five separate
websites, see [SIMU-6 acceptance](../../docs/simu-6-acceptance.md).

For a persistent deployment, copy `.env.example` to untracked `apps/twin/.env`
and fill the three required secrets. Choose distinct random URL-safe database
and broker passwords, such as hexadecimal values, because they form connection
URLs. Add source, identity and control JSON only on the server. The persistent
entry point uses project `simu-twin-v1`, named PostgreSQL/RabbitMQ volumes and
separate API, projection and web services:

```sh
python3 scripts/docker_guard.py --wait -- docker compose --env-file apps/twin/.env -f apps/twin/compose.yml config --quiet
python3 scripts/docker_guard.py --wait -- docker compose --env-file apps/twin/.env -f apps/twin/compose.yml build api web
python3 scripts/docker_guard.py --wait -- docker compose --env-file apps/twin/.env -f apps/twin/compose.yml up -d
```

Its website is `http://127.0.0.1:8086` by default (`TWIN_PORT` overrides the port).
Configure an explicit ingress for remote access. This project and its volumes
are separate from disposable `stack-check` and `twin-deployment-check` projects.
Normal `down` retains its data; do not remove its named volumes during upgrades.
An existing deployment with different project or volume names needs explicit
volume mappings; this new entry point does not adopt old volumes automatically.
`TWIN_IMAGE` and `TWIN_WEB_IMAGE` can select prebuilt pinned images. Restart or
recreate the web service with the API when replacing API containers so Nginx
refreshes its upstream address. This documentation does not start or cut over a
persistent deployment automatically.

Runtime configuration requires `DATABASE_URL`, `AMQP_URL`, `SIMULATOR=twin`,
`APP_USERNAME`, `APP_PASSWORD` and JSON `APP_IDENTITIES`. A service observer
identity must explicitly receive `status:read`. `ROLE=api` starts Gunicorn on
8000. `ROLE=projection` starts the independent consumer; HTTP requests never
start it. Both roles use the same database and source configuration.

`TWIN_SOURCES` is a JSON array; `[]` is valid and requires no departmental
services. Each source has a unique departmental `name`, a base HTTP `url`,
`username`, `password`, and optional public `website_url`:

```json
[
  {
    "name": "storage",
    "url": "http://storage-api:8000",
    "username": "storage-observer",
    "password": "<server-side-secret>",
    "website_url": "https://storage.example.invalid"
  }
]
```

Source URLs must be reachable from the API and projection containers. Separate
Compose projects do not share service DNS by default; use routable addresses or
an explicitly shared network. Public website links are configured separately.
Source URLs must not embed credentials, query strings or fragments. The
consumer authenticates to `/api/projection`, validates the versioned complete
current-run snapshot/history contract, and commits source snapshots, cursors,
events and Twin revisions transactionally. Credentials remain server-side.
Disconnected sources retain their last successful snapshot, visibly stale;
unknown values are unavailable rather than zero stock or confirmed delivery.
Removed sources are hidden when the consumer applies its configuration. Optional
source health reports role heartbeat age, SQL pending/queued jobs and dead
letters. These job counts are not RabbitMQ queue depth. Missing readiness, broker
or queue evidence stays unknown; source HTTP reachability alone is not healthy
worker/controller evidence.

`GET /api/twin` returns live read-only facility state, per-source times and
event history. `GET /api/twin/events?after=N` supports revision catch-up and
optional SSE (`format=sse`). Source times do not imply an atomic federation
snapshot. `GET /api/sources` remains available for compatibility. Default
`controls` is empty. Operator-only controls require explicit server-side
`TWIN_CONTROL_TARGETS` configuration and dedicated owner credentials with
`runs:control`, for example:

```json
[
  {
    "name": "storage",
    "label": "Storage",
    "scope": "local",
    "source": "storage",
    "url": "http://storage-api:8000",
    "username": "control-service",
    "password": "<separate-server-side-secret>",
    "actions": ["hold", "resume"]
  }
]
```

Operators submit `POST /api/twin/controls/{name}/{action}` with an
`Idempotency-Key`; local requests also supply the observed `{run_id,epoch}`.
Stale or mismatched local state returns 409, and the departmental owner fences
the run inside its transaction. Twin persists control intent before forwarding;
the owner owns authorization, idempotency, audit and execution. Retry an unknown
outcome with the same key. Redirects are never followed.

An explicitly configured `scope: "federation"` owner has no `source` and supports
`pause`/`resume`. Twin reports global acknowledgement only for HTTP 200 with
`global_pause_acknowledged: true` or `global_resume_acknowledged: true` from that
owner. HTTP 202 means requested. A local hold never claims global pause.

The independent web image listens on 8080 and proxies `/api/` to `API_UPSTREAM`
(default `http://twin-api:8000`). Departmental public website links come from
source configuration; browser traffic does not carry source observer secrets.
Python dependencies are locked in `requirements.lock`; React dependencies are
locked in `web/package-lock.json`.

For a preserved-state cutover, stop old Twin API/consumer processes, retain
PostgreSQL/RabbitMQ volumes and credentials, apply the new numbered/checksummed
migrations and start the new image with the same identities. Do not reset
business runs or edit applied migration SQL. Validate configuration and recovery
in a disposable project before an operator-managed hosted cutover.

## Facility rendering

The facility uses Three.js through React Three Fiber, with Drei camera controls
and local Kenney Factory/Car Kit GLB assets (CC0 licenses in `web/public/models`).
It renders solid machines, robot arms, conveyors, racks, loading docks and trucks.
Drag to orbit, scroll/pinch to zoom, and use Reset view to restore the overview.
The existing asset list and keyboard selection remain available.

Geometry is schematic. Stock quantities and vehicle states come from the owned
read model; estimated travel still freezes on held/stale/disconnected sources.
A vehicle reaching its planned ETA still awaits source arrival confirmation.
WebGL2 is required for the 3D scene; browsers without it retain the data list.
Focused travel-state checks run with `npm run test:scene` inside the frontend
Docker environment.

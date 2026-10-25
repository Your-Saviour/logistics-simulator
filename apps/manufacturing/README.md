# Manufacturing V1 (SIMU-3)

This application owns its business API, PostgreSQL transitions, RabbitMQ worker,
scheduler, clock, sample effects and Angular website. Java never forwards API or
business work to Python. Connected mode uses only the private department-local
HELICS adapter defined in [the adapter protocol](../../docs/adapter-protocol.md).
The production model, employee workflow and typed storage boundaries are documented in [Manufacturing V1](../../docs/manufacturing-v1.md). The sample quantity API remains available for bootstrap compatibility.

The UI follows the Industrial anchor: warm black `#0B0C0A`, amber `#FFB800`,
monospace typography, square controls and 1px rules. The granted-time number is
its visual reference point; metrics, jobs, identities and audits come from the API.
Credentials live only in browser memory and clear at logout/reload.

## Toolchains and dependency ownership

- Java 21 LTS, Maven 3.9.11; Spring Boot 4.1.2. The Spring Boot BOM pins transitive
  versions; `backend/dependencies.lock` records the resolved dependency tree.
- RabbitMQ Java client 5.36.0. Publisher confirms, mandatory returns, persistent
  delivery, manual ACK/NACK and explicit dead-letter topology use its native API.
- Angular 21.2.25 (supported LTS), CLI/build 21.2.28, TypeScript 5.9.3, RxJS 7.8.2,
  Node 24. `frontend/package-lock.json` includes exact transitive versions/integrity.
  A compatible `undici` 7.30.1 build-tool override removes vulnerable upstream 7.x releases.
- PostgreSQL 17 and RabbitMQ 4.3.6 in isolated smoke/test configurations. Existing
  PostgreSQL schema and migration checksums remain authoritative at cutover.

Primary compatibility references checked during implementation:
[Spring Boot requirements](https://docs.spring.io/spring-boot/system-requirements.html),
[Angular support](https://angular.dev/reference/releases),
[Angular compatibility](https://angular.dev/reference/versions),
[RabbitMQ Java client](https://www.rabbitmq.com/client-libraries/java-client),
[RabbitMQ server support](https://www.rabbitmq.com/release-information),
[nginx stable releases](https://nginx.org/en/download.html).

## Build and test in containers

Run the canonical guarded checks from the repository root:

```sh
sh scripts/check_stack_unit.sh manufacturing
sh scripts/check_stacks.sh manufacturing
```

The first command runs the backend suite and compares the resolved Maven
dependency tree with `backend/dependencies.lock`. The latest verified result is
**40 tests passed** with an exact dependency-lock match. The second builds the
production backend/frontend images and runs shared HTTP, recovery and browser
checks against the independent manufacturing deployment. Its current production
verification is tracked separately from the unit result in `VERIFYING.md`.

Both scripts run framework builds and tests inside Docker, serialize Docker work
through `scripts/docker_guard.py`, and require a 20 GiB free-space reserve by
default. The host runs orchestration only. They clean up their isolated Compose
containers on exit. The application-owned `compose.test.yml` and
`compose.smoke.yml` describe disposable independent databases and brokers;
verification never attaches an existing deployment's state.

The backend suite covers strict quantity/time validation, unknown fields and
trailing JSON, DST elapsed seconds, independent roles, command replay/conflict,
atomic accepted audits, rejected actor attribution, concurrency, duplicate
effects, run/epoch fences, requested/granted barriers, power deferral, mandatory
routing returns, dead letters and unacknowledged delivery recovery. It also
exercises standalone lease termination/reacquisition and durable connected
finalization intent. Adapter tests use a protocol
fixture for same-ID retries and persisted session ownership; native federation
checks remain part of shared acceptance.

The application HTTP smoke uses a Python test-client container against the actual
Spring Boot and nginx/Angular services. It covers readiness, role denial, strict
validation, job execution, replay after time advance, audits and the served HTML.
Python is not a business execution dependency.

## Runtime settings and HTTP contract

Build contexts are the repository root. Backend Dockerfile:
`apps/manufacturing/backend/Dockerfile`; frontend:
`apps/manufacturing/frontend/Dockerfile`. Each backend listens on port 8000.
Run one process for each `ROLE=api`, `ROLE=worker`, `ROLE=controller`. All use
`SIMULATOR=manufacturing` and independent `DATABASE_URL`, `AMQP_URL`,
`APP_USERNAME`, `APP_PASSWORD`, optional `APP_IDENTITIES`. Service identities have
no implicit scopes; employees may read status and schedule jobs; operator scopes
include controls/audits. Credentials and request bodies are never written to audits.

Preserved routes: `GET /api/health/live`, `/api/health/ready`, `/api/status`,
`/api/sources`, `/api/audit`; `POST /api/jobs` with `Idempotency-Key` and
`{due_at,quantity}`; `POST /api/control/{hold,resume,speed,reset,finalize}`.
Errors use `{detail}` and every handled API request returns `X-Request-ID`.
Accepted commands and audits commit together. Rejected commands use a separate
attributed audit transaction; an unavailable database produces HTTP 503 and an
explicit audit-unavailable log, never an invented durable record.

The website listens on port 80 and proxies `/api` to `API_UPSTREAM` (default
`manufacturing-api:8000`). It offers login, run/grant status, production orders, material shortages, line capacity,
role-scoped controls, and operator audit history. Reset requires the current run
ID. The command idempotency key remains visible and retained after failed requests.

`CLOCK_MODE=standalone` uses SQL-persisted granted/requested/committed times,
`HANDOFF_QUANTUM` (finite >=1) and supported speeds 1/5/20/60. Hold stops new
advances. Existing due work and outputs gate further time requests. The singleton
controller holds PostgreSQL session advisory lock 8192102 and verifies it on every
tick; runtime transactions take schema gate 8192103 before locking the current run.
A standalone SQL connection or lease loss closes the old pooled connection and
retries acquisition without changing the persisted run ID, epoch or state. A held
run remains held, and graceful standalone shutdown preserves its state. The
connection is closed even if releasing its advisory lock fails. Connected native
owner loss follows the coordinated recovery rules below.
Workers execute only eligible due work under the current run/epoch and a healthy
controller heartbeat. Outbox resend survives lost broker ACKs. Three business
failures fail the run and dead-letter the delivery; dependency outages do not
consume the business retry budget.

`AUTONOMOUS_PRODUCTION=true` enables seeded materials/supply and demand inputs only
for explicit synthetic providers. `BOUNDARY_PROVIDERS` names exactly `materials`,
`demand`, `power`, each `synthetic` or `helics` (standalone allows only synthetic).
`SCENARIO` accepts `seed`, `time_zone`, offset-aware `start_at`, local whole-minute
`business_open`/`business_close`, unique Monday=0 weekdays, `interval_seconds`.
The normalized scenario is persisted on the run and changes only at confirmed
standalone reset. Quantities and UUIDv5 input identities reproduce the original
SHA-256 seeded provider contract. Simulation seconds always measure elapsed UTC;
business scheduling resolves local timezone gaps/repeated openings.

## Connected operation and recovery

Supply `FEDERATION_ID`, `FEDERATION_RUN_ID`, `FEDERATION_EPOCH`, `HELICS_PEERS`,
`HELICS_OUTPUTS`, `HELICS_ADAPTER_URL`, `HELICS_ADAPTER_TOKEN`, optional
`HELICS_TIMEOUT_SECONDS` (default 60), and explicit boundary providers. The
separate adapter owns `HELICS_CONFIG` and its native session, never business SQL.
Peer/output routing retains the existing endpoint/source/destination/boundary
configuration shape. A HELICS power provider uses its peer's `value_target`,
default `external-power/available_power_kw`.

Native material reservations retain their original request and track each new
attempt separately. A confirmed Storage shortage schedules a fresh request for
the same missing quantity after `MATERIAL_RETRY_QUANTA` simulation quanta
(default 5; allowed range 1–3600). Successful recipe parts remain assigned to
their batch. A rejected issue retains its receiving slots until Storage confirms
release; accepted or received custody cannot be reversed by a rejection.
Unknown, stale or contradictory outcomes appear in `material_recovery` in the
production API and projection with their quarantine reason. A blocked release
requires source reconciliation rather than another material order. Migration
012 preserves requests and reservations emitted by the preceding schema.

Connected batch completion reserves its fresh finished unit at the production
output and publishes a custody offer on Storage's `supply` boundary. Storage's
positive acceptance returns on `materials`; departure then clears the output
position. Only the matching receipt retires Manufacturing's pending custody.
The default destination is `storage.finished_receipt.dockNN` for cell NN;
`STORAGE_FINISHED_ENDPOINT` can select another catalogued finished receiving
dock. Configure both the outgoing `requests` and `supply` routes to Storage.
The unit barcode and batch lineage survive retries; completion sends no
quantity-only Storage receipt.

The Java controller persists adapter session and operation intents before HTTP
mutations. Native initialization, polling/receive processing and time requests
set a durable pending flag. Preparing a time request marks it in the same SQL
transaction as the requested watermark; only persisted grant/input commits and
receive acknowledgement clear it. Connected finalization requires a settled
executing native session and the SQL completion barrier. An accepted connected
`finalize` command records `state=finalizing` and a pending native-finalization
intent in the same transaction as its accepted audit. The controller sends the
finalize operation with a stable ID derived from the owning session. Only an
adapter reply confirming `state=finalized` permits the session and run to become
finalized together, scoped to the current run, epoch and session. Failure can
transition the finalizing run to stalled; SQL acceptance alone is not a claim of
native completion.

Lost replies retry the same request ID/body; polls have fresh IDs.
Boundary publication operation IDs derive from stable outbox ID and route.
Received envelopes enter the transactional inbox/jobs before `receive_ack`.
Persisted grants authorize execution only up to the actual grant, including
an earlier grant. Connected grants cannot exceed the persisted requested
watermark, and grants cannot advance a finalizing run. Missing/nonpositive/invalid
external power atomically defers due work by a quantum and records the reason before a worker can execute it. No
synthetic power fallback occurs. Pending jobs and boundary outputs prevent the
next request; internal broker output retains its SQL retry ledger.

Adapter/native loss or a controller error stalls the run. A persisted native
session cannot be recreated in the same epoch even if its grant was still zero.
There is no automatic native-state reconstruction, live rejoin or connected reset.
The federation owner must coordinate recovery and provision a new run/epoch while
retaining the prior data/journal for diagnosis. Adapter publication acknowledgement
is transport evidence, not destination database commit.

## Preserved-state cutover

Quiesce the old manufacturing API writers, controller and workers, take the normal
backup, then start the Java API with the same independent database and credentials.
Copied migrations 001–003 are byte-identical to the repository SQL and are verified
with SHA-256 against `schema_migrations`. Migration 004 adds manufacturing
adapter session/operation tables; migration 005 adds the persisted native
pending/state barrier. V1 migrations 006–007 add production records, canonical
workflow states and the correlated completion-event outbox. Any checksum mismatch aborts startup. The new
worker reuses `sample.jobs.v1` and the existing dead-letter topology. Start exactly
one controller only after validating mode/run/epoch configuration. Never run old
and new controllers together. Connected active native sessions require coordinated
federation shutdown/new epoch; copying SQL is not native HELICS recovery.

`VERIFYING.md` records commands actually exercised and remaining limits.

## Standalone terminal recovery

The standalone controller retains its SQL lease and waits while the current run
is `failed`, `stalled` or `finalized`, including when started against that state.
It advances no work in that state. A confirmed reset creates a fresh epoch that
the same controller observes and schedules; resetting does not require a process
restart. Connected terminal runs retain their coordinated new-epoch recovery rule.
The shared production-container acceptance checks finalize/reset and failed/stalled
SQL fixtures followed by reset and successful new-epoch execution.

## Independent persistent deployment / CyberLab

Copy `manufacturing.env.example` outside the repository and replace secrets.
Build from the repository root, one image at a time:

```sh
python3 scripts/docker_guard.py --label manufacturing-api -- docker compose --env-file /absolute/path/manufacturing.env -f apps/manufacturing/compose.v1.yaml build manufacturing-api
python3 scripts/docker_guard.py --label manufacturing-web -- docker compose --env-file /absolute/path/manufacturing.env -f apps/manufacturing/compose.v1.yaml build manufacturing-web
python3 scripts/docker_guard.py --label manufacturing-start -- docker compose --env-file /absolute/path/manufacturing.env -f apps/manufacturing/compose.v1.yaml --profile local up -d --no-build
```

The employee website binds localhost:8083 by default. Named SQL/broker volumes
persist; normal shutdown omits `--volumes`. Put TLS at the lab ingress.
For independent CyberLab role placement, omit `--profile local`, configure
`MANUFACTURING_DATABASE_URL`, `MANUFACTURING_AMQP_URL` and
`MANUFACTURING_API_UPSTREAM` with reachable addresses, then run API, worker
and controller on their assigned machines. Workers can replicate; only one
controller owns the SQL lease. Docker DNS does not span machines. Configure
role-local credentials and network access; no central service is required.
Connected mode additionally needs the private adapter/HELICS broker and explicit
peer routes described in the production document and adapter protocol.

Verify disposable deployments (preserves persistent V1 state):

```sh
make stack-unit APP=manufacturing
make stack-check APP=manufacturing
make manufacturing-connected-check
make manufacturing-deployment-check
```

The native check uses a real HELICS storage/power reference peer. It does not
claim a live hosted CyberLab or separate physical-machine deployment. See
[SIMU-3 acceptance](../../docs/simu-3-acceptance.md) for actual results.

`SCENARIO_PRESET=pump-assembly` selects the seeded pump/BOM/two-slot assembly
scenario on a fresh deployment. The canonical work-order states are queued,
ready, held, running and completed. Completion facts publish good output and
scrap together to the owned durable `production.events.v1` queue; see the
production document for scope, correlation and redelivery semantics.

Coordinated transport is opt in: set `FLEET_MODE=coordinated`, `FLEET_URL`,
`FLEET_TOKEN`, `FLEET_RUN_ID`, and `FLEET_EPOCH` on native roles. Missing or invalid
configuration fails startup. Disabled mode retains the existing custody behavior.
The worker durably admits finished-output movements after Storage accepts capacity;
output departure waits for physical pickup readiness. Incoming raw receipts wait
for physical arrival at an eligible native grant before they become consumable.
Fleet waits move jobs beyond the current grant, allowing native time requests to
continue. Native departure and receipt proofs commit with business state and relay
after commit; unavailable fleet HTTP retains requests and proofs in
`production_fleet_jobs` without fallback. Projection `handling.fleet` identifies
coordinated scopes without exposing credentials. Production creates outputs and
lineage at the native cell and consumes only confirmed input placements.

`FLEET_TIME_OFFSET` defaults to zero and must match this department's fleet
source mapping (finite, nonnegative seconds). Eligibility compares native grant
plus this offset against physical fleet time; outgoing effective times stay native.

Optional PLC/equipment execution and the editable FUXA cell are documented in
[manufacturing OT](../../docs/manufacturing-ot.md). The base deployment keeps
`OT_MODE=disabled`; the separate OT overlay is opt-in. Run
`make manufacturing-ot-check` for disposable real-PLC/HMI acceptance.

# Manufacturing foundation (SIMU-49)

This application owns its business API, PostgreSQL transitions, RabbitMQ worker,
scheduler, clock, sample effects and Angular website. Java never forwards API or
business work to Python. Connected mode uses only the private department-local
HELICS adapter defined in [the adapter protocol](../../docs/adapter-protocol.md).
This remains a sample quantity workflow; it does not implement manufacturing V1.

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
**24 tests passed** with an exact dependency-lock match. The second builds the
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
`manufacturing-api:8000`). It offers login, run/grant status, sample jobs,
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

`AUTONOMOUS_SAMPLE=true` enables seeded materials/supply and demand inputs only
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
pending/state barrier. Any checksum mismatch aborts startup. The new
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

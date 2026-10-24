# Logistics foundation (SIMU-50)

Go/Gin owns HTTP commands, PostgreSQL transactions, the sample quantity worker,
RabbitMQ delivery, seeded providers, and the durable clock barrier. Svelte and
TypeScript provide the dark amber sample website. There are no V1 transport
workflows and no Python business executor.

## Build and verify in containers

From the repository root:

```sh
sh scripts/check_stack_unit.sh logistics
sh scripts/check_stacks.sh logistics
```

The first command runs Go vet and the complete backend suite against isolated
PostgreSQL/RabbitMQ containers. The second builds the production API and website
serially, then runs HTTP contract checks, real dependency recovery checks and the
containerized browser checker. Both use `scripts/docker_guard.py` with a default
20 GiB free-space reserve; `SIMULATOR_MINIMUM_FREE_GIB` configures the reserve.
The host only orchestrates Docker: dependency installation, builds and service
tests execute inside containers.

The app-local `compose.test.yml` also publishes no host ports. Its Node probes
run inside the Docker network. `tests/recovery.sh` deliberately stops/restarts
only its own broker and database to check retained work, exactly-once effects,
unchanged processing retry budgets, database-outage 503s, and the authenticated
website proxy. Run backend fixtures separately from running application checks:
their setup truncates the isolated business tables. Never use a production
database for these fixtures.

Stop the app-local isolated project while retaining its named volumes:

```sh
docker compose -p logistics-go-test -f apps/logistics/compose.test.yml down
```

`backend/Dockerfile` builds one binary. `ROLE=api|worker|controller` selects its
process; API listens on 8000. `frontend/Dockerfile` serves port 80 and proxies
`/api` to `API_UPSTREAM` (default `logistics-api:8000`, host:port without scheme).
The compose file uses isolated demonstration credentials; configure independent
credentials for a real deployment. Container source and dependency installation
are reproducible from `go.mod`/`go.sum` and `package-lock.json`.

## Configuration and compatibility

Preserved variables: `SIMULATOR=logistics`, `DATABASE_URL`, `AMQP_URL`,
`APP_USERNAME`, `APP_PASSWORD`, `APP_IDENTITIES`, `CLOCK_MODE`,
`BOUNDARY_PROVIDERS`, `HANDOFF_QUANTUM`, `FEDERATION_ID`, `FEDERATION_RUN_ID`,
`FEDERATION_EPOCH`, `HELICS_PEERS`, `HELICS_OUTPUTS`, `SCENARIO`,
`AUTONOMOUS_SAMPLE`, and `HELICS_TIMEOUT_SECONDS` (default 60 seconds). The
connected backend additionally requires `HELICS_ADAPTER_URL` and
`HELICS_ADAPTER_TOKEN`; only the department-local adapter
receives `HELICS_CONFIG` and native HELICS ownership. `ROLE` selects the process.

Employee identities can read status and create jobs; operator identities can
also read audit and control the run. Service identities have no default scopes,
and can receive only explicit status/job scopes. Passwords and request bodies
are excluded from audit records. Accepted command and audit inserts share one
transaction. Rejected commands retain their captured request-time run and
principal attribution in a separate transaction. A client disconnect does not
cancel this audit write: it uses a cancellation-independent context bounded to
five seconds. Database unavailability or an audit timeout can still prevent
persistence; the failure is logged by request ID. A command rejected because the
database is unavailable returns 503.

Preserved endpoints: `/api/health/live`, `/api/health/ready`, `/api/status`,
`/api/jobs`, `/api/control/{hold,resume,speed,reset,finalize}`, `/api/sources`,
and `/api/audit`. Commands return 422 for invalid/unknown JSON fields, 401/403
for identity failures, 409 for state/idempotency conflicts, and 503 for database
unavailability. Idempotent job replays return the original row and add a command
audit. Quantity is a JSON integer from 1 through 10000, not a string or boolean.

The immutable 001–003 migration copies retain the original checksums.
`004_logistics_adapter.sql` adds native-session/operation journals and durable
boundary publication timestamps. `005_logistics_native_barrier.sql` persists
native initialization, pending-request and processing state. Migration startup
rejects edited applied SQL, mode changes, and mismatched connected run/epoch identities. Quiesce old Python
controllers/workers before applying this application to a preserved database;
back up and verify its migration checksums first. No migration resets data or
credentials. Connected recovery requires an owner-coordinated new run/epoch and
an archived/fresh deployment database, never a unilateral live reset.

## Durable execution and connected clock

Runtime transactions take the shared schema gate and current-run row lock before
job/outbox locks. Workers execute only current-run/current-epoch jobs at or below
the persisted grant with a healthy controller. Inbox and effect uniqueness stop
concurrent/redelivered jobs from adding duplicate quantity. The controller
advances only after all eligible jobs and boundary outputs settle; held runs
retain their time. Local pacing uses PostgreSQL `anchor` and `speed`, while
workers never derive simulation time from their own wall clock.

RabbitMQ topology is compatible with `sample.jobs.v1`, `sample.dead.v1` and
`sample.jobs.dead.v1`. Persistent mandatory messages require publisher confirms
before the SQL outbox publication marker. Manual ACK follows transaction commit.
A lost ACK redelivers harmlessly. Processing failures retry three times with a
persisted two-second backoff, then fail the run and dead-letter the delivery.
Broker/database failures reconnect without consuming that business retry budget.
Uncompleted published jobs are relayed again after five wall seconds.

Scenario defaults persist seed 1, Australia/Adelaide, an explicit offset start,
Monday–Friday 08:00–17:00, and 30-second seeded input slots. Synthetic transport
(demand) and destination (carrier) inputs use SHA-256 quantities and UUIDv5
identities compatible with the original providers. UTC elapsed seconds are
translated through the persisted IANA zone for business openings, including DST.

Connected controllers use [adapter protocol v1](../../docs/adapter-protocol.md).
A PostgreSQL advisory lease admits one controller. Its native session and each
operation intent are persisted before HTTP. Lost replies retry the same request
ID and body; each poll gets a fresh ID. Inputs are ACKed only after the backend
inbox transaction commits. Grants are persisted and never authorize execution
beyond their actual value, including an earlier-than-requested grant. Boundary
publications use stable outbox/route operation IDs. SQL completion precedes the
next time request. The SQL prepare transaction marks native pending before HTTP,
and finalization rejects initialization, pending requests or input/output
processing under the same run-row lock.

An accepted connected finalize command atomically records the run as `finalizing`
and its native session as finalizing/pending. This records intent, not completed
native shutdown. The controller handles that state before polling or requesting
time and sends a stable UUIDv5 operation derived from the session and `finalize`.
Only an adapter response with `state: finalized` permits one transaction to mark
the matching run, epoch and session `finalized`. No grant or new job execution is
authorized while finalizing; the controller exits after this acknowledgment. A
native finalization failure can transition `finalizing` to `stalled`. Standalone
finalization remains immediate once the completion ledger is clear.

Hold continues polling and output settlement. Adapter session loss or controller
restart stalls connected execution and requires coordinated new-epoch recovery;
there is no synthetic fallback or SQL-to-native restoration.

## Pinned dependencies and evidence

- Go 1.26.1 ([official downloads](https://go.dev/dl/)); Gin 1.12.0
  ([module documentation](https://pkg.go.dev/github.com/gin-gonic/gin@v1.12.0)).
- pgx 5.8.0 ([official module](https://pkg.go.dev/github.com/jackc/pgx/v5@v5.8.0));
  amqp091-go 1.10.0 ([RabbitMQ client](https://github.com/rabbitmq/amqp091-go)),
  using confirm mode, mandatory returns, and explicit ACK/NACK.
- Node 24.13.0; Svelte 5.57.2, Vite 8.3.5, Svelte Vite plugin 7.3.1,
  TypeScript 5.9.3, svelte-check 4.3.2. Exact registry tarballs and integrity
  hashes are locked. [Svelte docs](https://svelte.dev/docs/svelte/overview),
  [Vite guide](https://vite.dev/guide/) and the official npm registry provide
  primary package/toolchain metadata.
- Isolated test PostgreSQL 16.15 and RabbitMQ 4.3.6, selected from the
  [PostgreSQL support table](https://www.postgresql.org/support/versioning/) and
  [RabbitMQ release table](https://www.rabbitmq.com/release-information).
  Container base images are exact release tags; Go module and npm integrity
  locks verify application dependencies.

The suite exercises real PostgreSQL/RabbitMQ and an HTTP adapter protocol test
server. Native HELICS federation integration is a separate shared acceptance
run; these app-local tests alone do not claim a mixed-language federation or
physical multi-host validation. Initial pre-implementation failures were observed
for strict validation, calendars, service isolation, durable API behavior, and
frontend retries. All subsequent service builds/tests run inside Docker.

Latest container verification: Go vet and the full 19-test backend suite passed
against PostgreSQL 16.15 and RabbitMQ 4.3.6 (`ok simulator/logistics 1.657s`),
including null/scalar command rejection, audit persistence after a canceled
request, and connected finalization intent/failure visibility. The
recorded result is in
[logistics-review-green.log](../../.superpowers/sdd/simu-framework-migration/logistics-review-green.log).

The Svelte production build previously passed with both client tests green and
zero svelte-check errors/warnings. The earlier app-local real outage probe passed
broker/database stop-and-restart recovery with exactly five completed items from
two jobs, zero processing retry-budget loss, database-outage 503s, and the
website's authenticated API proxy. Shared production, rendered-browser and native
federation checks are separate evidence; the 19-test unit result alone does not
claim those checks passed.

## Standalone terminal recovery

The standalone controller retains its SQL lease and waits while the current run
is `failed`, `stalled` or `finalized`, including when started against that state.
It advances no work in that state. A confirmed reset creates a fresh epoch that
the same controller observes and schedules; resetting does not require a process
restart. Connected terminal runs retain their coordinated new-epoch recovery rule.
The shared production-container acceptance checks finalize/reset and failed/stalled
SQL fixtures followed by reset and successful new-epoch execution.

## Shared migration acceptance

Production HTTP/identity checks and independent-only-dependency startup/browser
checks passed. The mixed C#/Java/Go/PHP HELICS federation passed delayed/held
grants, correlated durable handoffs, external power, optional Flask Twin source
recovery, native acknowledgement/finalization and adapter-loss fencing. Business
runtimes also passed real broker/database recovery and terminal-run reset checks.
See [the shared verification record](../../docs/verification.md) for commands,
actual evidence and the untested hosted/physical-host limits.

# Storage V1 (SIMU-2)

The storage deployment owns an ASP.NET Core 10 API, PostgreSQL transaction ledger,
RabbitMQ worker and durable simulation-time controller. Its independent website
uses Vue 3 and TypeScript. It owns inventory, finite location capacity, receipts,
reservations, production material issues, picking and in-transit transfers. Employee
actions and seeded activity execute through the same durable C# job path. No business
process invokes Python. Connected mode uses the department-local HTTP HELICS adapter
specified in `docs/adapter-protocol.md`.

The website preserves the Industrial visual direction: warm black `#0B0C0A`,
amber `#FFB800`, monospace type, tabular clock numerals and flat rules. Its clock
and committed/granted/requested strip show the database's actual watermarks;
process, boundary and sample ledger information comes from the API. Credentials
remain in memory and are cleared on sign out. Employee/service identities never
receive operator controls.

See the [warehouse lifecycle, HTTP/domain contracts and persistent deployment guide](../../docs/storage-v1.md).

## Build and isolated verification

Run the canonical entry points from the repository root:

```sh
sh scripts/check_stack_unit.sh storage
sh scripts/check_stacks.sh storage
```

Both scripts route Docker workloads through `scripts/docker_guard.py`, which
serializes builds/tests and enforces the default 20 GiB free-space reserve.
Application builds, dependency installation and tests execute inside containers;
the host only orchestrates them. Run one verification workload at a time. Set
`SIMULATOR_MINIMUM_FREE_GIB` to increase the reserve when needed.

The unit command creates a uniquely named disposable PostgreSQL/RabbitMQ project,
runs the application-owned .NET harness, then removes that project's containers
and test volume. It does not start or change a deployed storage application.
The harness confirms/resets its test run, temporarily alters/restores a migration
checksum and verifies bounded retry failure. Run it against disposable state only.

The stack command builds production backend/frontend images sequentially, creates
the isolated generated storage stack, then runs shared HTTP fixtures, standalone
recovery checks and the browser checker. It stops its generated stack on exit.
Its test credentials and data are independent of deployed applications. No host
service ports are published. See [VERIFYING.md](VERIFYING.md) for scope and evidence.

The Storage V1 backend harness currently passes **126 checks against real
PostgreSQL and RabbitMQ**, including stock concurrency, duplicate commands,
capacity rollback, material issues, transfer accounting and provider retries.
See [SIMU-2 acceptance](../../docs/simu-2-acceptance.md) for current evidence.
Framework-foundation evidence remains in [shared verification](../../docs/verification.md).

`tests/Storage.Tests.csproj` is an executable assertion harness that exits nonzero
on failure. Without `STORAGE_INTEGRATION=true`, it runs the pure validation,
calendar/DST and seeded-input checks. The integration total includes those pure checks. `tests/smoke.py` remains an
application-owned HTTP smoke fixture; the canonical stack runner uses the shared
acceptance and recovery scripts.

## Runtime configuration

The backend image runs `dotnet Storage.dll`, listens on 8000 and selects the native
C# process using `ROLE=api|worker|controller`. Set `SIMULATOR=storage`.

Required shared environment variables are `DATABASE_URL` (PostgreSQL URL or Npgsql
connection string), `AMQP_URL` and `APP_PASSWORD`. `APP_USERNAME` defaults to
`operator`. `APP_IDENTITIES` is a JSON array with unique username, password and
employee/operator/service role; optional scopes may only narrow that role.
Service scopes default to none. Employee scopes are status:read/jobs:write;
operator also has runs:control/audit:read.

`CLOCK_MODE=standalone` defaults to explicit synthetic supply/requests providers.
`BOUNDARY_PROVIDERS` must name exactly these two boundaries. `HANDOFF_QUANTUM`
defaults to 1 and must be finite and at least one second. `SCENARIO` preserves the
existing seed, IANA timezone, offset-bearing start, local business hours, weekdays
(Monday=0) and interval fields. Elapsed seconds are UTC seconds; calendar openings
respect DST gaps and repeated times. `AUTONOMOUS_WAREHOUSE=true` seeds deterministic warehouse
supply/demand and local workflow actions. When absent, the historical
`AUTONOMOUS_SAMPLE` boolean supplies its default; verification disables it to isolate
employee effects. Standalone speed supports 1,5,20,60. Hold stops new local grants.
Reset requires `confirm_run_id`, archives the existing run and creates a new epoch.
On standalone Npgsql connection or timeout failure, the controller releases the
lost lease, retains the held/running run, epoch, scenario and watermarks, and
retries lease acquisition. It resumes eligible work after recovery without a run
reset. Workers leave database-outage deliveries unacknowledged and do not spend
business retry attempts.

For `CLOCK_MODE=helics`, also supply `FEDERATION_ID`, `FEDERATION_RUN_ID`,
`FEDERATION_EPOCH`, `HELICS_ADAPTER_URL`, `HELICS_ADAPTER_TOKEN`, explicit
`BOUNDARY_PROVIDERS`, `HELICS_PEERS`, and nonempty `HELICS_OUTPUTS` using the
existing routing shapes. `HELICS_CONFIG` belongs to the separately deployed
adapter, not the C# business process. `HELICS_TIMEOUT_SECONDS` defaults to 60.
Native initialization and polling continue while locally held. No synthetic
fallback occurs when an adapter or peer fails.

The controller persists its adapter session and every request intent before
sending. Transport retries retain request IDs and original JSON; poll snapshots
use fresh IDs. Received messages are acknowledged only after SQL inbox commit.
Boundary sends retain event identity and use a stable operation key per route.
The native request fence commits in the same transaction as requested time,
before HTTP send. Poll intents also fence finalization until grants, SQL inputs
and native receive acknowledgements settle. Finalize rejects initializing, pending
and unsettled native state. Accepted connected finalization persists
`finalizing` plus the native pending fence under the run lock before sending the
stable finalize operation. The controller handles it before polling or advancing
time, requires an adapter response with `state=finalized`, then atomically marks
the matching run/epoch/session `finalized`. Grants and competing native operations
cannot advance a finalizing run. Failed native finalization remains eligible for
`stalled`; accepting the command does not claim native completion.

Only a persisted completion barrier permits the next native time request; an
earlier grant authorizes only that grant. A lost native session stalls execution
and requires owner-coordinated new-epoch recovery. Existing native sessions are
never reconstructed from SQL or silently resumed by a replacement controller.

The frontend image serves port 80 and proxies `/api` to `API_UPSTREAM`, default
`storage-api:8000`. Use TLS at the deployment ingress when sending Basic credentials.
Existing routes remain `/api/health/live`, `/api/health/ready`, `/api/status`,
`/api/jobs`, `/api/control/{action}`, `/api/sources`, `/api/audit`.

Manufacturing finished-unit offers arrive on a configured HELICS `supply` peer;
acceptance and receipt proofs return on the `materials` output route. Acceptance
reserves the exact finished receiving dock and logical stock capacity without
creating stock. A matching departure imports the original barcode and contents
at that dock, continuing its version, movement sequence and custody generation.
`STORAGE_FINISHED_LOCATION` selects the logical grouping (default `FINISHED-A`).
Local receipts and movements respect these incoming promises. A blocked dock
retries the identical offer when capacity becomes available. The warehouse API
and projection include receiving handoffs alongside outgoing raw handoffs.

## Dependencies and preserved-state cutover

The SDK is pinned in `global.json` to 10.0.402 and the runtime image to ASP.NET
Core 10.0.13. Backend packages are Npgsql 10.0.3 and RabbitMQ.Client 7.2.2, recorded
with content hashes in the application-owned NuGet lock files. The client uses
v7 tracked publisher confirms: mandatory return or negative confirmation rejects
the awaited publish; only confirmed sends update the SQL outbox. Consumers disable
auto-ack and acknowledge after committed execution/failure state. Database failure
leaves delivery unacknowledged without burning business retry attempts.
The consumer requires a JSON object containing only a valid UUID `job_id`.
Malformed JSON, null, scalars, arrays, missing IDs and unknown fields are manually
rejected to the DLQ instead of entering a reconnect/redelivery loop. The review
regression verifies JSON null reaches the DLQ and the next valid job still executes.

Vue 3.5.44, TypeScript 5.9.3, Vite 8.3.5 and their build/test dependencies are pinned
in `frontend/package-lock.json`. Primary compatibility references checked:
[Npgsql 10](https://www.npgsql.org/doc/release-notes/10.0.html),
[RabbitMQ .NET v7](https://www.rabbitmq.com/client-libraries/dotnet-api-guide),
[Vue quick start](https://vuejs.org/guide/quick-start.html), and official NuGet/npm
package metadata. Node 24 provides the frontend build environment.

The owned copies of migrations 001–003 are byte-identical to the historical SQL;
applied SHA-256 checksums are checked before any change. Migration 004 adds only
storage adapter session/operation tables; migration 005 adds the persisted native
pending/state barrier. V1 migrations 006–007 add warehouse state and immutable
peer command identity/versioning. All ledger transactions take the shared
schema advisory gate and run-row lock; migration takes the exclusive gate.

Before production cutover, quiesce the old Python API/controller/workers, retain
PostgreSQL data and credentials, and use the existing run identity/configuration.
Do not run old and new controllers together. Standalone state can continue under
the existing ledger. A live connected federation cannot be taken over: coordinate
finalization/new epoch with its owner, retaining the old database/journal for
diagnosis. This repository change performs no live deployment or data reset.

## Standalone terminal recovery

The standalone controller retains its SQL lease and waits while the current run
is `failed`, `stalled` or `finalized`, including when started against that state.
It advances no work in that state. A confirmed reset creates a fresh epoch that
the same controller observes and schedules; resetting does not require a process
restart. Connected terminal runs retain their coordinated new-epoch recovery rule.
The shared production-container acceptance checks finalize/reset and failed/stalled
SQL fixtures followed by reset and successful new-epoch execution.

The controller owns a dedicated non-pooled PostgreSQL session for its advisory
lease. Closing that physical session releases ownership before a failure is
recorded through an ordinary pooled transaction. The backend regression verifies
a fresh physical session can acquire ownership after controller shutdown.

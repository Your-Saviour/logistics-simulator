# Storage V1 (SIMU-2)

Storage is an independent ASP.NET Core/Vue simulator. Its website, API, worker
pool, run controller, PostgreSQL and RabbitMQ operate without Manufacturing,
Logistics, Shipping or Twin. A private Python adapter owns native HELICS only.
The warehouse business engine and scheduler execute in C#.

## Warehouse lifecycle

The current run starts with empty stock and an explicit catalog/location
configuration. Defaults are raw `COMPONENT`, finished `PRODUCT`, `RAW-A` and
`FINISHED-A` capacity 500 each, and `DISPATCH` capacity 250. Capacity is shared by
all SKUs at a location, measured in item units.

1. `expect` plans a receipt with SKU, location, whole quantity and order/batch
   correlation UUID. `receive` references that receipt and commits physical stock.
2. `reserve` allocates the complete quantity of available stock. Production
   reservations require raw materials; customer reservations require finished
   goods. Shortages reject visibly without partial allocation.
3. `issue` consumes a production reservation once. `release` cancels an unpicked
   reservation and restores available quantity.
4. `pick` stages a customer reservation at its source. It remains on hand and
   reserved until departure. A picked reservation cannot be cancelled.
5. `transfer` references a picked reservation and a different destination. It
   removes source stock and records the quantity as in transit. It does not add
   destination inventory. `arrive` commits destination stock after a capacity
   check. A full destination leaves the complete shipment in transit.

Receipt, reservation and transfer IDs are the IDs of their creating commands.
Every record retains its correlation ID. Mutable records carry an increasing
version. The movement ledger records simulation time, command/reference,
correlation, physical and reserved deltas. A pick has zero stock deltas because
it changes workflow state without moving physical stock.

The UI shows searchable inventory, capacity, receipt and pick lists, transfers,
movement history and asynchronous command outcomes. Only valid state actions
are shown. An uncertain HTTP outcome retains the exact body and idempotency key
for retry. Employee identities can operate the warehouse; only operators can
hold/resume, change speed, reset, finalize or read the security audit.

## HTTP contract

Authenticate with the existing deployment-local identities. `status:read` allows
`GET /api/warehouse`; `jobs:write` allows `POST /api/warehouse/commands`.
All mutations require a 1..128 character `Idempotency-Key` header and explicit
`run_id`, `epoch`, `due_at` and `action`. `due_at` must be at least one handoff
quantum beyond the greater of granted/requested time. Use current `/api/status`
watermarks; the website fetches current status before submission and adds two
quanta plus one wall-second at the configured standalone speed.

Example request fields for `expect`:

```json
{
  "run_id": "20000000-0000-4000-8000-000000000001",
  "epoch": "30000000-0000-4000-8000-000000000001",
  "due_at": 2,
  "action": "expect",
  "sku": "COMPONENT",
  "location": "RAW-A",
  "quantity": 10,
  "correlation_id": "40000000-0000-4000-8000-000000000001"
}
```

`reserve` has the same fields plus `purpose: production|customer`. `receive`,
`release`, `issue`, `pick` and `arrive` instead require `reference: <UUID>`;
`transfer` requires `reference` and `destination`. Unknown fields, invalid codes,
booleans/fractions/string quantities and quantities outside 1..10000 reject.

HTTP 200 means the command was durably accepted, not that the warehouse effect
has completed. Poll the returned command ID in `GET /api/warehouse`'s `commands`.
Outcomes are `pending`, `completed`, or `rejected` with a reason; `job_status`
and attempts expose infrastructure retry/dead-letter state. Invalid state,
shortage and capacity are durable business rejections that settle the time
barrier. Dependency failures use the existing durable retry/hold behavior.
Malformed requests return 422, stale run/epoch/time and conflicting keys 409,
missing permissions 403 and unavailable PostgreSQL 503.

An identical replay returns the same command and its latest outcome, including
when held or finalized. Reusing its key with changed fields rejects. A browser
from an archived epoch cannot schedule into a new run. Internal `warehouse:`,
`synthetic:` and `boundary:` key namespaces cannot be supplied by employees.
The original sample `/api/jobs` contract remains available for bootstrap checks.

## Transactions and recovery

All API and worker transactions take the existing schema gate and current-run
row lock before reading stock or changing workflow state. This serializes
competing reservations, capacity checks, time preparation and resets across
worker replicas. SQL constraints additionally prevent negative or over-reserved
stock. Command outcome, workflow record, movement, inbox deduplication and
boundary outbox commit together. Expected business rejections use a savepoint,
so a rejected transition retains no partial writes.

RabbitMQ carries durable internal jobs with publisher confirmations and manual
acknowledgements after SQL commit. Duplicate/redelivered jobs return their
existing outcome. Worker restarts resume persisted jobs, and a run cannot request
a later grant while current-time work or boundary output remains unsettled.
Reset archives prior inventory by run and fences prior jobs using run/epoch.
Migration 006 adds warehouse tables; 007 adds workflow versions and immutable
peer-command identities. Migrations 001–005 and existing volumes are preserved.
No source update performs a live cutover or resets an existing deployment.

## Explicit autonomous providers

`AUTONOMOUS_WAREHOUSE=true` enables deterministic supply, production demand,
customer demand and transfer outcomes. For compatibility with existing checks,
when this variable is absent, `AUTONOMOUS_SAMPLE` supplies its boolean default;
when both are absent automation is enabled. Automated work now means warehouse
work. `false` leaves employee operations enabled and disables provider scheduling.

`BOUNDARY_PROVIDERS` selects exactly `supply` and `requests`, each `synthetic` or
`helics`; standalone requires both synthetic. Synthetic supply plans receipts
from the scenario seed and interval. Synthetic requests reserve available raw
materials for production and finished goods for customers. Provider-owned work
then receives/issues/picks/transfers automatically. Synthetic arrivals are
created only when requests are synthetic. HELICS ownership disables that
boundary's synthetic inputs. There is no fallback on peer failure.

Automation acts only on provider-created records; employee-created records remain
available for employee decisions. Both use the same validator, scheduled jobs
and transactional preconditions. Pending actions are deduplicated. When capacity
rejects automatic receipt/arrival, it can retry in a later scenario slot after
space becomes available. Demand is a single complete line; no partial allocation
or automatic supplier procurement for a rejected employee reservation is implied.

Configuration is immutable within a run. An operator's confirmed reset may supply
`scenario.warehouse` with `locations: [{code,capacity}]` and
`catalog: [{sku,kind}]`. Codes use 1..32 uppercase letters/digits/underscore/hyphen;
there must be 2..100 unique locations and 1..100 unique SKUs; kind is raw/finished.
Location capacity is 1..1000000. Calendar, seed, interval and timezone use the
existing scenario contract. The configuration and empty stock initialize once
per run. Connected scenario changes require coordinated new-epoch deployment.

## Connected domain protocol

The owned adapter accepts the published
[`storage-boundary` schema](../contracts/v1/storage-boundary.schema.json) alongside
the unchanged sample envelope. Input fixtures are in
`contracts/v1/fixtures/storage-boundary.json`. HTTP adapter commands remain v1.0.

| Input type | Owned boundary | Payload |
| --- | --- | --- |
| `storage.receipt.v1` | supply | sku, location, quantity |
| `storage.request.v1` | requests | sku, location, quantity, purpose |
| `storage.transfer.arrived.v1` | requests | reference (local transfer UUID) |

Every input uses the configured peer source/endpoint, federation, current run,
epoch and effective time. `aggregate_id` identifies an immutable peer command;
`aggregate_version` is 1. Retries reuse the original event ID. Event deduplication,
command scheduling and external aggregate identity are atomic. A new event ID
cannot replay an already accepted peer command aggregate. Late, differently
owned or malformed input fails explicitly; old epochs are fenced.

Successful actions publish `storage.<action>.completed.v1`. The payload is the
resulting receipt/reservation/transfer record, including local ID, run, SKU,
quantity, correlation, status and version. The envelope carries that record's
aggregate ID/version, originating command as causation ID, original correlation
and effective time one quantum after execution. Transfer records include source,
destination and reservation ID. Configured `HELICS_OUTPUTS` routes receive these
facts. The adapter is transport-only: receiving peers own interpretation of the
versioned facts. Domain rejection reasons remain in the warehouse command API;
no successful fact is emitted for a rejected command.

## Independent and CyberLab configuration

`apps/storage/compose.v1.yaml` is a persistent deployment, separate from generated
test projects. Copy `storage.env.example` to an untracked env file and replace all
placeholder secrets. For local dependencies, use the `local` profile. Builds
must be serialized through the guard:

```sh
python3 scripts/docker_guard.py --label storage-v1-backend -- docker compose --env-file /absolute/path/storage.env -f apps/storage/compose.v1.yaml build storage-api
python3 scripts/docker_guard.py --label storage-v1-web -- docker compose --env-file /absolute/path/storage.env -f apps/storage/compose.v1.yaml build storage-web
python3 scripts/docker_guard.py --label storage-v1-start -- docker compose --env-file /absolute/path/storage.env -f apps/storage/compose.v1.yaml --profile local up -d --no-build
```

The website binds localhost:8082 by default. Put TLS at the lab ingress and set
`STORAGE_BIND`/`STORAGE_PORT` deliberately. Named database and broker volumes
persist; normal shutdown omits `--volumes`.

For distributed CyberLab role placement, provide reachable
`STORAGE_DATABASE_URL`, `STORAGE_AMQP_URL` and `STORAGE_API_UPSTREAM`, omit the local
profile, and run the same backend image with `ROLE=api`, `worker` or `controller`
on the assigned endpoints. Only one controller holds the database lease; workers
can be replicated. Docker bridge DNS does not span hosts. Apply network controls
at the lab boundary and retain department-owned credentials/state. Connected
mode also requires the documented private adapter, HELICS broker and configured
peer routes; its native config uses reachable advertised addresses. See
[adapter protocol](adapter-protocol.md) and [operations](operations.md).
These are simulator deployment inputs for CyberLab; modifying adjacent CyberLab
modules or provisioning hosted machines is outside this repository change.

## Verification

Run from the repository root:

```sh
make stack-unit APP=storage
make stack-check APP=storage
make storage-connected-check
make storage-deployment-check
```

The first command runs real PostgreSQL/RabbitMQ accounting, concurrency, rollback,
barrier, epoch and provider regressions. The second builds production images,
runs employee HTTP lifecycle and real dependency/worker restart checks, then
uses Chromium to perform receipt → reservation → pick → transfer → arrival on
the independently served Vue website at desktop/mobile widths. Two actual worker
replicas process the warehouse workload and duplicate deliveries; a broker outage
also holds physical stock unchanged until recovery. The third runs
only Storage plus a real native HELICS broker/peer, exchanging typed receipts,
production/customer requests, transfer arrivals and correlated output facts,
including actual duplicate native deliveries. The fourth starts the persistent
packaging in a fresh disposable project, proving healthy startup without manual
restarts and validating the external-dependency profile. Local dependencies use
optional health-gated startup ordering, so externally configured roles remain
independent of local database/broker containers. Both additional V1 checks run
in the storage job of the migrated-stack CI workflow. All deployments are disposable;
these commands preserve persistent V1 deployment volumes.

Local evidence and limitations are recorded in [SIMU-2 acceptance](simu-2-acceptance.md).

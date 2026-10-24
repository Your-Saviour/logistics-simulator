# Logistics V1 (SIMU-4)

Logistics runs its own Go/Gin API, durable controller, RabbitMQ workers,
PostgreSQL state and Svelte employee website. Other departments and Twin are
optional. Python executes only wire validation and native HELICS transport in
the private adapter; Go owns every transport transaction.

The employee requests a route/SKU/item quantity, assigns an available vehicle,
loads, departs, unloads after confirmed arrival, and confirms destination receipt.
One vehicle has one active assignment, so its full load capacity is reserved
exclusively until unloading. Capacity is in whole items; oversized loads reject
without partial assignment. A vehicle must be at the origin. Unloading moves its
available location to the destination. Return journeys use explicit reverse routes.

The transfer state progresses through `requested`, `assigned`, `loaded`,
`in_transit`, `arrived`, `unloaded`, `received`. Source custody persists until
loading, vehicle custody persists through arrival, and destination custody starts
at unloading. `planned_eta` is departure grant plus configured journey seconds.
The scheduled arrival job may execute only at an eligible grant at or beyond ETA.
`arrived_at`, `unloaded_at` and `received_at` record separate confirmations; ETA
and unloading never imply destination receipt. The movement ledger and monotonically
increasing transfer version expose every successful state change.

## Employee HTTP contract

`GET /api/transport` returns `configuration`, `vehicles`, `transfers`, `commands`
and `movements`. It requires `status:read`. `POST /api/transport/commands` requires
`jobs:write`, an `Idempotency-Key` of 1..128 characters, and a JSON command:

```json
{
  "run_id": "20000000-0000-4000-8000-000000000001",
  "epoch": "30000000-0000-4000-8000-000000000001",
  "due_at": 2,
  "action": "request",
  "route": "WAREHOUSE-DISPATCH",
  "sku": "PRODUCT",
  "quantity": 8,
  "correlation_id": "40000000-0000-4000-8000-000000000001"
}
```

| Action | Action-specific fields |
| --- | --- |
| request | route, sku, quantity, correlation_id; optional external_reference UUID |
| assign | reference (local transfer UUID), vehicle |
| load, depart, arrive, unload, receive | reference |

Codes use 1..32 uppercase letters/digits/underscore/hyphen. Quantities are strict
JSON integers 1..10000. Unknown and action-inappropriate fields reject with 422.
Commands must name the current run and epoch. Employee `due_at` must be at least
one handoff quantum beyond both requested and granted time. The website refreshes
watermarks before sending and adds two quanta plus one wall-second at current
speed. An uncertain HTTP result retains the exact body/key for retry.

HTTP 200 means durable acceptance. Poll `commands` for `pending`, `completed` or
`rejected` with a reason, plus job status and infrastructure attempts. Business
state/capacity rejections settle the barrier without consuming infrastructure
retry budgets. Identical replays return the existing command's latest outcome;
changed commands or stale epochs return 409. Internal `transport:`, `boundary:`
and synthetic namespaces are reserved. Identity failures return 401/403 and
SQL unavailability returns 503. Employees operate transport; operators also own
run controls and audit reads. The sample `/api/jobs` contract remains available
under platform diagnostics for historical bootstrap checks.

## Configuration and persistence

The default scenario has WAREHOUSE, DISPATCH and CUSTOMER, four routes including
reverse journeys, TRUCK-1 (100 items, WAREHOUSE) and VAN-1 (25 items, DISPATCH).
Warehouse/dispatch journeys take 10 seconds; dispatch/customer take 20.
An operator's confirmed standalone reset may set `scenario.transport`:

```json
{
  "locations": [{"code":"A"},{"code":"B"}],
  "routes": [{"code":"A-B","origin":"A","destination":"B","journey_seconds":10}],
  "vehicles": [{"code":"TRUCK","location":"A","capacity":100}]
}
```

Configure 2..100 unique locations, 1..100 unique routes and vehicles, capacities
1..10000 items, journey duration 1..604800 seconds, and valid location references.
Configuration is immutable within a run. Existing calendar, seed, zone and interval
fields remain supported. Reset archives prior data and fences old deliveries.
Connected changes require owner-coordinated new run/epoch deployment.

Migration `006_transport.sql` adds vehicles, commands, transfers, movements and
peer command identities. Migrations 001–005 remain unchanged. Transactions take
the existing schema gate/current-run lock before domain rows. Command outcomes,
movement records, state, inbox and boundary outbox commit together. A savepoint
rolls back expected business rejections. Accepted command/audit writes are atomic.
RabbitMQ publisher confirmations and SQL-first acknowledgement retain work across
broker, database and worker outages. Eligible work and unsent outputs block later
time requests. Repeated arrivals cannot duplicate physical movements.

## Explicit standalone and connected providers

`BOUNDARY_PROVIDERS` selects `transport` and `destinations` as `synthetic` or
`helics`. Standalone requires both synthetic. `AUTONOMOUS_SAMPLE=true` now enables
deterministic transport demand and provider-owned transport workflows; false
leaves employee work enabled. Synthetic demand uses the persisted scenario seed,
calendar, interval and stable UUIDs. Destination providers confirm receipt only
after provider-owned goods unload. Synthetic inputs are disabled for HELICS-owned
boundaries and never replace a failed connected peer.

The [logistics boundary schema](../contracts/v1/logistics-boundary.schema.json)
defines `logistics.request.v1` (transport boundary, route/SKU/quantity/optional
external reference) and `logistics.receipt.v1` (destinations boundary, local transfer
reference). Input envelope aggregate_version is 1. The original sample schema
remains supported for shared foundation verification. The private adapter also
accepts the existing [storage domain schema](../contracts/v1/storage-boundary.schema.json).

A configured storage peer may send `storage.transfer.completed.v1` on transport.
Its record must be in transit, match envelope aggregate/version/correlation/run,
and have an origin/destination matching a configured route. Logistics retains its
ID as `external_reference`. Configure warehouse codes and vehicle locations to
match Storage's actual origin/destination (for example FINISHED-A → DISPATCH).
Every domain input validates configured sender endpoint/source, federation,
run/epoch, effective time and strict payload. Event IDs deduplicate; a new event
ID cannot replay the same immutable source aggregate. ACK follows SQL commit.

Successful actions publish `logistics.<action>.completed.v1`, with the complete
transfer record, original correlation, command causation, transfer aggregate and
version, one quantum after execution. A receiving Shipping peer consumes these
facts and sends `logistics.receipt.v1` after `logistics.unload.completed.v1` to
acknowledge destination receipt. For outputs routed to destination `storage`,
only successful unloads with a storage reference emit
`storage.transfer.arrived.v1`, boundary `requests`, payload `{reference}`. This
uses Storage's existing arrival command and never treats planned ETA as receipt.
Other facts use general configured routes. HTTP and RabbitMQ remain internal.

## Independent deployment and CyberLab

Copy [the environment example](../apps/logistics/logistics.env.example) to an
untracked file and replace every example secret. Build/start persistent packaging:

```sh
python3 scripts/docker_guard.py --label logistics-api -- docker compose --env-file /absolute/path/logistics.env -f apps/logistics/compose.v1.yaml build logistics-api
python3 scripts/docker_guard.py --label logistics-web -- docker compose --env-file /absolute/path/logistics.env -f apps/logistics/compose.v1.yaml build logistics-web
python3 scripts/docker_guard.py --label logistics-start -- docker compose --env-file /absolute/path/logistics.env -f apps/logistics/compose.v1.yaml --profile local up -d --no-build
```

The website defaults to localhost:8084. Put TLS at the lab ingress. Named volumes
retain state; shutdown omits `--volumes`. The `local` profile supplies owned SQL
and RabbitMQ. To place roles on separate CyberLab nodes, omit it and provide
reachable `LOGISTICS_DATABASE_URL`, `LOGISTICS_AMQP_URL` and
`LOGISTICS_API_UPSTREAM` (host:port without scheme). The same backend image runs
with `ROLE=api|worker|controller`; workers replicate, one controller holds its SQL
lease. Docker bridge DNS does not span machines. Department credentials and state
remain separate. Physical-host network provisioning is outside this source change.

Connected mode additionally supplies federation/run/epoch, peer/output routes,
adapter token and URL, and native HELICS configuration with reachable advertised
addresses. The `connected` profile runs a private adapter with a durable journal;
build its image separately through the guard. Native loss stalls the run and
requires coordinated epoch recovery. There is no automatic live cutover.

## Verification

```sh
make stack-unit APP=logistics
make stack-check APP=logistics
make logistics-connected-check
make logistics-deployment-check
```

All service builds/tests run in Docker. Guarded workloads retain 20 GiB by default;
the guard resolves Git's common directory so local worktrees share one lock.
Test project names include a checkout-specific suffix, and connected generation
leaves active standalone manifests untouched. `BROWSER_CHECK_IMAGE` selects an
isolated browser image when required. The stack check includes real dependency recovery, two worker replicas, transport
lifecycle and worker restart, plus desktop/mobile employee browser flows. The
connected check uses actual native HELICS with a configured storage/shipping
reference peer and duplicate delivery; it needs no other departmental app. The
deployment check starts persistent packaging in a disposable project and runs a
worker independently with external SQL/broker URL configuration. CI invokes these
checks in the Logistics matrix job. Local versus hosted evidence is recorded in
[SIMU-4 acceptance](simu-4-acceptance.md).

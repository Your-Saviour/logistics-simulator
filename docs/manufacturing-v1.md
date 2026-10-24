# Manufacturing V1 (SIMU-3)

Manufacturing owns an independent Spring Boot API, RabbitMQ worker pool, durable
controller, PostgreSQL database and Angular website. Its private Python adapter
owns native HELICS only. Storage and Twin are optional in standalone mode.

## Production model

Configuration is immutable within a run. `scenario.manufacturing` defines
`products: [{sku,bom:{RAW_SKU: units_per_item},duration_seconds,scrap_percent}]`
and `lines: [{code,capacity,products:[SKU]}]`. Capacity counts simultaneous
batches. Duration applies to the complete batch. Default PRODUCT consumes two
COMPONENT per item, runs for 20 simulation seconds on LINE-1 (one batch), and
has zero scrap. Scrap is floor(batch quantity × scrap percent / 100).

Products and raw material codes are distinct. Quantities are integers, batch
quantities 1..10000, BOM units 1..100, duration 1..86400 seconds, scrap 0..100,
and line capacity 1..100. Every product needs a compatible line. A confirmed
standalone reset may change configuration; earlier run records remain archived.

Work orders move queued → ready → running → completed. Before start an
employee can hold and re-release an order. A running batch cannot be held:
materials have already been consumed. Starts wait for the entire BOM, an
available line slot and positive configured external power. Each start consumes
materials atomically and schedules a durable finish. Output and scrap are
recorded exactly once. Finish cannot execute before its due time or the actual
grant. Missing power defers current work until a later grant; this V1 treats
power as permission to transition, rather than integrating energy consumption
or continuous processing progress during an outage.

## HTTP commands and observations

`GET /api/production` requires `status:read` and returns persisted configuration,
materials, orders, commands, production history and material/output movements.
Employee history is domain activity; `/api/audit` remains operator-only security
history. The existing status/jobs/control routes remain compatible.

`POST /api/production/commands` requires `jobs:write`, an `Idempotency-Key` of
1..128 characters and a JSON body with `run_id`, `epoch`, `due_at`, `action`:

| Action | Additional fields |
| --- | --- |
| create | product, line, quantity, optional correlation_id UUID |
| release / hold | reference (work order UUID) |
| supply | sku, quantity; synthetic material provider only |

Work order ID is the creating command ID. Start and finish are scheduler-only.
HTTP 200 means durable acceptance; poll `commands` for completed/rejected outcome
and reason. Expected workflow errors commit a rejection with no partial business
writes. Unknown fields/type errors return 422; stale scope/time or conflicting
keys 409; missing permission 403; unavailable SQL 503. Identical retries return
the latest result even after time advances. New commands must be at least one
quantum beyond the greater of requested/granted time. Reserved provider key
prefixes cannot be submitted by employees.

The website retains the exact body and key after an uncertain HTTP result. Retry
that command or explicitly discard it before preparing another; discarding a
client retry does not cancel a command already accepted by the server.

## Providers and HELICS

`BOUNDARY_PROVIDERS` explicitly selects materials/demand/power as synthetic or
helics; standalone permits synthetic only. `AUTONOMOUS_PRODUCTION` controls
seeded inputs and automatic release of provider-created queued orders. It defaults to
`AUTONOMOUS_SAMPLE` for bootstrap compatibility, and then true. Employee queued orders
are never automatically released, and employee-held provider orders stay held.
The durable scheduler still starts released orders and finishes running batches
when automation of new inputs is disabled.

Synthetic demand and materials use the persisted scenario seed, calendar and
interval. All changes use the same queued command executor as employees.

Connected production uses versioned transport envelopes and one private HELICS
combination federate:

| Input | Boundary | Meaning |
| --- | --- | --- |
| manufacturing.demand.v1 | demand | product, line and quantity create a queued order |
| storage.issue.completed.v1 | materials | issued production reservation credits raw material once |
| available_power_kw value | power | positive finite value permits production transitions |

Storage fact payload and envelope IDs, run, correlation and version must match.
Other valid storage lifecycle facts are acknowledged as observations and never
credit materials. The original issue envelope is retained with its queued job
for correlation/audit inspection. Event ID deduplication plus immutable source/type/aggregate identity prevent a
second event ID crediting the same issue. Peer source/endpoint, destination,
federation and run/epoch must match configured ownership. Late inputs fail;
old epochs are fenced. No synthetic material fallback occurs.

Release publishes `storage.request.v1` for the BOM at RAW-A with purpose
production; requirements above 10000 split into stable uniquely identified
requests. Storage retains reservation/issue ownership. Completion publishes
`storage.receipt.v1` for good output at FINISHED-A. Zero output emits no receipt.
All envelopes retain work-order correlation, stable event/aggregate IDs and
execution time plus one handoff quantum. `STORAGE_RAW_LOCATION` and
`STORAGE_FINISHED_LOCATION` override location codes. Configure a storage route
in HELICS_OUTPUTS. Storage's provider workflow handles boundary-owned
reservations/issues and expected receipts; shortage outcomes remain visible
in Storage. This version does not automatically retry a rejected storage
reservation under a new identity: an operator must resolve supply/recovery.

Existing sample envelopes remain compatible for platform acceptance. Domain
work never uses Python business logic or cross-department RabbitMQ jobs.

## Recovery and deployment

The schema gate/current-run row lock serializes commands, starts, capacity,
material accounting, reset and time preparation. Domain rows, inbox dedup,
command outcomes, audits and boundary outbox commit atomically. Durable jobs
are relayed through publisher confirms and manual acknowledgements; workers
can replicate. Future work does not block current time; unfinished due work
and unsent boundary outputs do. Database/broker loss retains the SQL ledger.
Native adapter/controller loss requires coordinated federation recovery in a
new run/epoch; SQL restart is not native-state restoration.

Migration 006 adds manufacturing tables; 007 adds completion events and canonical queued/ready workflow states. Applied migrations 001–006 and
persistent deployment volumes are preserved. Packaging and exact verification
commands are documented in the application README and acceptance record.

Connected storage routing requires both command boundaries on the same native
endpoint, for example:

```json
[
  {"endpoint":"storage/events","destination":"storage","boundary":"requests"},
  {"endpoint":"storage/events","destination":"storage","boundary":"supply"}
]
```

Storage publishes its lifecycle facts back to `manufacturing/events` with
destination `manufacturing` and boundary `materials`. Configure Manufacturing's
materials peer as source `storage`, endpoint `storage/events`. Configure demand
and power peers explicitly as well. Align SKU/location catalogs and arrange raw
stock in Storage through its own providers or employee workflows. Reservation,
receipt and transfer notifications are observations; only an issued production
reservation authorizes raw material credit at the factory.

## Pump assembly and completion facts

Set `SCENARIO_PRESET=pump-assembly` on a fresh deployment for the persisted
[seeded pump scenario](../apps/manufacturing/backend/src/main/resources/scenarios/pump-assembly.json):
PUMP uses one HOUSING, one IMPELLER and two SEAL units, 45 simulation seconds per
batch, 5% configured scrap and two simultaneous batches on ASSEMBLY-1. Explicit
SCENARIO fields override the preset. Existing runs remain pinned; use a confirmed
reset with the desired scenario or a fresh database to change them.

Completion records one `manufacturing.batch.completed.v1` fact containing good
output and scrap quantities with run, epoch, batch and order correlation. A
transactional outbox publishes it to this department's durable RabbitMQ queue
`production.events.v1` using publisher confirms. Pending completion facts gate
the next grant, including when good output is zero. SQL records one fact per
batch; transport redelivery retains its event ID and consumers must deduplicate
that ID. This internal fact is separate from the HELICS storage receipt for good
physical output. The `events` collection is part of `GET /api/production`.

A confirmed reset archives the prior run, including any unsent completion facts,
and fences their publication into the new epoch. Those records remain in SQL
for diagnosis/export; reset does not drain archived work into a new scenario.
Prerequisite deferrals retry at the next grant and do not inherit the wall-clock
delay used to resend an uncertain broker publication.

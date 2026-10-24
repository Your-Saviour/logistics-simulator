# Application and boundary contracts v1

The shared wire envelope is published as [sample.completed.schema.json](../contracts/v1/sample.completed.schema.json). Each department validates it in its selected backend; `src/simulator/contracts.py` remains the Python reference model and adapter validator. [boundaries.json](../contracts/v1/boundaries.json) names ownership and units. Schemas and routes are available directly to application implementers; the execution plan is not a required dependency.

## HTTP

Each website proxies `/api` only to its own API. APIs use independent HTTP Basic credentials. Vue, Angular, Svelte and React hold browser credentials only in memory and remove them on sign-out. Shipping’s Blade/Livewire website uses a department-local, HttpOnly/same-site server session with CSRF checks; every public component action revalidates its identity and scope. It retains HTTP Basic for the API. Use TLS at the deployment ingress outside loopback development; HTTP Basic does not encrypt credentials. Migration test websites have private service-DNS origins and publish no host ports; historical review URLs use loopback bindings. No central identity service is required.

- `GET /api/health/live`: process liveness and application identity, public.
- `GET /api/health/ready`: database/broker checks plus current controller/worker or projection heartbeat. Returns 503 on missing dependencies, stale heartbeats, failed or stalled runs.
- `GET /api/status`: authenticated application, identity/scopes, persisted scenario, local business timestamp, run, providers, sample effects, jobs and heartbeats. Requires `status:read`.
- `POST /api/jobs`, with `Idempotency-Key`: body `{"due_at":10,"quantity":2}`. An employee/autonomous sample command is valid only at least one configured quantum beyond the maximum of granted/requested time. Quantity is an integer from 1 to 10000. A key replay returns its existing job even after time advances or work is deferred; a changed original body returns 409. Keys are scoped to the current run. Internal `synthetic:`, `synthetic-sample:` and `boundary:` key namespaces are reserved. Requires `jobs:write`.
- `POST /api/control/hold`, `/resume`, `/speed`, `/finalize`, `/reset`: JSON body, using `{"speed":5}` or `{"confirm_run_id":"<current-run-uuid>"}` as appropriate. Reset confirmation is checked under the current-run lock. Requires `runs:control`; employees and services cannot obtain this permission. Twin returns 403 for all business mutations. Confirmed standalone reset optionally accepts a validated `scenario` object; a new epoch retains the previous scenario if it is omitted.
- `GET /api/sources`: twin read-model source statuses, observation timestamps and per-source snapshots. An unconfigured twin returns an empty list.

`GET /api/audit` requires `audit:read` and returns up to 100 retained accepted/rejected attempts. Each row includes validated actor/role, run, request ID, action, status, idempotency key and optional job target; it excludes credentials and request bodies.

Roles: operators can read status, submit jobs, control local runs and read audits; employees can read status and submit jobs; services require an explicit subset of `status:read` and `jobs:write`. `APP_IDENTITIES` supplies per-application credentials/roles/scopes as JSON. The generated observer used by the twin has only `status:read`. Independent API credentials prevent cross-application identity reuse.

Unauthorized requests return 401, forbidden scopes 403, validation failures 422, conflicting commands 409 and database unavailability 503. Handled requests return `X-Request-ID`. Bodies are JSON objects; unknown fields, trailing documents and coerced quantities are rejected. Shared request schemas/positive-negative HTTP fixtures are in [contracts/http/v1](../contracts/http/v1). The bootstrap frontend polls its own API; no browser talks directly to databases, RabbitMQ or HELICS.

## Boundary exchange

`sample.completed.v1` represents only the sample count, not an inventory receipt, production completion, shipment or delivery. Domain implementations add new versioned types and payload validators rather than pretending this count models departmental workflows.

The envelope contains event/schema/type, federation/run/epoch, correlation/causation/aggregate IDs, aggregate version, source/destination, boundary, effective simulation time, wall timestamp, quantity unit and payload. UUID event IDs remain stable across retries. Duplicate IDs have one business effect. Old runs/epochs are fenced, unknown routing/owners are rejected, and a late event cannot rewrite already-granted history. This sample creates one aggregate per operation; richer aggregate sequencing and prerequisite deferral belong with domain-specific contracts.

- Time: seconds since run start; minimum handoff quantum 1 second, positive and configurable. Wall-time retries are independent of simulation speed.
- Count: integer `item`; external power: typed HELICS `double` in `kW`.
- Ownership: manufacturing owns batches, storage owns inventory/reservations/receipts, logistics owns journeys, shipping owns orders/shipments. External power owns available-power conditions.
- `BOUNDARY_PROVIDERS` explicitly selects one string, `synthetic` or `helics`, for every declared boundary. Standalone uses synthetic providers; connected mode permits explicitly synthetic open boundaries alongside selected HELICS peers. Duplicate provider lists, missing boundaries or unsupported providers fail startup. No peer failure changes the configured provider.
- RabbitMQ carries internal job IDs only. Connected boundary sample events are sent only through HELICS. A received boundary sample produces one local effect and is not echoed, avoiding a feedback loop.

HELICS is a combination-federate adapter with message endpoints and typed publications/subscriptions, using pinned Python/native package 3.6.1. Native handles belong to the separately supervised, department-local Python adapter process. Each C#/Java/Go/PHP controller owns its SQL scheduling/completion barrier and communicates over the authenticated [versioned local protocol](adapter-protocol.md); the adapter has no business database access. Endpoints are named `<simulator>/events`; publications `<simulator>/completed_items` and `external-power/available_power_kw`. Sample messages are sent at the current grant; the configured positive period/timeDelta makes the receiver eligible at the next quantum, matching payload effective time. Future `SendToAt` schedules the send itself and would add an additional quantum in this configuration; the native smoke test pins that distinction.

`HELICS_PEERS` maps each connected boundary to its expected source and endpoint. `HELICS_OUTPUTS` maps local sample outputs to a destination, endpoint and receiving boundary. The controller rejects a mismatched transport sender, envelope owner, federation identity or destination. The example maps manufacturing → storage → logistics → shipping → manufacturing; open domain boundaries are explicitly synthetic. Manufacturing samples are deferred to the next grant while external power is unavailable, including newly ingested work.

Reference semantics: [HELICS endpoint example](https://docs.helics.org/en/main/user-guide/examples/fundamental_examples/fundamental_endpoints.html), [Python API](https://python.helics.org/api/capi-py/), [RabbitMQ acknowledgements/confirms](https://www.rabbitmq.com/docs/confirms).


## Seeded boundary interfaces

[seeded-input.schema.json](../contracts/v1/seeded-input.schema.json) defines immutable synthetic inputs with deterministic input ID, run/epoch, application, boundary, effective time, item quantity and kind: `demand`, `supply`, `receiving` or `carrier`. Manufacturing materials use supply inputs; storage supply and shipping goods use receiving inputs; logistics destinations and shipping carrier use carrier inputs. These are bootstrap interfaces, not complete domain workflows.

`Scenario` persists `seed`, `time_zone`, timezone-aware `start_at`, local `business_open`/`business_close`, weekday indices (Monday=0) and `interval_seconds`. Set initial values with `SCENARIO` JSON on a new run database, or use an operator-confirmed reset with a scenario object. Restart never replaces active scenario settings with changed environment defaults. The calendar skips closed hours/weekends, uses elapsed UTC seconds, chooses the next valid minute at DST gaps and considers both valid openings during a repeated local hour.

CI runs `make schema-check`: published schemas must match runtime models; valid fixtures must pass both; invalid/analytics fixtures must be rejected. The business-ingestion regression additionally verifies analytics input leaves both inbox and effects unchanged.

## Local adapter and durable barriers

[Adapter command schema](../contracts/adapter/v1/command.schema.json) and
[reference initialize fixture](../contracts/adapter/v1/fixtures/initialize.json)
define initialize, poll, receive/persist acknowledgement, request/grant,
publication acknowledgement, health, checkpoint and finalize. Each command has
protocol/request/run/epoch/session identity. Native mutations journal intent
before execution; exact retries retain request ID/body. Inputs remain retained
until backend inbox commit and acknowledgement. The backend persists a native
pending/processing fence before HTTP, in the same SQL transaction that prepares
a requested watermark. It clears the fence only after granted time and incoming
work are durably recorded and receive acknowledgement has completed.

Connected finalization first records `finalizing`, then reaches `finalized` only
after native acknowledgement. A failure during that interval must remain visible
as stalled/unavailable; a SQL status cannot prove native disconnect. Standalone
finalization is local and immediate once due work/outputs settle. Future jobs
remain archived and never execute in a finalized run.

The twin is never a time regulator or business mutator. Its source snapshots
contain public status/identity fields, not source credentials. Each source has
its own observed/granted/committed watermark; source connectivity does not prove
a federation-wide atomic snapshot or a ready business scheduler.

## Manufacturing domain extension

[Manufacturing V1](manufacturing-v1.md) adds queued production commands and
run-scoped manufacturing snapshots. The transport-only
[`manufacturing-boundary` schema](../contracts/v1/manufacturing-boundary.schema.json)
adds typed demand while retaining storage's issued reservation facts and
request/receipt inputs. The adapter command schema includes this union;
published sample and storage-boundary schemas remain unchanged.

## Shipping V1

Shipping commands and provider ownership are documented in [Shipping V1](shipping-v1.md).
The additive [shipping wire schema](../contracts/v1/shipping-boundary.schema.json)
and [order fixture](../contracts/v1/fixtures/shipping-boundary.json) cover shipping
orders, owned confirmations, explicit storage operations and the production/carrier
wire contracts. The existing storage/sample schemas remain unchanged.

# Application and boundary contracts v1

The runnable Python envelope is `src/simulator/contracts.py`; its published JSON Schema is [sample.completed.schema.json](../contracts/v1/sample.completed.schema.json). [boundaries.json](../contracts/v1/boundaries.json) names ownership and units. Schemas and routes are available directly to application implementers; the execution plan is not a required dependency.

## HTTP

Each website proxies `/api` only to its own API. Credentials use HTTP Basic authorization, held in browser memory and removed on sign-out. Use TLS at the deployment ingress outside loopback development; HTTP Basic does not encrypt credentials. Default website ports bind only to loopback. No central identity service is required.

- `GET /api/health/live`: process liveness and application identity, public.
- `GET /api/health/ready`: database/broker checks plus current controller/worker or projection heartbeat. Returns 503 on missing dependencies, stale heartbeats, failed or stalled runs.
- `GET /api/status`: authenticated application, run, providers, sample effects, jobs and heartbeats.
- `POST /api/jobs`, with `Idempotency-Key`: body `{"due_at":10,"quantity":2}`. An employee/autonomous sample command is valid only at least one configured quantum beyond the maximum of granted/requested time. Quantity is an integer from 1 to 10000. A key replay returns its existing job even after time advances or work is deferred; a changed original body returns 409. Keys are scoped to the current run.
- `POST /api/control/hold`, `/resume`, `/speed`, `/finalize`, `/reset`: JSON body, using `{"speed":5}` or `{"confirm_run_id":"<current-run-uuid>"}` as appropriate. Reset confirmation is checked under the current-run lock. Twin returns 403 for all business mutations.
- `GET /api/sources`: twin read-model source statuses, observation timestamps and per-source snapshots. An unconfigured twin returns an empty list.

Unauthorized requests return 401, validation failures 422, conflicting commands 409. The bootstrap frontend polls its own API; no browser talks directly to databases, RabbitMQ or HELICS.

## Boundary exchange

`sample.completed.v1` represents only the sample count, not an inventory receipt, production completion, shipment or delivery. Domain implementations add new versioned types and payload validators rather than pretending this count models departmental workflows.

The envelope contains event/schema/type, federation/run/epoch, correlation/causation/aggregate IDs, aggregate version, source/destination, boundary, effective simulation time, wall timestamp, quantity unit and payload. UUID event IDs remain stable across retries. Duplicate IDs have one business effect. Old runs/epochs are fenced, unknown routing/owners are rejected, and a late event cannot rewrite already-granted history. This sample creates one aggregate per operation; richer aggregate sequencing and prerequisite deferral belong with domain-specific contracts.

- Time: seconds since run start; minimum handoff quantum 1 second, positive and configurable. Wall-time retries are independent of simulation speed.
- Count: integer `item`; external power: typed HELICS `double` in `kW`.
- Ownership: manufacturing owns batches, storage owns inventory/reservations/receipts, logistics owns journeys, shipping owns orders/shipments. External power owns available-power conditions.
- `BOUNDARY_PROVIDERS` explicitly selects one string, `synthetic` or `helics`, for every declared boundary. Standalone uses synthetic providers; connected mode permits explicitly synthetic open boundaries alongside selected HELICS peers. Duplicate provider lists, missing boundaries or unsupported providers fail startup. No peer failure changes the configured provider.
- RabbitMQ carries internal job IDs only. Connected boundary sample events are sent only through HELICS. A received boundary sample produces one local effect and is not echoed, avoiding a feedback loop.

HELICS is a combination-federate adapter with message endpoints and typed publications/subscriptions, using pinned Python/native package 3.6.1. Native handles belong to the controller process. Endpoints are named `<simulator>/events`; publications `<simulator>/completed_items` and `external-power/available_power_kw`. Sample messages are sent at the current grant; the configured positive period/timeDelta makes the receiver eligible at the next quantum, matching payload effective time. Future `SendToAt` schedules the send itself and would add an additional quantum in this configuration; the native smoke test pins that distinction.

`HELICS_PEERS` maps each connected boundary to its expected source and endpoint. `HELICS_OUTPUTS` maps local sample outputs to a destination, endpoint and receiving boundary. The controller rejects a mismatched transport sender, envelope owner, federation identity or destination. The example maps manufacturing → storage → logistics → shipping → manufacturing; open domain boundaries are explicitly synthetic. Manufacturing samples are deferred to the next grant while external power is unavailable, including newly ingested work.

Reference semantics: [HELICS endpoint example](https://docs.helics.org/en/main/user-guide/examples/fundamental_examples/fundamental_endpoints.html), [Python API](https://python.helics.org/api/capi-py/), [RabbitMQ acknowledgements/confirms](https://www.rabbitmq.com/docs/confirms).

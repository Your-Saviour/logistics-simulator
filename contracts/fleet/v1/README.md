# Fleet transport HTTP v1 (SIMU-75)

Private authenticated HTTP; no native HELICS or departmental SQL credentials.
`Authorization: Bearer <department token>` binds writes to one department.
The independent Twin observer token reads only. All requests/responses are JSON.
Failures: 400 malformed, 401 unauthenticated, 403 wrong identity, 409 scope or
idempotency conflict, 503 dependency unavailable. Retry the exact durable body.

## Configuration

Native departments opt in with `FLEET_MODE=coordinated`, `FLEET_URL`,
`FLEET_TOKEN`, `FLEET_RUN_ID`, `FLEET_EPOCH`. Default `FLEET_MODE=disabled`
preserves existing behavior. Explicit coordinated mode never falls back on failure.
Fleet run maps each department's own run/epoch and common-origin offset; native
requests must use current actual departmental IDs rather than assuming equal IDs.
`FLEET_TIME_OFFSET` defaults to 0 and must equal that department's finite
nonnegative fleet scope offset. Request/proof effective times remain native;
physical fact eligibility compares native granted + offset to fleet effective time.
GET job includes `fleet_scope` with requesting department run_id/epoch/offset
so clients can reject configuration mismatches before acting.

## Admit and inspect

`POST /v1/jobs` takes exactly:

```json
{"version":1,"id":"UUID","run_id":"FLEET UUID","epoch":"FLEET UUID","producer":"storage","source_run_id":"DEPARTMENT UUID","source_epoch":"DEPARTMENT UUID","unit_id":"UUID","origin":"catalog.endpoint","destination":"catalog.endpoint","custody_generation":1,"effective_time":10}
```

Response is the persisted job object (201 new or 200 exact retry). `id`, endpoints,
generation and effective_time are immutable. Persist the request before HTTP;
never recompute its effective_time on retry. One unit and robot per active job.

For a cross-department handoff, derive job ID as UUIDv5(namespace=unit UUID,
name=`fleet:<handoff UUID>:<departure custody_generation>`). Both sides can derive
this from the existing departure token without extending the custody envelope.
Local moves use the command UUID as the handoff component and the unit's current
custody generation; persist that identity before changing unit state.

`GET /v1/jobs/<id>` returns the job with `request`, `state`, `robot_id`, `route`,
`proofs`, `waiting_reason`, plus `events` containing committed physical facts.
Only producer and destination department may read it. Each event is
`{id,job_id,kind,body,acknowledged}`; body repeats request identity with `job_id`,
`robot_id`, `kind`, `route_version:1` and fleet `effective_time`.
Kinds include `pickup_ready`, `arrival`, `completed`. Presence is durable;
lost HTTP responses do not withdraw them.

## Departmental proofs

`POST /v1/jobs/<id>/proofs/departure` and `/proofs/receipt` take exactly:

```json
{"job_id":"UUID","unit_id":"UUID","run_id":"FLEET UUID","epoch":"FLEET UUID","source_run_id":"OWNING DEPARTMENT UUID","source_epoch":"OWNING DEPARTMENT UUID","custody_generation":1,"endpoint":"catalog.endpoint","effective_time":12}
```

Only source owner submits departure; only destination owner submits receipt.
Departure binds origin, receipt destination. Persist proof in the same native
transaction as business departure/receipt, then send through a durable outbox
after commit. Effective time is the actual committed native simulation time.
Fleet waits if a source commits proof ahead of the fleet minimum clock.
Receipt is rejected without a matching committed physical arrival or if it
predates it. Exact proof retries succeed; conflicting facts return 409.

Source departure waits for pickup_ready; receiver receipt waits for arrival and
the existing accepted manifest/departure token. For local movement, reserve
destination capacity and mark nonallocatable transit at departure; only commit
new confirmed placement after arrival. All waits defer durable work beyond the
current grant so native time requests can progress. Never make HTTP inside a
native SQL transaction. A request intent is not proof of movement.

Arrival is an additional physical predicate, not a business receipt. Apply late
arrival at an eligible current/future grant, never rewrite committed history.

## Observation

`GET /v1/snapshot` returns version 1, mode `operational`, current fleet run with
revision/committed/state/reason/source mappings, robots, jobs, reservations and
physical events. It contains no service credentials. Twin must not extrapolate
poses or switch coordinated scopes to historical replay during an outage.
The live job list includes all active jobs and the latest 256 terminal job
headers; completed routes are omitted there. `GET /v1/jobs/<id>` retains the
complete durable route and proofs for historical inspection.

Clock polling uses each department's existing authenticated `/api/projection`;
only its committed watermark authorizes fleet motion. Default five-second source
freshness and explicit matching run/epoch are required.

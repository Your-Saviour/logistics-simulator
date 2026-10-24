# Department-local HELICS adapter protocol v1

This protocol is private to one application deployment. Business APIs, workers,
scheduling, transactions, synthetic providers and local time remain in the
selected department backend. The optional twin never uses the adapter.

Transport: HTTP JSON, `Authorization: Bearer <HELICS_ADAPTER_TOKEN>` on every
request. Bind a private interface; use TLS for non-local transport. One adapter
process, one native combination federate. The backend supplies
`HELICS_ADAPTER_URL` and `HELICS_ADAPTER_TOKEN`. No application DB credentials
are supplied to the adapter.

`POST /v1/commands` request (all top-level fields required):

```json
{"version":"1.0","request_id":"aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa","run_id":"bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb","epoch":"cccccccc-cccc-4ccc-8ccc-cccccccccccc","session_id":"dddddddd-dddd-4ddd-8ddd-dddddddddddd","operation":"initialize","payload":{}}
```

The controller generates and persists session_id before initializing. The
adapter is configured with `FEDERATION_RUN_ID`, `FEDERATION_EPOCH`,
`HELICS_CONFIG`, and a durable `ADAPTER_JOURNAL` SQLite file. Session identity
must match every subsequent request. Request IDs are UUIDs, unique across
operations. Identical retries return the original response; conflicting bodies
return 409. Unknown fields, operations and invalid payloads return 422. An old
run/epoch/session returns 409. Transport/internal failure returns 503; retry
the same request_id rather than inventing a new publication.

Success is HTTP 200 with `{"version":"1.0","request_id":"...","result":{...}}`.
Errors are `{"detail":"..."}`. All times are finite, nonnegative simulation
seconds; values declare units. Event bodies follow `contracts/v1`.

| Operation | Payload | Result |
| --- | --- | --- |
| initialize | `{}` | `{state: "initializing"}`; starts native async initialization once |
| poll | `{}` | `{state, granted, requested, pending, messages, values}`; polls initialization/time; messages are `{source,envelope}` retained until receive_ack; values map typed publication targets to numbers (kW inputs) |
| receive_ack | `{event_ids: [UUID, ...]}` | `{acknowledged: [UUID, ...]}`; send only after backend inbox transaction commit |
| request_time | `{target: seconds, committed: seconds, pending_work: 0, pending_outputs: 0}` | `{requested: seconds}`; only executing, no pending native request or unacknowledged messages; committed must equal last grant, target must exceed it |
| publish | `{endpoint: "peer/events", envelope: business-envelope}` | `{published: event UUID}`; send once per request ID, stable event identity on retries; only executing outside pending time requests, positive future effective_time |
| publish_value | `{value: finite number, unit: "item"}` | `{published: true}`; publish completed sample quantity |
| checkpoint | `{}` | `{state, granted, requested, pending, recoverable: false, session_id}`; metadata only, never a native-state restore promise |
| finalize | `{}` | `{state: "finalized"}`; backend settles current work/outputs first |

`GET /v1/health` returns `{version,state,session_id}` without advancing native
time. Liveness does not authorize job execution. Poll is a fresh operation
with a fresh request ID each time; retrying a lost poll returns its snapshot.

The backend must commit the received grant, then persist/ACK inputs, execute
only eligible work, settle its durable outbox and committed watermark, and
only then send request_time with zero outstanding work/outputs. These counts
are an authenticated backend assertion, not a substitute for its SQL ledger.
The adapter independently blocks advances with unacknowledged native inputs.
For manufacturing, persist unavailable-power deferral before granting eligible
work. Local hold stops new requests; polling and output settlement continue.

Journal an intent before native mutations. A crash between send and journal
completion is ambiguous and stalls the epoch; do not resend automatically
into a newly created native federation. Restart of an adapter with a prior
native session is stalled, even if SQL/backend state survives. A fresh backend
session cannot take over the same live epoch. Recovery requires federation
owner coordination and new run/epoch configuration; retain old journal/data
for diagnosis. Same-process lost HTTP replies are safely replayable. Receiver
inbox deduplication remains required because HELICS and SQL are not atomic.

# Department projection HTTP v1

Each department exposes authenticated `GET /api/projection` to identities with
`status:read`. Missing/invalid credentials receive 401; valid identities without
that scope receive 403. The endpoint does not require broker, adapter, controller
or peer availability. A database failure returns the existing framework's safe
503 response. It performs no business writes, seeding, time advancement or
provider calls.

The response conforms to `twin-projection.schema.json`. `source` is the owning
department. `run` contains that department's persisted current run, including
`id`, `epoch`, `granted`, `requested`, `committed`, `state`, `speed`, `anchor` and
`scenario`. The additive top-level `effects` preserves the legacy `/api/status`
meaning: sum of committed sample `effects.quantity` in the active run (not a
count of warehouse movements, batches, journeys or orders). Run and domain reads share one SQL transaction and the run-row lock
used by all domain writers. This consistency applies to one source, not the
federation. Run/epoch changes fence old histories.

Every successful response replaces the entire source snapshot and includes the
complete durable domain history for its active run. No history or snapshot list
is silently truncated. There is no `after` query or pagination in v1. Consumers
store source, run and epoch with the opaque `cursor`, deduplicate events by their
stable string `id`, and persist the replacement snapshot, events and cursor in
one transaction. An unchanged cursor means unchanged response content. A changed
cursor may reflect clock or publication metadata alone; it is not a new business
transition and has no ordering semantics. A restart can always fetch the full
response again. History size grows with a run; explicit pagination would require
a new contract with a transactionally stable snapshot/history boundary.

| Source | Snapshot fields | Durable event records and IDs |
| --- | --- | --- |
| storage | `run_id`, `epoch`, `inventory`, `locations`, `receipts`, `reservations`, `transfers`, `movements`, `commands` | Warehouse movements: `storage:movement:<uuid>` |
| manufacturing | `config`, `orders`, `materials`, `commands`, `history`, `events`, `movements` | Production history: `manufacturing:history:<sequence>`; material movements: `manufacturing:movement:<sequence>`; completed batch facts: `manufacturing:fact:<uuid>` |
| logistics | `run_id`, `epoch`, `configuration`, `vehicles`, `transfers`, `commands`, `movements` | Transport movements: `logistics:movement:<uuid>` |
| shipping | `run_id`, `epoch`, `orders` (including lines, shipment, history and intents), `shipments`, `commands` | Shipping history: `shipping:history:<sequence>` |

Events preserve original fields and add `kind` (`movement`, `history` or `fact`)
when the record has no original `kind`. Manufacturing material movements retain
their original business `kind` (for example, supply, consumption or output); the
ID prefix identifies their record category.
`simulation_time` is the original persisted simulation time; batch facts expose
the envelope's simulation time. `correlation_id` is retained directly or joined
from the immutable owning order/transfer or original inbound job envelope when
available. Production material
supply/history without an owning order may have no correlation; none is invented.
The original shipping `sequence` remains present. Mutable batch publication
`sent_at` is included only in the replacement snapshot, never in a durable event.
History, movements and facts represent distinct original records; consumers must
not count all three as separate completed batches or infer extra transitions.

Commands and their pending/rejected outcomes remain visible in each snapshot;
they are not fabricated movement events. An empty history does not confirm a
delivery or stock receipt. On a fresh run that has not initialized its domain,
projection reads expose only durable rows (possibly empty arrays), without
creating default warehouse stock, materials or vehicles. Configuration describes
the run's configured/default model, not evidence that equipment or inventory
has been initialized. Source health/staleness is the consumer's observation.

## Handling extension version 1

The additive `snapshot.handling` object has `version: 1`, `catalog_version: 1`
and complete `units`, `movements`, `handoffs` and `lineage` arrays. `quarantine`
retains rejected custody evidence when provided. The JSON schema embeds the
shared unit, movement, handoff and lineage shapes from `contracts/handling/v1`.
Existing snapshot fields remain available. Native planning/context fields such
as `legacy_stock`, `input_allocations`, `unit_context` and `plans` remain owned
by their department and may coexist with this extension.

Each source reports its own retained unit records, including consumed and
historically dispatched units. Unit IDs, barcodes, scope, category and contents
are immutable. Per-unit sequences and custody generations never regress.
Movements reference retained units and retain the latest recorded sequence;
consumption is a terminal event at its original input endpoint, not travel to
an invented position. Manufacturing owns recipe-conserving input/output lineage.

Native movement events use `<source>:unit-movement:<movement UUID>` IDs.
Manufacturing lineage events use `manufacturing:lineage:<lineage UUID>` IDs.
These remain distinct from legacy quantity/history events. A client must not
count both records as separate physical movements.

Within an active scope, a source cannot omit an observed unit, movement,
closed handoff, lineage or quarantine record on reconnect. Movement, lineage
and quarantine identities retain their original bodies. Handoff phases cannot
regress: offer/acceptance freeze the complete reserved manifest; departure
advances its version, sequence and custody generation exactly once; receipt
and acknowledgement retain that same transit manifest and departure proof.
Twin validates these invariants before atomically replacing snapshot/events/cursor.
Legacy responses without `handling` remain readable; after observing the
extension it cannot disappear within the same run/epoch.

Unknown endpoint IDs remain recorded strings without guessed coordinates.
Known endpoints retain ownership/category/capacity validation. A missing catalog
mapping is distinct from an empty warehouse. Quarantine uses the observing
source run/epoch while retaining the original rejected envelope's claimed scope;
it establishes neither receipt nor allocatable stock.

## Infrastructure and control retries

The additive `health` object exposes persisted heartbeats (`role`, `seen_at`,
`healthy`), with the existing 15-second freshness threshold. Heartbeat `detail`
is intentionally excluded. `pending_jobs` counts this run's jobs in `pending`
or `queued`; `dead_letters` counts its durable `dead` jobs. These are SQL ledger
counts, not claims about the broker's physical queue/DLQ depth. `broker` and
`ready` are `null` because the read-only projection does not probe the broker or
claim overall readiness from SQL alone. All health reads share the projection
transaction; health changes can change its content cursor without business events.

HTTP `POST /api/control/hold` and `/resume` support `Idempotency-Key` (1..128
characters). A durable receipt, keyed by current run, authenticated actor and
key, atomically stores the action, original JSON body and complete original
response with the control mutation. Replaying an identical request returns that
response without applying the control again—even after an intervening opposite
control. Reusing a key for a different hold/resume action or JSON body returns
409. Optional run/epoch preconditions are checked before receipt lookup and
remain mandatory for clients that require fencing across resets. JSON object
property ordering does not change request identity. Receipts require additive
native migrations and survive API restarts. Unkeyed controls retain their normal
behavior; reset, speed and finalization semantics are unchanged.

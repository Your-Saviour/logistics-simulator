# Handling-unit upgrade (SIMU-64)

This is an additive upgrade under development. It performs no live cutover.
Do not run old quantity-only writers concurrently with whole-unit writers.
Retain database volumes and take a verified backup before applying new migrations.

## Storage

Migration `009_handling_units.sql` adds the unit ledger, barcode constraints,
single-slot placement index, immutable allocation membership and sequenced
physical movement records. Earlier migration files remain unchanged. It does
not turn existing aggregate stock into invented barcodes or shelf placements.

Drain expected receipts, live reservations and in-transit transfers before
conversion. Existing unconverted quantities appear in
`GET /api/warehouse` → `handling.legacy_stock`; reservation of such quantities
fails with a conversion reason. Existing active work without unit identities
requires operator reconciliation, never a guessed allocation or lineage.

An operator can queue `action: "convert"` through the existing authenticated
`POST /api/warehouse/commands` with an `Idempotency-Key`. Supply current `run_id`,
`epoch`, a valid future `due_at`, `sku`, logical `location`, exact total `quantity`,
`correlation_id` and `units`, for example:

```json
{
  "units": [
    {"id": "a1111111-1111-4111-8111-111111111111", "quantity": 4, "position": "storage.raw.r01.b01.l01"},
    {"id": "a2222222-2222-4222-8222-222222222222", "quantity": 6, "position": "storage.raw.r01.b02.l01"}
  ]
}
```

The omitted command fields above depend on the live run and stock; read them
before submitting. The manifest must exactly conserve that location/SKU's
untouched unreserved aggregate stock. IDs must be fresh; positions must belong
to Storage, accept the SKU category, and have capacity. Conversion commits all
units or none, retains its command receipt/provenance and emits no fictional
historical physical movements. Identical command retries retain their identity;
altered manifests under the same key conflict.

New `expect` commands require an explicit `units` manifest containing unit UUIDs
and whole quantities summing exactly to the receipt quantity. `receive` assigns
exact available inbound or finished-receipt dock positions. `putaway` and
`retrieve` take `unit_id` and catalog `destination`; they use the same run/epoch,
grant barrier, worker and idempotency path as existing commands. No partial picks
or implicit unit creation from legacy quantities are supported.

Rollback to old writers is supported only before whole-unit writes are enabled,
or by restoring a verified pre-upgrade backup and reconciling operations. Old
binaries cannot preserve the new unit invariants after those writes occur.

## Manufacturing

Migration `009_handling_units.sql` is appended to the native migration index.
It adds barcoded raw/finished units, single-position capacity constraints,
once-only input consumption membership, completed batch lineage and durable
physical receipt/production movements. Applied migrations 001–008 are unchanged.

`supply` requires an explicit `units` manifest of fresh UUIDs and quantities
summing to the command quantity. The website plans one whole unit per receipt.
The fixed facility maps the first four configured production lines, in persisted
configuration order, to `manufacturing.cell01` through `cell04`. Raw receipts use
input positions; good output uses output positions. A batch waits when its exact
recipe cannot be made from whole units at its cell, or when output positions are
full. It never splits inputs. Start atomically consumes whole inputs and records
batch membership; completion creates a fresh output unit and durable lineage.
All-scrap batches retain their input lineage and create no zero-quantity unit.

Unconverted raw quantities appear in `handling.legacy_stock`. After draining
active work orders and pending boundary work, an operator can queue `convert`
through `POST /api/production/commands` with current run/epoch, future `due_at`,
`sku`, exact legacy `quantity`, and `units` containing UUID, quantity and exact
`manufacturing.cellNN.inputNN` position. Conversion requires untouched legacy
stock and commits atomically without changing aggregate quantity or fabricating
physical history. Preserve its idempotency key when retrying. Existing running
batches without whole-input provenance require operator reconciliation; the new
worker will not manufacture invented output lineage for them.

Legacy quantity-only Storage facts remain visible observations. They do not
authorize material placement or create new barcodes in Manufacturing. The
cross-database token/acknowledgement protocol must be deployed before enabling
connected whole-unit operations. Independent reset never imports old-scope stock.

## Logistics

Migration `008_handling_units.sql` adds unit-linked transport manifests, unique
active allocations, exact truck/staging placement and sequenced physical history.
It does not backfill identities for old quantity-only transfers. Drain those
transfers before upgrading; the worker rejects attempts to move unreconciled
legacy loads rather than inventing barcodes.

Initial stock fixtures use `intake` through the normal transport command endpoint
with run/epoch, future due time, SKU, raw/finished `category`, exact `quantity`,
correlation ID and explicit `units` (UUID and quantity). Optional `location` is
the configured logical route origin; it is separate from the recorded physical
endpoint. The service assigns compatible finite staging positions. Real custody
imports must use the handoff protocol, preserving the existing barcode.

`request` requires `unit_ids`. Selected units must be available in this run/epoch,
at the logical origin, with exactly the requested SKU/quantity. Loading validates
both vehicle quantity capacity and its eight physical slots, committing every
unit or none. Departure clears confirmed placement and preserves origin/intended
destination. Unload and receipt remain separate. An off-site trip retains unknown
world position until confirmation; it does not acquire an invented scene coordinate.

Quantity-only legacy Storage transfer facts are retained observations and cannot
create transport stock. Source projection and the website receive unit data plus
`unit_context` (logical origin/current transfer); logical names are never scene
coordinates. Cross-database token/acknowledgement integration remains required
before connected whole-unit cutover.

## Shipping local units and custody protocol

Shipping migrations `010`–`014` add immutable single-SKU unit contents, unique
barcodes and occupied positions, active line allocations, explicit synthetic
supply plans, sequenced movements and durable incoming/outgoing handoffs. Old
quantity-only orders remain historical records; they are not backfilled with
invented barcodes or positions. Drain active workflows before upgrading.

`intake` accepts a complete `sku`, `quantity` and explicit `units` manifest of
UUID/quantity entries. It creates stock only at compatible, free Shipping
positions; rejection rolls back the complete manifest. Fulfilment first searches
for an exact subset of available whole units. Synthetic replenishment creates
new, explicitly planned units; an existing larger unit remains intact. Packing
requires owned, reserved units with confirmed physical positions.

The native custody receiver persists slot acceptance without placing stock.
Only the matching source departure token can import the reserved barcode,
contents, generation and continuing movement sequence. The native source clears
placement before publishing departure and acknowledges only its exact departure
proof. Conflicting identities, endpoints, contents and receipts reject atomically.
Temporary destination capacity rejection marks the original command retryable;
the identical peer offer can requeue that same command after capacity frees.
Pending source offers fence release and alternative synthetic departure.
Pending stages retry at five-second wall-clock intervals using the same immutable
event envelope; a fresh private adapter operation performs each actual retry.
Duplicate receipt messages can recover a lost acknowledgement without repeating
retirement or movement history. Protocol evidence received after its original
simulation time runs at the current grant and cannot rewind history.

These PHP protocol components and controlled peer fixtures are not evidence of
a connected four-department lifecycle. Automatic vehicle-assignment offers,
whole-unit peer request integration, the other native protocol participants and
connected failure acceptance remain required before any whole-unit cutover.
Known returning barcodes currently require explicit reconciliation rather than
automatic re-import.

## Twin instructions pending

Twin upgrade instructions will be added with its native implementation. The shared protocol is in
[`contracts/handling/v1/README.md`](../contracts/handling/v1/README.md).

## Logistics custody receiver

Migrations `009` and `010` add a separate durable custody ledger and incoming
control-event journal. Accepted offers reserve their exact compatible endpoint
without creating stock. Matching departure evidence imports the original unit
with the next movement sequence; an acknowledgement closes the receiver record.
The complete native snapshot retains accepted, received and acknowledged states.

Temporary slot pressure leaves the offer unaccepted and marks its command
retryable. Identical peer redelivery can requeue that same job once capacity is
free. Lost acceptance/receipt replies reuse the full original envelope and a new
private adapter operation, with at most one unsent retry per event. The adapter
relays only to an explicitly matching recipient/boundary route. Counter bounds
reserve PostgreSQL integer headroom for source departure and destination receipt;
exhausted local counters reject before mutation rather than failing SQL arithmetic.

These receiver components use existing configured peer endpoints. Logistics
source handoffs, provisional manifest requests and assigned-vehicle coupling,
explicit multi-peer routing and connected native acceptance remain required.

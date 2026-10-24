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

## Remaining applications

Logistics, Shipping and Twin upgrade instructions will be added
with their native implementations. The shared protocol is in
[`contracts/handling/v1/README.md`](../contracts/handling/v1/README.md).

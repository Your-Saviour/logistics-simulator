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

## Remaining applications

Manufacturing, Logistics, Shipping and Twin upgrade instructions will be added
with their native implementations. The shared protocol is in
[`contracts/handling/v1/README.md`](../contracts/handling/v1/README.md).

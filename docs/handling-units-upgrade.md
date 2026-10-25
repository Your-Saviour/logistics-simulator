# Handling units: upgrade and recovery

This change does not perform a live cutover. Each department retains its own
API, worker, controller and SQL transactions. The private adapter alone owns
native HELICS; Twin remains an optional observer.

## Additive migrations

Apply migrations through the corresponding application's normal startup. Retain
existing migration checksums and database volumes. The handling additions are:

| Owner | Migration directory | Handling additions |
| --- | --- | --- |
| Storage | `apps/storage/backend/migrations` | 009–013 |
| Manufacturing | `apps/manufacturing/backend/src/main/resources/migrations` | 009–014 |
| Logistics | `apps/logistics/backend/migrations` | 008–015 |
| Shipping | `apps/shipping/migrations` | 010–016 |
| Twin | `migrations` | 006, following the existing 004–005 read model |

The migrations add ledgers, retained handoffs, recovery/quarantine records and
whole-order goods reservations. They do not reconstruct barcodes or positions
from old aggregate quantities. Twin's immutable manifest registry retains unit
identity across source removal, restart and epoch retirement.

## Before enabling whole-unit operations

1. Stop admitting new operational commands. Let current receipts, reservations,
   manufacturing batches, shipments and custody handoffs finish or resolve them
   with their owning department.
2. Coordinate controller shutdown/holds after draining. Preserve adapter
   publications, command receipts and closed handoff evidence. Do not run old
   and new controllers concurrently against the same run.
3. Take and verify backups of each owning database and its migration ledger.
4. Apply the matching native application and adapter versions. Check that peers
   agree on run/epoch, catalog version and departure-token protocol.
5. Inspect aggregate stock for legacy/unplaced quantities. Submit an explicit
   conversion manifest before allocating that stock as whole units.

## Warehouse conversion

Submit an explicit conversion to the authenticated
`POST /api/warehouse/commands` endpoint with `action: "convert"`. This template
requires real operator-selected IDs, the current scope and a valid scheduled
`due_at`; its placeholders are not runnable values:

```json
{
  "run_id": "<current run UUID>",
  "epoch": "<current epoch UUID>",
  "due_at": 0,
  "action": "convert",
  "sku": "COMPONENT",
  "location": "RAW-A",
  "quantity": 2,
  "correlation_id": "<new correlation UUID>",
  "units": [
    {
      "id": "<new unit UUID>",
      "quantity": 2,
      "position": "storage.raw.r01.b01.l01"
    }
  ]
}
```

Set `due_at` using the current run's scheduling rules. Preserve the
`Idempotency-Key` and the entire request when retrying. An accepted HTTP command
is queued work: inspect its completed outcome before relying on the conversion.

The manifest must exactly conserve the SKU quantity at the logical location.
Units require fresh identities and compatible, free catalog endpoints. Active
receipts, reservations and transfers must be drained; aggregate reserved stock
must be zero. A conflict leaves aggregate stock and unit records unchanged.
Conversion records provenance and creates no invented past movement. Barcodes
are derived from UUIDs; quantities on an existing unit are immutable.

Existing manufacturing/material or shipment work without whole-unit evidence
must be drained or reconciled by its owner. Do not fabricate a destination
receipt or edit ledgers directly to make a legacy workflow appear converted.

## Interrupted custody and projection recovery

Restart the owning roles using the application's normal procedure. Durable
outboxes retry the same handoff evidence; timeout alone cannot restore source
stock or confirm destination receipt. An accepted destination reserves capacity
but is not stock. Retain receipt IDs, departure tokens and closed handoffs until
retries converge. Inspect quarantine before resolving inconsistent scope,
identity, contents or proof; do not silently rewrite a rejected manifest.

A disconnected Twin retains last recorded observations. It does not authorize
business work. Conflicted or unobserved custody has no confirmed 3D placement;
unknown endpoint strings remain unmapped. Reconnecting an observer cannot
advance a business transaction.

Old writers cannot preserve the new invariants after whole-unit writes begin.
A rollback requires a verified pre-upgrade backup and coordinated operational
reconciliation. Do not delete applied migrations or reuse immutable unit IDs in
a new epoch.

## Disposable local checks

Build and test only through the guarded Make targets. Unit and stack checks use
fresh Compose projects and remove their disposable volumes during teardown.
Keep the default 20 GiB reserve. Persistent application volumes are outside
those test projects; cleanup must never use blanket volume pruning.

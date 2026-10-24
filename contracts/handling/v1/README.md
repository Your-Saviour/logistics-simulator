# Whole handling units v1 (SIMU-65)

Departments remain the only writers of their business records. Twin validates
and observes these contracts; neither its availability nor its animation can
confirm receipt, allocate stock or advance a business workflow.

## Identity, contents and placement

`unit.schema.json` defines a stable UUID and `HU-` plus its uppercase UUID hex
barcode. Keep identity and contents immutable across departments. Contents have
one positive integer quantity per SKU. Manufacturing creates new output IDs and
retains input/output batch lineage; consumed inputs are terminal, unplaced and
excluded from available stock. Do not serialize individual items.

Available/reserved units have one confirmed compatible catalog position owned by
their department. Transit units have **no confirmed position** and retain origin,
intended destination and handoff identity. Historical source records are retained
but must never be counted as allocatable stock after departure. Legacy quantities
are explicitly unplaced and unavailable to whole-unit operations until conversion.

`facility.json` is the fixed version-1 catalog in metres, Y up. It includes 512
shelf slots, exact cell input/output positions, staging docks and truck slots.
Each endpoint holds one whole unit; category compatibility and owner must match.
Logical aggregate groups (RAW-A, FINISHED-A, DISPATCH) are not physical positions.
Access coordinates connect shelf aisles to the fixed lane network; shelf heights
are recorded separately from floor access points. Unknown IDs remain unmapped;
consumers must not substitute a guessed physical location.

The JSON schemas enforce record shape. `simulator.handling_contracts` also
validates cross-field identity, placement ownership, contents uniqueness,
single-slot occupancy, exact allocation and handoff scope/token consistency.
Native backends must enforce the same rules in their transactions and database
constraints; a projection validator is not an allocation lock.

## Whole-unit allocation and recipes

Reserve an exact subset of available whole units under the owning run lock.
Every SKU total must equal the request; no additional SKU may be introduced by
selecting a mixed unit. Never split, repack, clamp quantity or overfulfil.
The reference allocator uses stable unit-ID order and a bounded subset search;
it reports incompatibility or the search bound explicitly. Native allocators
must report an actionable wait/rejection rather than changing the request.
Explicit unit selection is permitted if it meets identical constraints.

New receipts require explicit manifests. Synthetic providers produce deterministic,
recipe-compatible manifests with exact quantities; they cannot infer partial
units by clamping demand to aggregate availability. Production reserves inputs
at cell positions and atomically consumes them once, creates newly barcoded
outputs once, and persists lineage and configured scrap accounting. Unsupported
whole-unit/recipe combinations must remain explicit.

## Recoverable handoff across separate databases

The internal boundary transport must authenticate the sender. A departure token
is durable evidence from the source transaction, not a browser-generated claim.
No distributed transaction or timeout-based receipt is assumed.

1. **Offer:** source reserves the unit at its confirmed origin and persists the
   immutable manifest plus offer in the existing transactional outbox.
2. **Accept:** destination reserves compatible finite capacity and saves the
   offer identity/content hash durably. Acceptance is not physical placement.
3. **Depart:** after acceptance, source atomically clears confirmed placement,
   enters non-allocatable transit and writes the departure token/outbox message.
   Token binds handoff/unit/run/epoch, incremented custody generation, latest
   movement sequence and unit version. Source cannot release/reallocate it.
4. **Receive:** destination requires the exact accepted manifest and matching
   departure token. It atomically claims custody, occupies its reserved endpoint,
   increments version/sequence, records receipt movement and emits acknowledgement.
5. **Acknowledge:** source closes only that handoff/custody generation. Its old
   row is historical, never restored stock. Late acknowledgements cannot retire
   a later custody generation after the unit has returned.

Use unique handoff IDs and immutable receipts to replay offers, acceptance,
departure, receipt and acknowledgements after restart. Identical retries return
the original outcome; changed payloads under an existing identity conflict.
Capacity reservations cannot expire after a committed departure. Before departure,
cancellation requires a durable bilateral cancellation outcome. After departure,
recovery must complete or explicitly reconcile custody; it cannot roll back by
silently reinstating source stock.

Run/epoch mismatch quarantines a handoff with a visible reason. It does not import
stock into an independently reset run. Operators must reconcile in-flight work
before reset; no automatic cross-run adoption is supported.

| Physical stage | Custody / confirmed endpoint owner |
| --- | --- |
| Inbound truck | Logistics / inbound truck slot |
| Unloaded inbound staging | Storage / inbound dock |
| Raw putaway and retrieval | Storage / raw shelf or raw dispatch dock |
| Manufacturing receipt and processing | Manufacturing / cell input |
| New finished output | Manufacturing / cell output |
| Finished receipt, putaway, retrieval | Storage / finished receipt dock, shelf, outbound dock |
| Shipment staging | Shipping / outbound dock |
| Outbound loaded truck | Logistics / outbound truck slot |

Each ownership boundary in that table uses the handoff protocol. On-site moves
within a department are atomic local transitions. Storage→Manufacturing and
Manufacturing→Storage do not need an invented intermediate Logistics placement.
Robots between the recorded endpoints are visualization estimates only.

## Movement ordering, lineage and projections

`movement.schema.json` records stable movement UUID, barcode/unit ID, run/epoch,
monotonic per-unit sequence, custody generation, exact endpoints, simulation time
and nullable transfer/batch/shipment references. Initial receipt/production may
have a null origin. Reservations have no physical movement. A migration does
not fabricate earlier movement events. Consumers deduplicate by
`(source, run_id, epoch, movement.id)`, reject identity reuse with changed payload,
and order each unit by custody generation and sequence, not HTTP arrival order.

The departure token carries the last unit sequence/version; the receiver appends
the next transition. A generation is advanced at departure; a returned unit must
have a newer generation. Gaps or incompatible scopes remain visible/quarantined,
not guessed. Recipe lineage links immutable input IDs to fresh output IDs and
batch identity; retained terminal inputs remain available for inspection.

Department projections add `handling: {version: 1, catalog_version: 1, units,
movements, handoffs, lineage}` while retaining existing v1 fields. Source run/time
metadata and complete-history/replacement-snapshot semantics continue to apply.
Cursor, snapshot and durable events commit together in Twin. Different source
clocks are not one atomic snapshot. Reconcile cross-source unit custody using
departure/receipt generations; retain conflicts/pending states explicitly.
Unavailable data differs from zero stock. Retired epochs cannot reappear.

## Additive upgrade and recovery

Add the next numbered migration to each native backend. Never change applied SQL
or migration checksums. Back up databases and retain data volumes. Drain existing
reservations, active production, shipments and handoffs **before** enabling the
new whole-unit paths; report non-drained work as requiring operator remediation.

Existing aggregate stock is not proof of barcodes or shelf positions. Conversion
requires an explicit operator-supplied immutable manifest assigning new unit IDs,
contents and valid available endpoints. Under the run lock, validate exact SKU
conservation, no active allocations, uniqueness and capacity; persist a conversion
receipt so an identical retry is harmless and altered retries conflict. Record
conversion provenance, not fictional receipt/movement history. Invalid conversion
must leave both aggregate quantities and unit records unchanged.

Rolling back old application binaries after whole-unit writes is unsupported:
old writers cannot preserve unit invariants. Rollback is allowed before enabling
whole-unit writes, or by restoring a verified pre-upgrade backup with coordinated
operational reconciliation. No automatic deployment or live cutover is included.

## Private adapter custody relay

`handling.offered|accepted|departed|received|acknowledged|quarantined.v1` wraps
one complete handoff as `payload`. Envelope aggregate and causation IDs equal
the handoff ID; aggregate version equals the embedded unit version. The source
sends offers, departures and acknowledgements; the destination sends acceptance
and receipt. The adapter validates scope, immutable evidence and sender/recipient
ownership but performs no inventory operation.

Persist the entire first envelope, including `wall_time`, before publishing it.
A retry retains its event ID and complete body. It uses a new private publication
operation so the adapter actually sends again instead of returning a cached
operation response. Native HELICS sends immediately; its configured positive
quantum governs delivery. Valid custody messages may therefore carry historical
protocol evidence after native time advances. Receivers schedule that evidence
at `max(current grant, original effective_time)` and continue the same durable
handoff, rather than inserting or rewriting earlier movement records. Ordinary
business messages retain their existing positive-quantum and late-input fences.

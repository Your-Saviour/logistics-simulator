# SIMU-64: whole handling units and robotic facility

Source: https://ctfittwo.atlassian.net/browse/SIMU-64 and SIMU-65–74, read 2026-10-25.

Design approved by the user on 2026-10-25. Detailed protocol decisions from the
builder review are recorded in `contracts/handling/v1/README.md`: departure-token
gating, custody generations and sequence continuation, endpoint ownership,
draining legacy workflows before conversion, explicit receipt manifests and
quarantine on mismatched run/epoch. These resolve implementation details without
changing the epic's scope.

## Intent and approved direction

Implement the entire epic: inbound unloading, raw putaway, retrieval, manufacturing, finished putaway, retrieval and outbound loading. Preserve five independent websites, departmental SQL ownership, native HELICS ownership, optional Twin sources and a Twin that cannot gate business progress. Replace the visualization using the existing React/Three.js integration.

The issue records the choice of replacement over extending the existing scene. A visualization-only change cannot satisfy whole-unit conservation; a central inventory service would change departmental ownership. Extend each existing business transaction and its durable boundary messaging, then project those records into the replacement scene.

## Proposed implementation decisions

### Contracts and identity

Add `contracts/handling/v1` with JSON schemas, fixed catalog, fixtures and protocol documentation. A unit has immutable UUID `id`, unique `barcode` (`HU-` plus uppercase UUID hex), immutable nonempty SKU/positive integer quantity contents, `run_id`, `epoch`, lifecycle, owner, version and placement. IDs remain unchanged through custody transfers; finished production outputs receive new IDs. Lineage records reference input and output IDs and the production batch. Quantities never change on an existing unit.

Movement fields: stable `id`, unit ID/barcode, monotonically increasing per-unit `sequence`, origin and destination endpoint IDs, simulation time, run/epoch, action and nullable transfer/batch/shipment correlations. Reservations do not fabricate physical movement. An in-transit unit retains last confirmed origin, intended destination and handoff ID; confirmed position is null. Consumed/dispatched terminal units do not render as live stock.

### Fixed catalog and physical rules

Catalog version 1 defines inbound dock bays and truck slots, raw shelf slots, manufacturing input/output cell positions, finished shelf slots, outbound bays and truck slots. Each endpoint has owner, kind, permitted raw/finished categories, finite unit capacity, coordinates, access-lane waypoint and shelf elevation. Use one unit per shelf slot, cell position and truck slot. Provide enough numbered slots for a 500-unit acceptance scene. Existing logical locations such as `RAW-A` remain grouping names, not exact physical endpoints.

All placements validate endpoint category and capacity in the owning transaction. Serialize allocation using the existing run lock, with database uniqueness constraints on active allocation and occupied single-capacity endpoint as defense in depth. Multi-unit requests require an exact sum of immutable unit contents. Choose deterministic whole-unit subsets ordered by receipt time and ID; reject/wait with an explicit whole-unit incompatibility reason when no exact subset exists. Do not overfulfil.

### Departmental operations and handoff

Extend Warehouse.cs, Production.java, transport business handlers and Shipping Fulfilment using native models and new numbered migrations. Aggregate stock remains a reconciled quantity view of unit lifecycle, never an independently editable source. Receive/putaway/retrieve, production start/complete and loading/unloading write unit transitions and movements atomically with existing command receipts and audits.

The source reserves the unit and persists a handoff offer in its transaction/outbox. Destination accepts the immutable manifest and reserves capacity durably, deduplicating by handoff ID and rejecting identity/content conflicts. Source departure clears confirmed placement and retains pending custody. Destination receipt records placement and an acknowledgement; source retires its local live custody only from the durable acknowledgement. The same physical unit may have retained records in two databases, but only one confirmed custody claim is valid in the protocol. Twin displays unresolved handoffs as pending, never as two placed units. Retry existing durable outbox messages after restart; timeouts alone never restore stock or confirm delivery. Fence every operation by run/epoch and retain closed handoff receipts.

Production reserves exact recipe inputs at cell endpoints, consumes each once and creates correctly quantified fresh outputs once in the completion transaction, linking all inputs/outputs to the batch. Reject unsupported recipe/whole-unit combinations explicitly. Account for configured scrap separately; never invent finished quantity. Coordinate with existing production contracts without adding PLC/FUXA work.

### Upgrade

Never edit applied SQL. Add next numbered migration in each native migration directory. Existing aggregate stock is explicitly legacy/unplaced until an operator-approved conversion manifest assigns whole units and catalog endpoints. Conversion is idempotent, validates conservation/capacity and records conversion provenance, not invented historical moves. Block operations that would mix unconverted aggregate stock into whole-unit allocation with a clear remediation reason. Preserve existing records and volumes. Document rollback compatibility and require upgrade checks before operational use; no automatic live cutover.

### Projection

Add a versioned handling extension to the current complete-snapshot projection. Keep existing fields for compatibility; expose units, catalog version, lineage, handoffs and complete durable movements. Twin validates these fields, persists them with snapshot/cursor/events in its current atomic transaction, rejects mutated event identities and retired epochs, and preserves optional source support. Cross-source custody reconciliation uses handoff identity/state, not arrival order or matching wall-clock times. Unknown catalog IDs remain inspectable as unmapped records and do not acquire guessed coordinates.

### Viewer and motion

Replace Facility3D with a fixed clean stylized facility: restrained department colors, readable labels, open cutaway walls, rack uprights/shelves, production machines, dock bays, trucks and lane markings. Overview camera shows the whole facility; retain orbit/pan/zoom and add reset. Robot design: compact wheeled base with mast/forks for shelving and truck handling. Routes run via catalog access points and connected lanes, with vertical pickup/place segments. Carry the unit as a robot child during travel; suppress its static mesh while replaying that journey.

Maintain per-unit ordered queues deduplicated by source/run/epoch/movement ID. Proposed bounds: at most 64 concurrent journeys, 256 queued movements, and 15 seconds maximum replay delay. Overflow coalesces older journeys to recorded state and visibly counts skipped movements. Completion trails fade over 3 seconds and never represent occupancy. Freeze on held/stale/disconnected sources, clear incompatible epoch queues, and do not let animation completion write business state. Reduced motion uses recorded placement and textual activity without interpolated travel or trails.

Selection is optional and does not hide other activity. Keyboard-accessible unit list and detail show barcode, contents, confirmed position/custodian, pending destination, history and lineage. Distinguish recorded state from visual replay, generated robot IDs/routes/timing, source freshness, missing inventory and backlog. Retain this view on WebGL failure.

## Verification and acceptance budget

Run every build/test inside Docker through scripts/docker_guard.py retaining its default 20 GiB reserve. Use framework-native tests for atomic movement/stock writes, exact allocation, capacity, duplicate commands, competing reservations, handoff retry/restart, stale epochs and recipe/lineage conservation. Extend projection recovery tests and browser checks for source subsets, delayed events, epoch changes, keyboard selection, fallback and reduced motion.

Proposed busy-scene budget: 500 live units and 64 concurrent journeys at 1440×900, Chromium in Docker with recorded host CPU/GPU and WebGL renderer; p95 frame interval ≤33.4 ms over 30 seconds after warmup, no queue beyond the stated bounds and catch-up within 15 seconds after source recovery. Report actual software-renderer limitations rather than claiming hardware performance from unit tests. Capture screenshots/recordings of overview, shelf/truck interactions, concurrent activity, inspection and fallback. Final acceptance also requires stack-unit and stack-check for all applications plus mixed-check, upgrade/conversion evidence and exact local/hosted distinctions.

## Exclusions

No layout editor, item serialization, splitting/repacking, separate barcode scanner subsystem, authoritative robot scheduling/failures, physics optimization, human handling, new PLC/FUXA integration or live cutover.

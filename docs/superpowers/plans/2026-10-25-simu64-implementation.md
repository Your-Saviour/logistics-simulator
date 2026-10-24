# SIMU-64 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Complete SIMU-64 and SIMU-65–74 with departmental whole-unit operations and a replacement robotic facility Twin.

**Architecture:** Extend existing native departmental transactions and durable boundaries. Retain the complete-snapshot Twin projection and React/Three.js viewer stack; visualization never confirms business receipt.

**Tech Stack:** PostgreSQL, ASP.NET/Vue, Spring/Angular, Go/Svelte, Laravel/Livewire, Flask/React/Three.js, guarded Docker and Playwright.

**Spec:** `docs/superpowers/specs/2026-10-25-simu64-handling-units-design.md`

## Global constraints

- Preserve five independent websites, optional sources and departmental/HELICS ownership.
- Build/test only in Docker through scripts/docker_guard.py, default 20 GiB reserve.
- Add numbered migrations; preserve applied checksums and volumes; no live cutover.
- Whole units only; exact quantities, exact endpoints, explicit pending custody.
- Budget: 500 units, 64 active journeys, 256 queued, 15-second catch-up, 3-second trails, p95 frame interval ≤33.4 ms at 1440×900 over 30 seconds.

## Review focus

- Same barcode received through conflicting handoffs must reject without double placement.
- Exact quantity availability does not guarantee a compatible whole-unit subset.
- Legacy aggregate stock must not silently become fictitious located units.
- Late source snapshots and independent clocks must not resurrect retired custody.
- Reduced motion, unavailable sources and renderer failure must preserve useful recorded-state access.

### Task 1: Shared contract and upgrade protocol (SIMU-65)

**Files:** Create `contracts/handling/v1/{unit.schema.json,movement.schema.json,handoff.schema.json,facility.json,fixtures.json,README.md}` and `tests/test_handling_contracts.py`.

**Interfaces:** Immutable unit manifest; sequenced movement; versioned catalog endpoints; offer/accept/depart/receive/acknowledge handoff protocol defined by the spec.

- [ ] Write fixtures/tests asserting identity uniqueness, positive contents, single placement, exact whole-unit allocation, compatible finite endpoints, pending custody and stale-epoch rejection.
- [ ] Run contract checks in the existing guarded Python test image and confirm missing contracts fail.
- [ ] Implement schemas/catalog and document ordering, ownership/recovery, additive projection compatibility and explicit legacy conversion.
- [ ] Run contract suite; require all valid/invalid fixtures to produce expected outcomes.

### Task 2: Storage unit ledger (SIMU-66)

**Files:** Modify `apps/storage/backend/{Warehouse.cs,WarehouseProviders.cs,Program.cs}`; add next numbered storage migration and native harness regressions.

**Interfaces:** Consumes Task 1 manifests/endpoints. Produces unit-aware receipts/reservations/retrieval and immutable movements in warehouse snapshot and boundary facts.

- [ ] Add regressions for duplicate receipt, competing allocation/placement, partial-unit requests, full slots, stale epochs and rejected-write rollback.
- [ ] Verify regressions fail with `make stack-unit APP=storage` through the guard.
- [ ] Implement unit ledger, exact subset allocation and stock reconciliation in existing command transactions; add explicit conversion manifest workflow for legacy stock.
- [ ] Verify native suite and `make stack-check APP=storage`, including migration/conversion conservation and restart recovery.

### Task 3: Production and lineage (SIMU-67)

**Files:** Modify `apps/manufacturing/backend/src/main/java/simu/manufacturing/{Production.java,Projection.java,Api.java}`; add next native migration and JUnit tests.

**Interfaces:** Consumes unit-aware storage handoffs. Produces consumed input IDs, fresh output manifests, exact cell positions and batch lineage.

- [ ] Add failing tests for exact recipe allocation, duplicate completion, restart mid-batch, stale epoch, invalid recipe and scrap accounting.
- [ ] Implement cell receipt/reservation, once-only consumption/output and lineage atomically with existing jobs/outbox.
- [ ] Verify `make stack-unit APP=manufacturing` and `make stack-check APP=manufacturing`; assert aggregate/unit conservation.

### Task 4: Transport/shipping handoffs (SIMU-68)

**Files:** Modify `apps/logistics/backend/{transport.go,transport_store.go,transport_provider.go,projection.go}` and `apps/shipping/src/{Fulfilment.php,ShippingBoundary.php,ShippingRules.php}`; add next native migrations and Go/PHP regressions.

**Interfaces:** Consumes shared handoff and unit manifests. Produces durable vehicle-slot/dock placement and recoverable custody transitions.

- [ ] Add failing integration cases for duplicate/conflicting offers, concurrent shipment allocation, full truck/dock slots, outage after departure, late acknowledgements and restart.
- [ ] Implement handoff receipts/outbox recovery, whole-unit shipping allocation and exact truck/dock moves with native transaction constraints.
- [ ] Verify stack-unit and stack-check for logistics/shipping; departure alone must leave destination unconfirmed.

### Task 5: Departmental inspection (SIMU-69)

**Files:** Extend each business application's existing operational frontend, API read endpoints and browser tests.

**Interfaces:** Unit barcode lookup returns immutable contents, exact placement/custody, history, references and lineage from its owning backend.

- [ ] Add browser regressions for lookup, role restrictions, loading/error states, pending handoffs, incompatible requests and legacy conversion requirements.
- [ ] Implement read/detail UI using each existing framework; preserve idempotent command handling.
- [ ] Verify frontend/native browser checks and capture screenshots for all four websites.

### Task 6: Twin projection extension (SIMU-70)

**Files:** Extend departmental projection producers, `contracts/http/v1/twin-projection.*`, `apps/twin/backend/projection.py`, and `apps/twin/tests/test_projection.py`; add migration only if storage shape requires it.

**Interfaces:** Add versioned `handling` extension with units, movements, lineage, handoffs and catalog version. Retain legacy projection fields and complete history semantics.

- [ ] Add failing tests for duplicate/changed events, conflicting barcode/custody, incomplete history, independently timed sources, stale/retired epochs and source subsets.
- [ ] Implement extension validation and atomic snapshot/event/cursor persistence; reconcile custody by durable handoff identity, retaining unresolved conflicts visibly.
- [ ] Verify Twin unit/recovery checks and all producer contract tests. Unknown endpoints remain unmapped.

### Task 7: Fixed facility scene (SIMU-71)

**Files:** Replace `apps/twin/web/src/Facility3D.tsx`; introduce focused catalog/scene components and extend `facility3d.css` plus frontend tests.

**Interfaces:** Consumes fixed catalog and projected unit records. Produces full-facility camera, endpoint meshes, robot lanes and selectable recorded placements.

- [ ] Test every catalog endpoint mapping, shelf elevation and unknown-ID fallback.
- [ ] Build stylized docks/trucks, raw/finished racks, production cells, lane network and overview/reset controls using restrained colors and readable labels.
- [ ] Verify frontend build/tests and capture normal/busy scene screenshots for visual review.

### Task 8: Concurrent journey reconstruction (SIMU-72)

**Files:** Create `apps/twin/web/src/journeys.ts` and journey renderer/tests; extend scene integration.

**Interfaces:** Consumes ordered durable movement IDs/endpoints plus source state; produces visual-only robot/unit poses, queue counters and fading trails.

- [ ] Add tests for simultaneous journeys, per-unit ordering, duplicate events, vertical pickup/placement, truck interaction, epoch reset, pause and bounded catch-up.
- [ ] Implement lane routing, carried-unit attachment, static mesh suppression, 64 active/256 queued limits, 15-second coalescing and 3-second trails.
- [ ] Verify frontend tests and browser recordings; assert no business mutations from journey completion.

### Task 9: Truthful inspection/accessibility (SIMU-73)

**Files:** Extend `apps/twin/web/src/main.tsx`, scene/detail components, styling and Twin browser acceptance.

**Interfaces:** Consumes recorded units/history/lineage and separate journey state. Produces keyboard-accessible list/details and source/backlog status independent of WebGL.

- [ ] Add checks for selection/clear, unrelated concurrent activity, missing/stale/held sources, reduced motion and forced WebGL failure.
- [ ] Implement recorded/replay distinction, visual-estimate labels, stale last-known state and fallback list. Reduced motion disables interpolation/trails.
- [ ] Verify browser checks and screenshots with source subsets and keyboard-only navigation.

### Task 10: Epic acceptance (SIMU-74)

**Files:** Extend mixed acceptance and browser fixtures; create `docs/handling-units-upgrade.md` and `docs/handling-units-verification.md`.

**Interfaces:** Connected inbound-to-outbound scenario plus failure injection and measured busy scene.

- [ ] Verify every lifecycle transition, exact endpoint, barcode uniqueness, recipe accounting, single custody, duplicate commands, concurrent allocation, restart, failed handoffs and stale epochs.
- [ ] Benchmark 500 units/64 journeys against declared budget; record browser, host hardware, WebGL renderer, frame intervals, bounded queue and reconnect convergence.
- [ ] Run guarded `make stack-unit` for each app, `make stack-check APP=all` and `make mixed-check`; retain logs and distinguish local evidence from hosted execution.
- [ ] Inspect screenshots/recordings for shelf/truck interaction, concurrent movement, fading trails, readable scene, fallback and reduced motion.
- [ ] Document numbered migrations, conversion/recovery commands, compatibility and measured limitations; audit all epic/child acceptance criteria before claiming completion.

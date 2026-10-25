# Coordinated Robot Fleet Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Implement durable whole-unit robot transport with grid traffic control and departmental receipt gates.

**Architecture:** An independent Flask/PostgreSQL fleet owns physical robot state and complete-trip reservations. Shared grid geometry drives A* routing and Twin rendering. Native departments retain business transactions and clocks; fleet consumes committed watermarks and produces idempotent physical proofs.

**Tech Stack:** Python 3.12, Flask, psycopg, PostgreSQL, existing native C#/Java/Go/PHP backends, React/Three.js.

**Spec:** `docs/superpowers/specs/2026-10-25-simu75-robot-fleet-design.md` (approved).

## Execution status — 2026-10-25

Functional implementation, independent review, native factory acceptance with and
without Twin, loaded process restart, every-phase worker recovery, and actual
native adapter SIGKILL acceptance are verified. See `docs/fleet-verification.md`
and `docs/verification/simu75-local-results.json` for local evidence and limits.
The approved catalog correction changed 93 coordinates while preserving all 800
IDs and shelf heights; this supersedes the original coordinate-preservation step.
The user accepts increased planner latency and plans four dedicated CPU cores
per separately deployed system. Throughput and software-rendered frame targets
remain unmet. Four robots completed the measurement window, eight reached a
partial window, and sixteen remains unmeasured; do not treat that budget step as
complete or claim production performance. No deployment or live cutover occurred.

## Global Constraints

- Build and test services only inside Docker through `scripts/docker_guard.py`; retain 20 GiB reserve.
- Preserve five websites, optional Twin, departmental transaction/native adapter ownership, existing volumes and migration checksums.
- One whole unit per robot; durable run/epoch/worker fencing; no timeout releases physical occupancy.
- Grid default 0.25 m; body 0.85 × 1.05 m; minimum clearance 0.15 m; validate swept load/fork/turn envelopes.
- Proposed fleet default 8, benchmark 4/8/16; 1 m/s translation, 0.5 m/s lift; freshness bound 5 wall seconds.
- No source-driven replay in operational mode; no browser extrapolation or receipt from route completion alone.

## Review Focus

- Geometrically disjoint cells can still overlap bodies or turning forks: test continuous swept envelopes.
- Ahead-of-fleet source clocks can introduce future proofs: gate phases by mapped release/effective times.
- Lost replies and worker takeover can duplicate assignment: test SQL uniqueness and worker generation fencing.
- Destination failures can strand physical occupancy: retain route/load until durable reconciliation.
- Opt-in configuration can be inconsistent across departments: reject mismatched modes/scopes before departure.

### Task 1: Navigation geometry and deterministic planner

**Files:** Create `contracts/fleet/v1/navigation.json`, `apps/fleet/backend/navigation.py`, `apps/fleet/tests/test_navigation.py`, `apps/fleet/Dockerfile`, `apps/fleet/test.compose.yml`.

**Interfaces:** `Navigation(catalog, topology)`, `plan(start, destination, occupied) -> Route | None`, `resources(route) -> set[str]`; poses use world x/z metres plus cardinal heading. Route includes exact connectors and swept exclusions.

- [x] Write navigation tests for deterministic routes, directional parallel lanes, obstacles, turn sweeps, shelf service exclusion, blocked destinations and parking occupancy. Assert clearance geometrically, independent of resource IDs.
- [x] Run guarded Docker pytest; expect missing navigation implementation.
- [x] Implement shared fixed geometry and conservative rasterization with deterministic orthogonal A*; preserve endpoint coordinates and validate off-grid connectors.
- [x] Run guarded navigation tests; expect all passing and report unsupported endpoints explicitly.

### Task 2: Durable fleet ledger and authenticated contracts

**Files:** Create `apps/fleet/backend/store.py`, `contracts/fleet/v1/README.md`, `contracts/fleet/v1/job.schema.json`, `apps/fleet/migrations/001_fleet.sql`, `apps/fleet/tests/test_store.py`, `apps/fleet/backend/api.py`.

**Interfaces:** `FleetStore.admit(command)`, `claim_worker() -> generation`, `assign(job_id, robot_id, route, generation)`, `snapshot()`. API mutations authenticate department identities and bind scopes.

- [x] Write SQL tests for exact/conflicting retries, single active unit/robot, atomic route reservation, audit persistence, concurrent worker takeover and stale generation rejection.
- [x] Run guarded PostgreSQL-backed tests; expect missing ledger.
- [x] Implement dedicated schema/migrations and transactional ledger with immutable request fingerprints, partial uniqueness, exclusive resource rows and fenced worker transactions.
- [x] Implement Flask validation/authentication and snapshot API; malformed/nonfinite/oversized inputs reject with no mutation.
- [x] Run all fleet tests; expect passing real PostgreSQL transactions.

### Task 3: Physical execution, clock and restart recovery

**Files:** Create `apps/fleet/backend/worker.py`, `apps/fleet/backend/clock.py`, `apps/fleet/tests/test_worker.py`, `apps/fleet/tests/test_clock.py`, `apps/fleet/entrypoint.sh`, `apps/fleet/compose.yml`.

**Interfaces:** `tick(generation, observations)` commits pose/phase/proofs at minimum healthy committed source time; `submit_proof(job_id, kind, proof)` deduplicates immutable departure/receipt facts. Snapshot includes route, pose, carried unit, progress and wait/blocker reasons.

- [x] Write tests for future proof gating, pause, stale/reversed time, scope replacement, restart in every phase, no lost load, same-bay/opposing traffic, disjoint concurrency, aging fairness and safe return to occupied parking.
- [x] Run guarded fleet tests; expect missing execution behavior.
- [x] Implement phase machine, complete-trip reservation/parking policy, stable ordering, protected aged requests, durable inbox/outbox and frozen/quarantined state.
- [x] Add independent persistent/test Compose and startup health checks; no native HELICS dependency.
- [x] Run fleet suite and process-restart acceptance; expect unchanged poses/reservations across failures.

### Task 4: Native departmental integration

**Files:** Modify native handling/custody/ledger/controller modules under `apps/storage/backend`, `apps/manufacturing/backend/src/main/java/simu/manufacturing`, `apps/logistics/backend`, `apps/shipping/src`; create their fleet clients and numbered native migrations/tests.

**Interfaces:** Explicit coordinated configuration; durable producer request/departure/receipt outboxes; fleet physical arrival is an additional receipt predicate. All producer events carry committed effective time and mapped fleet scope.

- [x] Add backend regressions for local moves, cross-department handoffs, source/destination downtime, contradictory proof, exact retry, mismatched scope/mode, early arrival and disabled-mode compatibility.
- [x] Run each guarded native unit suite and observe failures for missing coordination.
- [x] Integrate request/approach/depart/arrival/receipt stages transactionally. Defer waiting jobs beyond the current grant so native grant barriers remain live; do not backdate business effects.
- [x] Run all four native unit suites; expect passing coordinated and historical behavior.

### Task 5: Operational Twin and visible grid traffic

**Files:** Create `apps/twin/backend/fleet_projection.py`, `apps/twin/web/src/OperationalFleet.tsx`, `apps/twin/web/src/fleetState.ts`; modify Twin projection/API/Facility3D/inspector and add backend/frontend/browser tests.

**Interfaces:** Optional authenticated fleet source; validated monotonic operational snapshots; replay is disabled for coordinated scopes even if fleet becomes unavailable. Render only committed poses/load transforms.

- [x] Add tests for stale/reordered snapshots, scope replacement, no duplicate static load, selection-independent animation, stable robot/job identity and replay exclusion.
- [x] Run guarded Twin/model tests and observe missing behavior.
- [x] Render grid/reservation overlay and directed lanes from shared topology, operational robots including idle state, queue/blocker identity and accessible inspector. Retain reduced-motion/WebGL fallback.
- [x] Run Twin unit/build/browser acceptance with screenshots; expect visible simultaneous disjoint traffic and truthful stale/hold state.

### Task 6: Mixed acceptance, budgets and operations

**Files:** Create `scripts/check_fleet.sh`, `scripts/fleet_factory_verify.py`, `scripts/fleet_fault_verify.py`, `apps/fleet/README.md`, `docs/fleet-verification.md`; extend Makefile, mixed checks and browser performance fixtures.

- [x] Add deterministic concurrent workflow fixture spanning inbound, shelf/retrieval, manufacturing and outbound; inject process kills and native adapter loss.
- [x] Run guarded fleet/native/mixed/browser checks with Twin absent and present; require no premature business receipt, collision, duplicated assignment or stale lock release.
- [ ] Measure 4/8/16 robots over 600 simulation seconds after warmup, report throughput/wait/utilization and worker p95. Measure rendering with 500 units/16 robots for 30 s including grid overlay.
- [x] Compare observed budgets to approved targets (12 loaded legs/minute at 8 robots, worker p95 <100 ms, render p95 ≤20 ms); document measured topology failures before revising design.
- [x] Document exact verification commands/results, configuration/migrations, opt-in/recovery, local-vs-hosted limits and outstanding evidence.

### Task 7: Final review and verification

- [x] Request an independent whole-change review against approved spec, plan and Review Focus.
- [x] Fix important findings with regression tests; run affected complete suites.
- [x] Check diff hygiene and secret/generated artifact status. Deliver concrete results and material limits without deployment or live cutover.

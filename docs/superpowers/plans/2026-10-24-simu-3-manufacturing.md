# Manufacturing V1 implementation plan

> Execute inline using superpowers:executing-plans. User authorized direct implementation from the approved scope on 2026-10-24.

**Goal:** Complete SIMU-3 with independently deployable finite-capacity production and an Angular employee website.
**Architecture:** Retain Java-owned SQL transactions, durable jobs and RabbitMQ outbox. Add run-scoped manufacturing records and strict typed HELICS inputs/outputs; adapter remains transport only.
**Stack:** Existing Java 21/Spring Boot and Angular/TypeScript locks.
**Spec:** SIMU-3 and `docs/superpowers/specs/2026-10-24-logistics-simulator-design.md`, as superseded by the approved framework migration design.

## Global constraints

- Docker-only builds/tests, serialized guard, 20 GiB reserve; preserve existing volumes and migration checksums.
- Work only in `feat/simu-3-manufacturing-v1` worktree; no live cutover or adjacent repository writes.
- Preserve run/epoch fencing, granted-time eligibility, outstanding-work barriers, roles and atomic audits.

## Review focus

- Concurrent starts must not oversubscribe a line or consume BOM twice.
- Missing materials/power and held orders must defer visibly while allowing time to progress.
- Stale epochs, duplicate facts under new event IDs and uncertain HTTP retries must not duplicate stock/output.
- Worker/database/broker recovery must retain scheduled finishes and authoritative accounting.
- Configuration and zero-good-output scrap cases must validate without emitting invalid storage receipts.

### Task 1: Production domain and API

Files: new `Production.java`, migration `006_manufacturing_production.sql`, `ProductionTest.java`; modify `Store.java`, `Api.java`, `Scenario.java`.
Interfaces: `Production.command(Store,String,JsonNode,Store.Audit)` accepts run/epoch/due/action commands; `Production.snapshot(Store)` returns catalog, lines, materials, orders, movements, command outcomes. `Production.execute(Store,Connection,Map,Map)` executes under existing run lock.
- [x] Add failing HTTP/domain regressions for create/release/hold, shortages, capacity, duration, scrap, concurrent redelivery, audit rollback and fencing.
- [x] Run regressions in guarded PostgreSQL/RabbitMQ containers and confirm missing-route failure.
- [x] Implement strict configuration, additive migration, queued commands and atomic domain transitions.
- [x] Run complete backend suite and dependency-lock comparison.

### Task 2: Providers and connected contracts

Files: `Production.java`, `Policy.java`, `Controller.java`, transport-only `manufacturing_contracts.py`, schemas/fixtures, native peer/check scripts and tests.
Interfaces: Synthetic providers submit the same commands; typed `storage.issue.completed.v1` supplies materials, `manufacturing.demand.v1` supplies orders, storage request/receipt outputs retain correlation. Sample jobs remain compatible.
- [x] Add failing provider/transport regressions, including duplicate aggregate identities and wrong ownership.
- [x] Implement deterministic seeded production, typed boundary validation and correlated facts.
- [x] Verify with real native HELICS peer, external power off/on and duplicate messages.

### Task 3: Employee website

Files: Angular `main.ts`, styles and API tests; manufacturing Playwright acceptance.
Interfaces: `/api/production` snapshot and `/api/production/commands` asynchronous command results.
- [x] Add browser acceptance for creating/releasing/holding an order, shortage details, capacity, completion and employee permissions.
- [x] Build searchable work-order board, details, materials/capacity and production audit from real API state. Preserve exact failed command body/key for retry.
- [x] Run frontend tests/build and desktop/mobile browser checks, save screenshots.

### Task 4: Packaging and acceptance

Files: independent Compose/env example, manufacturing documentation, verification scripts, Makefile/CI integration and shared Docker guard isolation.
- [x] Verify persistent and external dependency configuration with disposable project names.
- [x] Exercise standalone automation, employee intervention, worker replicas, broker/worker restart and stale deliveries.
- [x] Run stack unit/check, manufacturing connected/deployment checks. Record exact results and hosted/physical-host limits.
- [x] Obtain whole-branch review, fix important findings, commit focused changes and retain worktree for user integration.

Completed evidence and decisions: [SIMU-3 acceptance](../../simu-3-acceptance.md).

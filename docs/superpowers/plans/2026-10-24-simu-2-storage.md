# Storage V1 Implementation Plan

> **For agentic workers:** Execute inline using superpowers:executing-plans, with a fresh whole-change review before completion.

**Goal:** Implement SIMU-2's independently runnable warehouse lifecycle.

**Architecture:** Extend the approved storage-owned ASP.NET Core/Vue foundation. Run warehouse commands through existing durable jobs and RabbitMQ, under the run lock and granted-time barrier. Persist stock, workflow state, movement history, command outcomes and boundary output in one PostgreSQL transaction.

**Tech Stack:** Existing pinned C#, ASP.NET Core, Vue/TypeScript, PostgreSQL, RabbitMQ and private HELICS adapter.

**Spec:** SIMU-2 and `docs/superpowers/specs/2026-10-24-logistics-simulator-design.md`; the approved framework migration supersedes historical Python/React choices.

## Global Constraints

- Build and test only in Docker through scripts/docker_guard.py; retain 20 GiB reserve.
- Preserve existing migrations, data volumes, HTTP sample contracts and run/epoch/time fencing.
- Keep department-owned transactions and explicit synthetic/HELICS boundary ownership.
- Employee permissions exclude run administration; credential state remains in memory.

## Review Focus

- Concurrent reservations and duplicate receipt/arrival commands must conserve stock.
- Failed capacity or state checks must roll back all inventory, movement and workflow writes.
- Resets must fence queued commands and isolate previous inventory.
- Uncertain HTTP outcomes must retain command identity; asynchronous rejection must be visible.
- Synthetic transfer completion must never run for a HELICS-owned boundary.

### Task 1: Durable warehouse accounting

Files: new backend `Warehouse.cs`, migration `006_storage_warehouse.sql`, tests `WarehouseTests.cs`; modify `Ledger.cs`, `Program.cs`.
Interfaces: `Warehouse.Submit(key, body, audit)` returns scheduled command; `Warehouse.Snapshot()` returns run-scoped inventory and work lists; `Warehouse.Execute(u, run, job)` applies atomic workflow effects.

- [x] Write real-PostgreSQL lifecycle, concurrency, duplicate, capacity, rollback and epoch regressions; run `make stack-unit APP=storage` and observe missing warehouse behavior.
- [x] Implement expected receipts/receive, reserve/release, issue, pick, depart/arrive transfers, persisted outcomes and movements. Validate strict quantities, identifiers, correlation and workflow state. Append a numbered migration only.
- [x] Run the complete native assertion harness through `make stack-unit APP=storage`.

### Task 2: Autonomous and connected boundaries

Files: Warehouse.cs, Ledger.cs, Controller.cs, domain contract and fixtures.
Interfaces: domain receipt/request/arrival envelopes enter the same command scheduler; domain fact envelopes retain correlation, epoch and stable event identity through adapter publication.

- [x] Add seeded standalone lifecycle and domain envelope regressions before implementation.
- [x] Schedule deterministic suppliers and production/customer demand, automatic valid task actions and synthetic transfer arrival only for configured synthetic boundaries.
- [x] Preserve sample compatibility and test duplicate boundary ingestion and wrong ownership/epoch.

### Task 3: Employee website and end-to-end acceptance

Files: Vue warehouse component and tests, existing App.vue, browser acceptance, storage HTTP/recovery script and documentation.
Interfaces: GET /api/warehouse; POST /api/warehouse/commands with Idempotency-Key and explicit run_id/epoch/due_at.

- [x] Add failing UI behavior and HTTP acceptance tests for stock quantities, workflow actions and asynchronous errors.
- [x] Implement searchable inventory, receipt/reservation/transfer lists, movements and pending/rejected command results, preserving operator-only controls.
- [x] Run `make stack-check APP=storage` including worker restart and browser lifecycle; inspect desktop/mobile screenshots.
- [x] Document configuration, contracts, acceptance evidence and local versus hosted limitations; obtain fresh code review and resolve important findings.

## Integration verification

- [x] Run the warehouse HTTP lifecycle with two real worker replicas; preserve physical stock through a broker outage and apply recovered receipts once.
- [x] Verify fresh persistent deployment startup with optional health-gated local dependencies and zero backend restarts; retain external-address profile support.
- [x] Run 126 native checks, 70 shared Python tests/schema parity, production stack/browser acceptance and actual HELICS domain acceptance before integration.
- [x] Include Storage V1 startup and native domain checks in the storage CI job.
